"""Health endpoints (docs/HRMS_COMPLETE_SPEC.txt Part 13 section C): /healthz (liveness --
the process answers), /readyz (readiness -- tenant DB, control plane and, if configured,
Redis all reachable; 503 otherwise so the load balancer stops routing here), and the
existing /health kept for backwards compatibility."""

import time

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text

from app.core.config import settings

router = APIRouter(tags=["ops"])


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


def _check_db(engine_factory) -> dict:
    start = time.perf_counter()
    try:
        engine = engine_factory()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True, "ms": round((time.perf_counter() - start) * 1000, 1)}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}


@router.get("/readyz")
def readyz():
    from app.core.database import engine as app_engine
    from app.platform.tenancy.database_cp import control_plane_engine

    checks = {"database": _check_db(lambda: app_engine), "control_plane": _check_db(lambda: control_plane_engine)}
    if settings.REDIS_URL:
        try:
            import redis

            redis.Redis.from_url(settings.REDIS_URL, socket_timeout=0.5).ping()
            checks["redis"] = {"ok": True}
        except Exception as exc:
            checks["redis"] = {"ok": False, "error": type(exc).__name__}
    ready = all(c["ok"] for c in checks.values())
    return JSONResponse(status_code=200 if ready else 503, content={"status": "ready" if ready else "not_ready", "checks": checks})


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(authorization: str = Header(default="")):
    from app.platform.ops.observability import METRICS

    if settings.METRICS_TOKEN and authorization != f"Bearer {settings.METRICS_TOKEN}":
        raise HTTPException(status_code=401, detail="metrics token required")
    return PlainTextResponse(METRICS.render(), media_type="text/plain; version=0.0.4")
