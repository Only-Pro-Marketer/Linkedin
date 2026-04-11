"""LinkedIn OAuth 2.0 three-legged flow + FastAPI routes."""

import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from auth.token_manager import TokenManager
from config import settings
from database.engine import get_db

router = APIRouter(tags=["auth"])

# In-memory state store for CSRF protection during OAuth
# Stores {state_token: creation_timestamp} with 10-minute expiry
_oauth_states: dict[str, datetime] = {}
_OAUTH_STATE_EXPIRY_MINUTES = 10

SCOPES = ["openid", "profile", "w_member_social", "r_member_social"]

AUTHORIZATION_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
PROFILE_URL = "https://api.linkedin.com/v2/me"


@router.get("/login")
async def oauth_login():
    """Redirect user to LinkedIn authorization page."""
    state = secrets.token_urlsafe(32)
    # Purge expired states to prevent memory leak
    now = datetime.utcnow()
    expired = [s for s, ts in _oauth_states.items() if now - ts > timedelta(minutes=_OAUTH_STATE_EXPIRY_MINUTES)]
    for s in expired:
        del _oauth_states[s]
    _oauth_states[state] = now

    params = {
        "response_type": "code",
        "client_id": settings.LINKEDIN_CLIENT_ID,
        "redirect_uri": settings.LINKEDIN_REDIRECT_URI,
        "state": state,
        "scope": " ".join(SCOPES),
    }
    url = f"{AUTHORIZATION_URL}?{urlencode(params)}"
    return RedirectResponse(url=url)


@router.get("/callback")
async def oauth_callback(
    code: str = "",
    state: str = "",
    error: str = "",
    error_description: str = "",
    db: Session = Depends(get_db),
):
    """Handle LinkedIn OAuth callback — exchange code for tokens."""
    if error:
        return JSONResponse(
            {"error": error, "description": error_description}, status_code=400
        )

    # Verify state for CSRF protection
    if state not in _oauth_states:
        return JSONResponse({"error": "Invalid state parameter"}, status_code=400)
    state_created = _oauth_states.pop(state)
    if datetime.utcnow() - state_created > timedelta(minutes=_OAUTH_STATE_EXPIRY_MINUTES):
        return JSONResponse({"error": "OAuth state expired — please try again"}, status_code=400)

    if not code:
        return JSONResponse({"error": "No authorization code received"}, status_code=400)

    # Exchange code for access token
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.LINKEDIN_REDIRECT_URI,
                "client_id": settings.LINKEDIN_CLIENT_ID,
                "client_secret": settings.LINKEDIN_CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if token_response.status_code != 200:
            return JSONResponse(
                {"error": "Token exchange failed. Please try connecting again."},
                status_code=400,
            )

        try:
            token_data = token_response.json()
        except Exception:
            return JSONResponse(
                {"error": "Invalid response from LinkedIn. Please try again."},
                status_code=400,
            )

        # Get person URN — try multiple endpoints
        person_urn = None
        access = token_data["access_token"]
        rest_headers = {
            "Authorization": f"Bearer {access}",
            "LinkedIn-Version": "202602",
            "X-Restli-Protocol-Version": "2.0.0",
        }

        # Try /v2/userinfo (works with openid scope)
        resp = await client.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {access}"},
        )
        if resp.status_code == 200:
            person_urn = f"urn:li:person:{resp.json()['sub']}"

        # Fallback: try /v2/me
        if not person_urn:
            resp = await client.get(PROFILE_URL, headers={"Authorization": f"Bearer {access}"})
            if resp.status_code == 200:
                person_urn = f"urn:li:person:{resp.json()['id']}"

        # Fallback: try REST /rest/me with versioned headers
        if not person_urn:
            resp = await client.get("https://api.linkedin.com/rest/me", headers=rest_headers)
            if resp.status_code == 200:
                person_urn = f"urn:li:person:{resp.json().get('id', resp.json().get('sub', ''))}"

        # Fallback: decode id_token JWT if present
        if not person_urn and "id_token" in token_data:
            import json as _json, base64 as _b64
            payload = token_data["id_token"].split(".")[1]
            payload += "=" * (4 - len(payload) % 4)
            decoded = _json.loads(_b64.urlsafe_b64decode(payload))
            person_urn = f"urn:li:person:{decoded.get('sub', '')}"

        # Last resort: try token introspection endpoint
        if not person_urn:
            resp = await client.post(
                "https://www.linkedin.com/oauth/v2/introspectToken",
                data={
                    "token": access,
                    "client_id": settings.LINKEDIN_CLIENT_ID,
                    "client_secret": settings.LINKEDIN_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code == 200:
                intro = resp.json()
                if "authorized_at" in intro or "client_id" in intro:
                    # Introspection worked but may not have sub
                    if "sub" in intro:
                        person_urn = f"urn:li:person:{intro['sub']}"

        if not person_urn:
            return JSONResponse(
                {
                    "error": "Token obtained but could not determine person ID automatically.",
                    "hint": "Please check the Settings page.",
                },
                status_code=400,
            )

    # Store token
    token_manager = TokenManager(db)
    token_manager.store_token(
        access_token=token_data["access_token"],
        expires_in=token_data.get("expires_in", 5184000),  # Default 60 days
        person_urn=person_urn,
        refresh_token=token_data.get("refresh_token"),
        refresh_token_expires_in=token_data.get("refresh_token_expires_in"),
        scopes=" ".join(SCOPES),
    )

    # Redirect to dashboard with success
    return RedirectResponse(url="/?auth=success")


@router.get("/status")
async def auth_status(db: Session = Depends(get_db)):
    """Return current authentication status."""
    token_manager = TokenManager(db)
    return JSONResponse(token_manager.get_token_status())


@router.post("/refresh")
async def refresh_token(db: Session = Depends(get_db)):
    """Manually trigger a token refresh."""
    token_manager = TokenManager(db)
    current = token_manager.get_current_token()

    if not current or not current.refresh_token:
        return JSONResponse(
            {"error": "No refresh token available"}, status_code=400
        )

    async with httpx.AsyncClient() as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": current.refresh_token,
                "client_id": settings.LINKEDIN_CLIENT_ID,
                "client_secret": settings.LINKEDIN_CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if response.status_code != 200:
            return JSONResponse(
                {"error": "Token refresh failed. Please reconnect your LinkedIn account."},
                status_code=400,
            )

        try:
            data = response.json()
        except Exception:
            return JSONResponse(
                {"error": "Invalid response during token refresh."},
                status_code=400,
            )
        token_manager.update_token(
            access_token=data["access_token"],
            expires_in=data.get("expires_in", 5184000),
            refresh_token=data.get("refresh_token"),
            refresh_token_expires_in=data.get("refresh_token_expires_in"),
        )

    return JSONResponse({"status": "Token refreshed successfully"})
