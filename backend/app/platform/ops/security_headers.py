"""Security response headers (docs/HRMS_COMPLETE_SPEC.txt Part 13 section D: CSP/HSTS).

JSON API responses get a lock-down CSP (they are never rendered as documents). The few
server-rendered HTML pages (one-click approval, interview confirmation/negotiation) use
inline styles and one inline script, so they get a self-only policy that allows inline.
The SPA's own CSP is set by the frontend nginx config (deploy/nginx/default.conf).
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.config import settings

API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
HTML_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
    "base-uri 'self'; form-action 'self'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        response.headers.setdefault("Content-Security-Policy", HTML_CSP if content_type.startswith("text/html") else API_CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if settings.HSTS_ENABLED:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response
