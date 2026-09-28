"""Connections API (docs/HRMS_COMPLETE_SPEC.txt Part 3 section 6). Gated by
require_roles("admin") -- interim stand-in for platform.connections.manage until Part 5's
IAM/RBAC exists."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import require_roles
from app.core.database import get_db
from app.models.connection import Connection, ConnectionAttempt, ConnectionRoute
from app.models.user import User
from app.platform.connectors.providers import register_all as register_providers
from app.platform.connectors.purposes import all_purposes
from app.platform.connectors.registry import NotYetImplementedProviderError, all_providers, get_provider
from app.platform.connectors.router import ConnectorRouter
from app.platform.secrets.store import get_secret_store
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/connectors", tags=["connectors"])
connections_router = APIRouter(prefix="/api/v1/connections", tags=["connections"])
routes_router = APIRouter(prefix="/api/v1/connection-routes", tags=["connection-routes"])

register_providers()


def _tenant_secret_store(db: Session):
    from app.models.secret import Secret, SecretScope

    tenant = require_current_tenant()
    return get_secret_store(db, Secret, SecretScope, str(tenant.tenant_id))


def _build_adapter(connection: Connection, db: Session):
    spec = get_provider(connection.provider_code)
    if spec.adapter_cls is None:
        raise NotYetImplementedProviderError(f"{connection.provider_code} has no adapter implementation yet")
    secrets: dict[str, str] = {}
    if connection.secret_ref:
        store = _tenant_secret_store(db)
        import json

        secrets = json.loads(store.get(connection.secret_ref))
    return spec.adapter_cls(connection.config_json or {}, secrets)


# ---- providers/purposes catalog ----


class ProviderCatalogEntry(BaseModel):
    code: str
    capabilities: list[str]
    config_schema: dict
    secret_fields: list[str]
    oauth: Optional[dict]
    implemented: bool


@router.get("/providers", response_model=list[ProviderCatalogEntry])
def list_providers(current_user: User = Depends(require_roles("admin"))):
    return [
        ProviderCatalogEntry(
            code=p.code, capabilities=list(p.capabilities), config_schema=p.config_schema,
            secret_fields=list(p.secret_fields), oauth=p.oauth, implemented=p.adapter_cls is not None,
        )
        for p in all_providers()
    ]


class PurposeStatus(BaseModel):
    purpose: str
    routed: bool


@router.get("/purposes", response_model=list[PurposeStatus])
def list_purposes(db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    # Part 18.2/18.3: "routed" = the router really finds a connection (fallbacks and the one
    # company mailbox included), not just "a row exists for this exact purpose".
    from app.platform.connectors.router import ConnectorRouter

    require_current_tenant()
    resolver = ConnectorRouter(db)
    return [PurposeStatus(purpose=p, routed=resolver.try_resolve(p) is not None) for p in all_purposes()]


# ---- connections CRUD ----


class ConnectionCreate(BaseModel):
    name: str
    provider_code: str
    config: dict[str, Any] = {}
    secrets: dict[str, str] = {}


class ConnectionUpdate(BaseModel):
    name: Optional[str] = None
    config: Optional[dict[str, Any]] = None
    secrets: Optional[dict[str, str]] = None
    status: Optional[str] = None


class ConnectionRead(BaseModel):
    id: UUID
    name: str
    provider_code: str
    capability: list[str]
    config_json: dict
    status: str
    last_tested_at: Optional[datetime]
    last_test_result: Optional[dict]
    health_status: Optional[str]


def _to_read(c: Connection) -> ConnectionRead:
    return ConnectionRead(
        id=c.id, name=c.name, provider_code=c.provider_code, capability=list(c.capability or []),
        config_json=c.config_json or {}, status=c.status, last_tested_at=c.last_tested_at,
        last_test_result=c.last_test_result, health_status=c.health_status,
    )


@connections_router.get("", response_model=list[ConnectionRead])
def list_connections(db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    return [_to_read(c) for c in db.query(Connection).order_by(Connection.name).all()]


@connections_router.post("", response_model=ConnectionRead, status_code=201)
def create_connection(payload: ConnectionCreate, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    import json

    try:
        spec = get_provider(payload.provider_code)
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {payload.provider_code}")

    tenant = require_current_tenant()
    secret_ref = None
    if payload.secrets:
        import uuid as _uuid

        secret_ref = f"connection-{_uuid.uuid4()}"
        store = _tenant_secret_store(db)
        store.put(secret_ref, json.dumps(payload.secrets), created_by=current_user.email)

    connection = Connection(
        tenant_id=tenant.tenant_id, name=payload.name, provider_code=payload.provider_code,
        capability=list(spec.capabilities), config_json=payload.config, secret_ref=secret_ref,
        status="draft", owner_user_id=current_user.id, created_by=current_user.email,
    )
    db.add(connection)
    db.commit()
    db.refresh(connection)
    return _to_read(connection)


@connections_router.patch("/{connection_id}", response_model=ConnectionRead)
def update_connection(connection_id: UUID, payload: ConnectionUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    import json

    connection = db.get(Connection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    if payload.name is not None:
        connection.name = payload.name
    if payload.config is not None:
        connection.config_json = payload.config
    if payload.status is not None:
        connection.status = payload.status
    if payload.secrets is not None:
        store = _tenant_secret_store(db)
        if connection.secret_ref:
            store.rotate(connection.secret_ref, json.dumps(payload.secrets), created_by=current_user.email)
        else:
            connection.secret_ref = f"connection-{connection.id}"
            store.put(connection.secret_ref, json.dumps(payload.secrets), created_by=current_user.email)
    db.commit()
    db.refresh(connection)
    return _to_read(connection)


@connections_router.delete("/{connection_id}", status_code=204)
def delete_connection(connection_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    connection = db.get(Connection, connection_id)
    if connection is not None:
        db.delete(connection)
        db.commit()


class TestResult(BaseModel):
    success: bool
    error: Optional[str] = None


@connections_router.post("/{connection_id}/test", response_model=TestResult)
def test_connection(connection_id: UUID, validate_only: bool = False, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    connection = db.get(Connection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        adapter = _build_adapter(connection, db)
        result = adapter.test_connection()
    except NotYetImplementedProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    from datetime import datetime as _dt, timezone as _tz

    connection.last_tested_at = _dt.now(_tz.utc)
    connection.last_test_result = {"success": result.success, "error": result.error}
    if result.success and not validate_only:
        connection.status = "active"
    elif not result.success:
        connection.status = "error"
    db.commit()
    return TestResult(success=result.success, error=result.error)


@connections_router.get("/{connection_id}/attempts")
def list_attempts(connection_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    rows = (
        db.query(ConnectionAttempt)
        .filter(ConnectionAttempt.connection_id == connection_id)
        .order_by(ConnectionAttempt.created_at.desc())
        .limit(100)
        .all()
    )
    return [
        {"id": str(r.id), "purpose": r.purpose, "operation": r.operation, "status": r.status,
         "latency_ms": r.latency_ms, "error": r.error, "created_at": r.created_at}
        for r in rows
    ]


# ---- connection routes CRUD ----


class ConnectionRouteCreate(BaseModel):
    purpose: str
    connection_id: UUID
    priority: int = 1
    condition_jsonlogic: Optional[dict] = None
    enabled: bool = True


class ConnectionRouteRead(BaseModel):
    id: UUID
    purpose: str
    connection_id: UUID
    priority: int
    condition_jsonlogic: Optional[dict]
    enabled: bool


def _route_read(r: ConnectionRoute) -> ConnectionRouteRead:
    return ConnectionRouteRead(
        id=r.id, purpose=r.purpose, connection_id=r.connection_id, priority=r.priority,
        condition_jsonlogic=r.condition_jsonlogic, enabled=r.enabled,
    )


@routes_router.get("", response_model=list[ConnectionRouteRead])
def list_routes(db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    return [_route_read(r) for r in db.query(ConnectionRoute).order_by(ConnectionRoute.purpose, ConnectionRoute.priority).all()]


@routes_router.post("", response_model=ConnectionRouteRead, status_code=201)
def create_route(payload: ConnectionRouteCreate, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    tenant = require_current_tenant()
    route = ConnectionRoute(tenant_id=tenant.tenant_id, **payload.model_dump())
    db.add(route)
    db.commit()
    db.refresh(route)
    return _route_read(route)


@routes_router.delete("/{route_id}", status_code=204)
def delete_route(route_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    route = db.get(ConnectionRoute, route_id)
    if route is not None:
        db.delete(route)
        db.commit()
