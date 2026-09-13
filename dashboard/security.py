"""Dashboard security: CSRF (same-origin) check and optional password login."""

import asyncio
import hmac
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from config import LOOPBACK_HOSTS, settings

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
PUBLIC_PREFIXES = ("/static/", "/login", "/logout", "/favicon")
ANY_ADDRESS = ("0.0.0.0", "::")


def allowed_hosts() -> list[str]:
    """Host names the dashboard answers to.

    Blocks DNS rebinding: a malicious site that points its own domain at
    127.0.0.1 still sends its domain in the Host header, so it gets a 400.
    Extra names (e.g. a LAN hostname) go in ALLOWED_HOSTS.
    """
    extra = [h.strip() for h in settings.ALLOWED_HOSTS.split(",") if h.strip()]
    if settings.HOST in ANY_ADDRESS and settings.DASHBOARD_PASSWORD and not extra:
        return ["*"]  # listening on the network with a password: the login protects it
    hosts = ["localhost", "127.0.0.1", "::1", *extra]
    if settings.HOST not in LOOPBACK_HOSTS and settings.HOST not in ANY_ADDRESS:
        hosts.append(settings.HOST)
    return hosts


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Stop other sites from framing the dashboard (clickjacking) and browsers from MIME sniffing."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response


def _same_origin(request: Request) -> bool:
    """True if the request carries proof it came from this dashboard.

    Our fetch() shim adds X-Requested-With to every same-origin write. A
    cross-site page cannot set that header without a CORS preflight (which we
    never allow). Plain HTML form posts are accepted when Origin/Referer match.
    """
    if request.headers.get("x-requested-with"):
        return True
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin:
        return False
    parsed = urlparse(origin)
    return parsed.netloc == request.headers.get("host", "")


class SameOriginMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in UNSAFE_METHODS and not _same_origin(request):
            return JSONResponse({"error": "Cross-site request blocked"}, status_code=403)
        return await call_next(request)


class LoginRequiredMiddleware(BaseHTTPMiddleware):
    """When DASHBOARD_PASSWORD is set, every page and API needs a login."""

    async def dispatch(self, request: Request, call_next):
        if not settings.DASHBOARD_PASSWORD:
            return await call_next(request)
        path = request.url.path
        if path.startswith(PUBLIC_PREFIXES) or request.session.get("auth") is True:
            return await call_next(request)
        if path.startswith("/api/") or path.startswith("/auth/status"):
            return JSONResponse({"error": "Login required"}, status_code=401)
        return RedirectResponse(f"/login?next={quote(path)}", status_code=303)


router = APIRouter(tags=["auth-ui"])

_LOGIN_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in · Content Engine</title>
<style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f5f5f7;
font-family:Inter,-apple-system,BlinkMacSystemFont,system-ui,sans-serif;color:#1d1d1f}
.card{background:#fff;border-radius:20px;padding:36px;width:min(360px,90vw);
box-shadow:0 1px 3px rgba(0,0,0,.06),0 8px 24px rgba(0,0,0,.06)}
h1{font-size:22px;margin:0 0 6px}p{margin:0 0 22px;color:#6e6e73;font-size:14px}
input{width:100%;box-sizing:border-box;padding:12px 14px;border:1px solid #d2d2d7;
border-radius:12px;font-size:15px}input:focus{outline:2px solid #0071e3;border-color:transparent}
button{margin-top:14px;width:100%;padding:12px;border:0;border-radius:12px;background:#0f0f0f;
color:#fff;font-size:15px;font-weight:600;cursor:pointer}.err{color:#d70015;font-size:13px;margin-top:10px}
</style></head><body><form class="card" method="post" action="/login">
<h1>Content Engine</h1><p>Enter your dashboard password.</p>
<input type="hidden" name="next" value="__NEXT__">
<input type="password" name="password" placeholder="Password" autofocus autocomplete="current-password">
<button type="submit">Sign in</button>__ERR__</form></body></html>"""


def _safe_next(next_path: str) -> str:
    """Only local paths. Browsers treat "\\" like "/", so "/\\evil.com" is an off-site link."""
    path = next_path or ""
    if (not path.startswith("/") or path.startswith("//") or "\\" in path
            or any(ord(c) < 32 or ord(c) == 127 for c in path)):
        return "/"
    return path


def _login_html(next_path: str, error: str = "") -> str:
    from html import escape
    err = f'<div class="err">{escape(error)}</div>' if error else ""
    return _LOGIN_PAGE.replace("__NEXT__", escape(_safe_next(next_path))).replace("__ERR__", err)


@router.get("/login", response_class=HTMLResponse)
async def login_page(next: str = "/"):
    if not settings.DASHBOARD_PASSWORD:
        return RedirectResponse("/", status_code=303)
    return HTMLResponse(_login_html(next))


@router.post("/login")
async def login_submit(request: Request, password: str = Form(""), next: str = Form("/")):
    expected = settings.DASHBOARD_PASSWORD
    if expected and hmac.compare_digest(password.encode(), expected.encode()):
        request.session["auth"] = True
        return RedirectResponse(_safe_next(next), status_code=303)
    await asyncio.sleep(1)  # slow down guessing
    return HTMLResponse(_login_html(next, "Wrong password."), status_code=401)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login" if settings.DASHBOARD_PASSWORD else "/", status_code=303)
