"""Part 30.2f: Settings > Developers -- API keys (the key shown once), usage per day, webhooks (the signing secret
shown once), test ping, delivery log with Resend. Admin only: platform.api_keys.manage."""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.core.database import get_db
from app.models.public_api import SCOPES, ApiKey, ApiUsage, WebhookDelivery, WebhookSubscription
from app.models.user import User
from app.platform.iam.authz import require
from app.platform.tenancy.context import require_current_tenant
from app.public_api import keys as key_service
from app.public_api import webhooks as hooks

router = APIRouter(prefix="/api/v1/ui/developers", tags=["ui-developers"])
manager = require(key_service.PERMISSION)


def _own(db: Session, model, row_id: UUID):
    row = db.get(model, row_id)
    if row is None or row.tenant_id != require_current_tenant().tenant_id:
        raise HTTPException(status_code=404, detail="Not found")
    return row


@router.get("/overview")
def overview(db: Session = Depends(get_db), user: User = Depends(manager)):
    tenant = require_current_tenant()
    return {"mode": key_service.mode_for(tenant), "sandbox": key_service.is_sandbox(tenant), "scopes": list(SCOPES), "events": list(hooks.EVENTS),
            "base_url": "/api/public/v1", "docs_url": "/api/public/v1/docs"}


# ---------------------------------------------------------------- keys


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str]
    expires_at: Optional[datetime] = None


@router.get("/keys")
def list_keys(db: Session = Depends(get_db), user: User = Depends(manager)):
    tenant = require_current_tenant()
    rows = db.query(ApiKey).filter(ApiKey.tenant_id == tenant.tenant_id).order_by(ApiKey.created_at.desc()).all()
    return {"items": [key_service.to_dict(r) for r in rows]}


@router.post("/keys", status_code=201)
def create_key(body: KeyIn, db: Session = Depends(get_db), user: User = Depends(manager)):
    tenant = require_current_tenant()
    try:
        row, full = key_service.create_key(db, tenant, user, name=body.name, scopes=body.scopes, expires_at=body.expires_at)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_action(db, "api_key", row.id, "api_key_created", user.email[:50], {"name": row.name, "prefix": row.prefix, "scopes": row.scopes, "mode": row.mode})
    return {**key_service.to_dict(row), "key": full, "note": "Copy this key now - it is not shown again."}


@router.post("/keys/{key_id}/revoke")
def revoke_key(key_id: UUID, db: Session = Depends(get_db), user: User = Depends(manager)):
    row = key_service.revoke(db, _own(db, ApiKey, key_id))
    log_action(db, "api_key", row.id, "api_key_revoked", user.email[:50], {"prefix": row.prefix})
    return key_service.to_dict(row)


@router.get("/usage")
def usage(days: int = 30, db: Session = Depends(get_db), user: User = Depends(manager)):
    """Calls per day (and errors) for the chart, last `days` days, per key."""
    tenant = require_current_tenant()
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 90)))
    day = func.date_trunc("day", ApiUsage.created_at)
    rows = (db.query(day.label("day"), ApiUsage.api_key_id, func.count(ApiUsage.id), func.count(ApiUsage.id).filter(ApiUsage.status_code >= 400))
            .filter(ApiUsage.tenant_id == tenant.tenant_id, ApiUsage.created_at >= since).group_by(day, ApiUsage.api_key_id).order_by(day).all())
    return {"items": [{"day": d.date().isoformat(), "key_id": str(k) if k else None, "calls": n, "errors": e} for d, k, n, e in rows]}


# ---------------------------------------------------------------- webhooks


class HookIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    events: list[str]
    scopes: list[str] = []


class HookPatch(BaseModel):
    active: Optional[bool] = None
    events: Optional[list[str]] = None


@router.get("/webhooks")
def list_hooks(db: Session = Depends(get_db), user: User = Depends(manager)):
    tenant = require_current_tenant()
    rows = db.query(WebhookSubscription).filter(WebhookSubscription.tenant_id == tenant.tenant_id).order_by(WebhookSubscription.created_at.desc()).all()
    return {"items": [hooks.subscription_dict(r) for r in rows]}


@router.post("/webhooks", status_code=201)
def create_hook(body: HookIn, db: Session = Depends(get_db), user: User = Depends(manager)):
    tenant = require_current_tenant()
    try:
        row, secret = hooks.create_subscription(db, tenant, user, url=body.url, events=body.events, scopes=body.scopes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_action(db, "webhook_subscription", row.id, "webhook_created", user.email[:50], {"url": row.url, "events": row.events, "scopes": row.scopes})
    return {**hooks.subscription_dict(row), "secret": secret, "note": "Copy this signing secret now - it is not shown again."}


@router.patch("/webhooks/{hook_id}")
def update_hook(hook_id: UUID, body: HookPatch, db: Session = Depends(get_db), user: User = Depends(manager)):
    row = _own(db, WebhookSubscription, hook_id)
    if body.events is not None:
        bad = [e for e in body.events if e not in hooks.EVENTS]
        if bad or not body.events:
            raise HTTPException(status_code=400, detail=f"Unknown events: {', '.join(bad)}" if bad else "Choose at least one event.")
        row.events = sorted(set(body.events))
    if body.active is not None:
        row.active = body.active
    db.commit()
    log_action(db, "webhook_subscription", row.id, "webhook_updated", user.email[:50], body.model_dump(exclude_none=True))
    return hooks.subscription_dict(row)


@router.post("/webhooks/{hook_id}/ping")
def ping(hook_id: UUID, db: Session = Depends(get_db), user: User = Depends(manager)):
    return hooks.delivery_dict(hooks.ping(db, require_current_tenant(), _own(db, WebhookSubscription, hook_id)))


@router.get("/webhooks/{hook_id}/deliveries")
def deliveries(hook_id: UUID, limit: int = 50, db: Session = Depends(get_db), user: User = Depends(manager)):
    _own(db, WebhookSubscription, hook_id)
    rows = (db.query(WebhookDelivery).filter(WebhookDelivery.subscription_id == hook_id).order_by(WebhookDelivery.created_at.desc())
            .limit(max(1, min(limit, 200))).all())
    return {"items": [hooks.delivery_dict(r) for r in rows]}


@router.post("/deliveries/{delivery_id}/resend")
def resend(delivery_id: UUID, db: Session = Depends(get_db), user: User = Depends(manager)):
    d = hooks.resend(db, _own(db, WebhookDelivery, delivery_id))
    sub = db.get(WebhookSubscription, d.subscription_id)
    if sub is not None and sub.active:
        d = hooks.attempt(db, d, sub)
    return hooks.delivery_dict(d)
