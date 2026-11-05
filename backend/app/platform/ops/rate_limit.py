"""Per-tenant / per-user rate limiting (docs/HRMS_COMPLETE_SPEC.txt Part 13 section C:
"rate limiting per tenant/user ... noisy-tenant protection").

Fixed one-minute windows, three independent budgets: the whole tenant, the signed-in user
(JWT `sub`), and anonymous callers by client IP. Redis (`REDIS_URL`) is the shared counter
store across API replicas; without it an in-process counter is used (correct for a
single replica, which is every MODE 1 dev/UAT stack). Keys carry the `t:{tenant_id}:`
prefix from section B. Health/metrics endpoints are never limited.
"""

import threading
import time
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings
from app.platform.tenancy.context import get_current_tenant

_EXEMPT_PATHS = ("/healthz", "/readyz", "/health", "/metrics")


class _MemoryCounter:
    def __init__(self):
        self._lock = threading.Lock()
        self._counts: dict[str, tuple[int, int]] = {}

    def hit(self, key: str, window: int) -> int:
        with self._lock:
            current_window, count = self._counts.get(key, (window, 0))
            if current_window != window:
                count = 0
            count += 1
            self._counts[key] = (window, count)
            if len(self._counts) > 50_000:  # drop stale windows so memory stays bounded
                self._counts = {k: v for k, v in self._counts.items() if v[0] == window}
            return count


_memory = _MemoryCounter()
_redis = None


def _redis_client():
    global _redis
    if _redis is None and settings.REDIS_URL:
        try:
            import redis  # optional dependency

            _redis = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=0.2)
        except Exception:
            _redis = False
    return _redis or None


def _hit(key: str, window: int) -> int:
    client = _redis_client()
    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.incr(key)
            pipe.expire(key, 120)
            return int(pipe.execute()[0])
        except Exception:
            pass  # Redis blip -> degrade to the local counter rather than failing requests
    return _memory.hit(key, window)


def _user_sub(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    try:
        from app.core.security import decode_access_token

        return str(decode_access_token(auth.split(" ", 1)[1]).get("sub"))
    except Exception:
        return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.RATE_LIMIT_ENABLED or request.url.path.startswith(_EXEMPT_PATHS):
            return await call_next(request)
        window = int(time.time() // 60)
        tenant = get_current_tenant()
        prefix = f"t:{tenant.tenant_id}:" if tenant else "t:none:"
        checks = [(f"{prefix}rl:tenant:{window}", settings.RATE_LIMIT_TENANT_PER_MINUTE)]
        sub = _user_sub(request)
        if sub:
            checks.append((f"{prefix}rl:user:{sub}:{window}", settings.RATE_LIMIT_USER_PER_MINUTE))
        else:
            ip = request.client.host if request.client else "unknown"
            checks.append((f"{prefix}rl:ip:{ip}:{window}", settings.RATE_LIMIT_ANON_PER_MINUTE))
        for key, limit in checks:
            if _hit(key, window) > limit:
                retry = 60 - int(time.time() % 60)
                return JSONResponse(status_code=429, headers={"Retry-After": str(retry)},
                                    content={"detail": {"code": "RATE_LIMITED", "message": "Too many requests -- please wait a moment and try again.", "retry_after_seconds": retry}})
        return await call_next(request)
