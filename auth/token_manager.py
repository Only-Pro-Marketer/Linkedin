"""Manage LinkedIn OAuth tokens — storage, retrieval, and refresh."""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from database.models import OAuthToken


class TokenManager:
    """Handles OAuth token lifecycle: store, retrieve, refresh, and expiry checks."""

    def __init__(self, db: Session):
        self.db = db

    def store_token(
        self,
        access_token: str,
        expires_in: int,
        person_urn: str,
        refresh_token: str | None = None,
        refresh_token_expires_in: int | None = None,
        scopes: str = "",
    ) -> OAuthToken:
        """Store a new OAuth token, replacing any existing one."""
        # Remove old tokens
        self.db.query(OAuthToken).delete()

        expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        refresh_expires_at = None
        if refresh_token_expires_in:
            refresh_expires_at = datetime.utcnow() + timedelta(
                seconds=refresh_token_expires_in
            )

        token = OAuthToken(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            refresh_expires_at=refresh_expires_at,
            scopes=scopes,
            person_urn=person_urn,
        )
        self.db.add(token)
        self.db.commit()
        self.db.refresh(token)
        return token

    def get_current_token(self) -> OAuthToken | None:
        """Get the most recent stored token."""
        return self.db.query(OAuthToken).order_by(OAuthToken.id.desc()).first()

    def get_valid_access_token(self) -> str | None:
        """Return a valid access token, or None if expired/missing."""
        token = self.get_current_token()
        if not token:
            return None

        # Check if access token is still valid (with 5 min buffer)
        if token.expires_at > datetime.utcnow() + timedelta(minutes=5):
            return token.access_token

        return None

    def get_person_urn(self) -> str | None:
        """Return the stored person URN."""
        token = self.get_current_token()
        return token.person_urn if token else None

    def is_authenticated(self) -> bool:
        """Check if we have a valid (or refreshable) token."""
        token = self.get_current_token()
        if not token:
            return False
        # Valid access token
        if token.expires_at > datetime.utcnow():
            return True
        # Has refresh token that hasn't expired
        if token.refresh_token and (
            not token.refresh_expires_at
            or token.refresh_expires_at > datetime.utcnow()
        ):
            return True
        return False

    def needs_refresh(self) -> bool:
        """Check if the access token needs refreshing (expires within 7 days)."""
        token = self.get_current_token()
        if not token:
            return False
        return token.expires_at < datetime.utcnow() + timedelta(days=7)

    def get_token_status(self) -> dict:
        """Return token status info for the dashboard."""
        token = self.get_current_token()
        if not token:
            return {"authenticated": False, "status": "Not connected"}

        now = datetime.utcnow()
        access_valid = token.expires_at > now
        days_left = (token.expires_at - now).days if access_valid else 0

        scopes_list = token.scopes.split() if token.scopes else []
        has_read_scope = "r_member_social" in scopes_list

        return {
            "authenticated": self.is_authenticated(),
            "status": "Connected" if access_valid else "Expired",
            "access_token_expires": token.expires_at.isoformat(),
            "access_days_left": days_left,
            "has_refresh_token": bool(token.refresh_token),
            "person_urn": token.person_urn,
            "scopes": scopes_list,
            "has_read_scope": has_read_scope,
        }

    def update_token(
        self,
        access_token: str,
        expires_in: int,
        refresh_token: str | None = None,
        refresh_token_expires_in: int | None = None,
    ) -> OAuthToken | None:
        """Update the existing token after a refresh."""
        token = self.get_current_token()
        if not token:
            return None

        token.access_token = access_token
        token.expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

        if refresh_token:
            token.refresh_token = refresh_token
        if refresh_token_expires_in:
            token.refresh_expires_at = datetime.utcnow() + timedelta(
                seconds=refresh_token_expires_in
            )

        token.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(token)
        return token
