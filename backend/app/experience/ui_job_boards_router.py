"""Part 18.9: Settings > Integrations > Job boards (LinkedIn, Naukri, Indeed, Monster, Shine).

- GET    /api/v1/ui/job-boards                 each board: saved?, tested?, what it needs, the ways that work today
- POST   /api/v1/ui/job-boards/{code}/connect  {secrets}: saves the credentials (secret store) + routes jobboard.<code>
- POST   /api/v1/ui/job-boards/{code}/test     tests the saved connection (plain answer if the board's API isn't built yet)
- DELETE /api/v1/ui/job-boards/{code}          disconnect (route + connection removed)

Pulling candidates straight from a board needs that board's partner API (LinkedIn Recruiter
System Connect, Naukri RMS / Resdex API, Indeed partner API). Until a board's adapter exists
the connection is stored and shown as "Saved - waiting for API access", and the two ways that
work today are offered instead: upload the resumes downloaded from the board (tagged with the
board as source), or forward the board's application emails to the company mailbox.
"""

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.auth.dependencies import require_roles
from app.core.database import get_db
from app.models.connection import Connection, ConnectionRoute
from app.models.user import User
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/ui/job-boards", tags=["ui-job-boards"])

# code -> (provider code in the connector catalog or None, what the company needs)
BOARDS = {
    "linkedin": ("linkedin_jobs", "linkedin_needs"),
    "naukri": ("naukri", "naukri_needs"),
    "indeed": ("indeed", "indeed_needs"),
    "monster": (None, "monster_needs"),
    "shine": (None, "shine_needs"),
}


def _board(code: str):
    if code not in BOARDS:
        raise HTTPException(status_code=404, detail="Unknown job board")
    return BOARDS[code]


def _connection(db, tenant, code: str):
    route = db.query(ConnectionRoute).filter(ConnectionRoute.tenant_id == tenant.tenant_id, ConnectionRoute.purpose == f"jobboard.{code}").first()
    return (route, db.get(Connection, route.connection_id)) if route else (None, None)


def _mailbox_address(db, tenant) -> str | None:
    from app.platform.connectors.router import ConnectorRouter

    resolved = ConnectorRouter(db).try_resolve("email.inbound.candidate_applications")
    if resolved is None:
        return None
    cfg = resolved.connection.config_json or {}
    return cfg.get("username") or cfg.get("email") or cfg.get("from_address")


@router.get("")
def list_boards(db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin", "recruiter"))):
    from app.platform.connectors.registry import get_provider

    tenant = require_current_tenant()
    out = []
    for code, (provider, needs) in BOARDS.items():
        spec = None
        if provider:
            try:
                spec = get_provider(provider)
            except KeyError:
                spec = None
        _route, conn = _connection(db, tenant, code)
        result = (conn.last_test_result or {}) if conn else {}
        api_ready = bool(spec and spec.adapter_cls is not None)
        live = bool(conn and api_ready and conn.status == "active" and result.get("success"))
        out.append({
            "code": code, "provider_code": provider, "needs": needs, "fields": list(spec.secret_fields) if spec else [],
            "saved": conn is not None, "api_ready": api_ready, "connected": live,
            "state": "connected" if live else "saved" if conn else "not_set_up",
            "last_tested_at": conn.last_tested_at.isoformat() if conn and conn.last_tested_at else None,
            "last_error": result.get("error") if conn else None,
        })
    return {"boards": out, "mailbox": _mailbox_address(db, tenant)}


class ConnectBody(BaseModel):
    secrets: dict[str, str]


@router.post("/{code}/connect")
def connect(code: str, body: ConnectBody, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    from app.platform.connectors.api_router import _tenant_secret_store
    from app.platform.connectors.registry import get_provider

    provider, _needs = _board(code)
    if provider is None:
        raise HTTPException(status_code=400, detail="This board has no API connection; use the resume upload or email forwarding instead.")
    spec = get_provider(provider)
    missing = [f for f in spec.secret_fields if not (body.secrets.get(f) or "").strip()]
    if missing:
        raise HTTPException(status_code=400, detail=f"Please fill in: {', '.join(missing)}")
    tenant = require_current_tenant()
    route, conn = _connection(db, tenant, code)
    ref = conn.secret_ref if conn and conn.secret_ref else f"connection-{uuid.uuid4()}"
    _tenant_secret_store(db).put(ref, json.dumps({f: body.secrets[f] for f in spec.secret_fields}), created_by=current_user.email)
    if conn is None:
        conn = Connection(tenant_id=tenant.tenant_id, name=f"{code.capitalize()} job board", provider_code=provider, capability=list(spec.capabilities),
                          config_json={}, secret_ref=ref, status="draft", owner_user_id=current_user.id, created_by=current_user.email)
        db.add(conn)
        db.flush()
        db.add(ConnectionRoute(tenant_id=tenant.tenant_id, purpose=f"jobboard.{code}", connection_id=conn.id, enabled=True))
    conn.secret_ref = ref
    db.commit()
    log_action(db, "connection", conn.id, "job_board_saved", current_user.email[:50], {"board": code})
    return test(code, db, current_user)


@router.post("/{code}/test")
def test(code: str, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    from app.platform.connectors.api_router import _build_adapter
    from app.platform.connectors.registry import NotYetImplementedProviderError

    _board(code)
    tenant = require_current_tenant()
    _route, conn = _connection(db, tenant, code)
    if conn is None:
        raise HTTPException(status_code=404, detail="Nothing is saved for this board yet.")
    try:
        result = _build_adapter(conn, db).test_connection()
        ok, error = bool(result.success), result.error
    except NotYetImplementedProviderError:
        ok, error = False, "API_NOT_AVAILABLE"
    except Exception as exc:  # noqa: BLE001
        ok, error = False, str(exc)[:300]
    conn.last_tested_at = datetime.now(timezone.utc)
    conn.last_test_result = {"success": ok, "error": error}
    if ok:
        conn.status = "active"
    db.commit()
    return {"code": code, "ok": ok, "error": error}


@router.delete("/{code}", status_code=204)
def disconnect(code: str, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    _board(code)
    tenant = require_current_tenant()
    route, conn = _connection(db, tenant, code)
    if route is not None:
        db.delete(route)
    if conn is not None:
        db.query(ConnectionRoute).filter(ConnectionRoute.connection_id == conn.id).delete(synchronize_session=False)
        db.delete(conn)
    db.commit()
    log_action(db, "connection", None, "job_board_disconnected", current_user.email[:50], {"board": code})
    return None
