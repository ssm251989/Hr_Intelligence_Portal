"""Part 17.13: replay the first response for a repeated `Idempotency-Key` (POST/PUT/PATCH).

Only JSON responses below 500 are kept (a failed call may be retried for real), for 24 hours,
per company. A key reused for a DIFFERENT path is refused (409) rather than guessed at."""

from datetime import datetime, timedelta, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

KEEP = timedelta(hours=24)
# never stored: sign-in / password / MFA responses carry credentials
_NEVER = ("/auth/", "/api/v1/public/auth", "/set-password")
MAX_BODY = 256 * 1024


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        key = request.headers.get("idempotency-key")
        if not key or request.method not in ("POST", "PUT", "PATCH") or len(key) > 200 or request.url.path.startswith(_NEVER)                 or "password" in request.url.path or "mfa" in request.url.path:
            return await call_next(request)
        from app.core.database import SessionLocal
        from app.models.idempotency import IdempotencyKey
        from app.platform.tenancy.context import get_current_tenant

        tenant = get_current_tenant()
        if tenant is None:
            return await call_next(request)
        db = SessionLocal()
        try:
            row = db.query(IdempotencyKey).filter(IdempotencyKey.tenant_id == tenant.tenant_id, IdempotencyKey.key == key).first()
            if row is not None and row.created_at and row.created_at > datetime.now(timezone.utc) - KEEP:
                if row.path != request.url.path or row.method != request.method:
                    return JSONResponse(status_code=409, content={"detail": "This Idempotency-Key was already used for a different request."})
                return Response(content=row.body or "", status_code=row.status_code, media_type=row.content_type or "application/json",
                                headers={"Idempotent-Replay": "true"})
            response = await call_next(request)
            if response.status_code >= 500 or "json" not in (response.headers.get("content-type") or ""):
                return response
            body = b"".join([chunk async for chunk in response.body_iterator])
            if len(body) <= MAX_BODY:
                if row is not None:
                    db.delete(row)
                    db.flush()
                db.add(IdempotencyKey(tenant_id=tenant.tenant_id, key=key, method=request.method, path=request.url.path,
                                      status_code=response.status_code, body=body.decode("utf-8", errors="replace"),
                                      content_type=response.headers.get("content-type")))
                db.commit()
            headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
            return Response(content=body, status_code=response.status_code, headers=headers, media_type=response.media_type)
        finally:
            db.close()
