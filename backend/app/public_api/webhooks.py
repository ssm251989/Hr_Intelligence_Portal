"""Part 30.2d: webhooks -- a company's own system hears what happened, signed so it can trust it.

Every minute (job "public_webhooks") the audit log since the saved cursor is mapped to events (the same audit
rows the agent timeline reads), plus the approval cards made / decided; each active subscription that asked for
the event gets a delivery. Deliveries go out through the generic_webhook provider: HMAC-SHA256 of the body in
X-Signature, plus X-Event and X-Delivery-Id. A failed delivery is retried after 1, 5, 30 min, 2 h and 12 h, then
marked failed ("Resend" on the Developers page tries again).

Payloads carry ids, status and a link -- never resume text, and salary figures only for a subscription with the
"sensitive" scope.
"""

import ipaddress
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models.public_api import WebhookDelivery, WebhookSubscription

log = logging.getLogger(__name__)

# event -> (audit entity_type, audit actions)
AUDIT_EVENTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "application.created": ("application", ("application_created",)),
    "application.screened": ("application", ("ai_screening_scored",)),
    "interview.scheduled": ("interview", ("interview_scheduled",)),
    "interview.decided": ("interview", ("interview_feedback_recorded",)),
    "salary.decided": ("application", ("salary_approval_decision", "salary_auto_decided")),
    "bgv.decided": ("application", ("bgv_passed", "bgv_discrepancy", "bgv_clearance_decision")),
    "offer.sent": ("application", ("offer_sent_for_signing",)),
    "offer.signed": ("application", ("offer_signed",)),
    "employee.joined": ("application", ("onboarding_completed",)),
    "separation.approved": ("separation", ("separation_lwd_approved",)),
    "job.published": ("job_role", ("job_platforms_published",)),
}
CARD_EVENTS = ("card.created", "card.decided")
EVENTS = tuple(AUDIT_EVENTS) + CARD_EVENTS
RETRY = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=30), timedelta(hours=2), timedelta(hours=12))
CURSOR = "webhooks.cursor"
LAG = timedelta(seconds=20)
BATCH = 500
SEND_BATCH = 100
SENSITIVE_KEYS = ("approved_salary", "expected_salary", "current_salary", "offered_ctc", "approved_ctc")


# ---------------------------------------------------------------- subscriptions


def check_url(url: str, tenant) -> str:
    """https only; a sandbox company may also use a loopback http receiver (the local proof). Private addresses are
    refused for live companies (a webhook must not reach into the server's own network)."""
    from app.public_api.keys import is_sandbox

    u = urlparse((url or "").strip())
    host = (u.hostname or "").lower()
    loopback = host in ("localhost",) or _is_ip(host, lambda ip: ip.is_loopback)
    if u.scheme == "http" and loopback and is_sandbox(tenant):
        return u.geturl()
    if u.scheme != "https" or not host:
        raise ValueError("The webhook URL must start with https:// (a sandbox company may also use http://localhost).")
    if not is_sandbox(tenant) and (loopback or _is_ip(host, lambda ip: ip.is_private or ip.is_link_local or ip.is_reserved)):
        raise ValueError("The webhook URL must be a public address.")
    return u.geturl()


def _is_ip(host: str, test) -> bool:
    try:
        return bool(test(ipaddress.ip_address(host)))
    except ValueError:
        return False


def create_subscription(db: Session, tenant, user, *, url: str, events: list[str], scopes: list[str]) -> tuple[WebhookSubscription, str]:
    from app.core.crypto import encrypt

    bad = [e for e in events if e not in EVENTS]
    if bad or not events:
        raise ValueError(f"Choose at least one event from: {', '.join(EVENTS)}." + (f" Unknown: {', '.join(bad)}." if bad else ""))
    if any(s != "sensitive" for s in scopes):
        raise ValueError("The only webhook scope is 'sensitive' (salary figures in the payload).")
    secret = "whsec_" + secrets.token_urlsafe(32)
    row = WebhookSubscription(tenant_id=tenant.tenant_id, url=check_url(url, tenant), events=sorted(set(events)), scopes=sorted(set(scopes)),
                              secret_enc=encrypt(secret), created_by=getattr(user, "id", None))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, secret


def subscription_dict(row: WebhookSubscription) -> dict:
    return {"id": str(row.id), "url": row.url, "events": row.events or [], "scopes": row.scopes or [], "active": row.active,
            "created_at": row.created_at.isoformat() if row.created_at else None}


def delivery_dict(row: WebhookDelivery) -> dict:
    return {"id": str(row.id), "subscription_id": str(row.subscription_id), "event": row.event, "status": row.status, "attempts": row.attempts,
            "last_status": row.last_status, "last_error": row.last_error, "next_at": row.next_at.isoformat() if row.next_at else None,
            "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None, "created_at": row.created_at.isoformat() if row.created_at else None,
            "payload": row.payload}


# ---------------------------------------------------------------- events -> deliveries


def _base(db: Session) -> str:
    try:
        from app.platform.links import public_base_url

        return public_base_url(db).rstrip("/")
    except Exception:  # noqa: BLE001
        return ""


def _application_data(db: Session, app_id, sensitive: bool) -> dict:
    from app.models.application import Application

    app = db.get(Application, app_id) if app_id else None
    if app is None:
        return {"application_id": str(app_id) if app_id else None}
    out = {"application_id": str(app.id), "job_id": str(app.job_role_id), "candidate_id": str(app.candidate_id), "status": app.status,
           "link": f"{_base(db)}/candidates/{app.id}"}
    if sensitive:
        out["salary"] = {k: float(v) for k in SENSITIVE_KEYS if (v := getattr(app, k, None)) is not None}
    return out


def _data(db: Session, event: str, row, sensitive: bool) -> Optional[dict]:
    """The payload's data for one audit row (None = this row is not that event after all)."""
    details = row.details or {}
    if event == "job.published":
        if details.get("new_status") != "published":
            return None  # saved for the job boards only
        return {"job_id": str(row.entity_id), "status": "published", "platforms": details.get("published_platforms") or {},
                "link": f"{_base(db)}/jobs"}
    if event == "salary.decided" and row.action == "salary_auto_decided" and details.get("new_status") != "salary_approved":
        return None  # the check only routed it to HR; HR's decision comes as salary_approval_decision
    if event == "separation.approved":
        out = {"separation_id": str(row.entity_id), "status": "approved", "approved_lwd": details.get("approved_lwd"), "link": f"{_base(db)}/exits"}
        return out
    if row.entity_type == "interview":
        from app.models.interview import Interview

        iv = db.get(Interview, row.entity_id)
        if event == "interview.decided" and not details.get("decision"):
            return None  # feedback saved without a decision
        out = _application_data(db, getattr(iv, "application_id", None) or details.get("application_id"), sensitive)
        out["interview_id"] = str(row.entity_id)
        if details.get("decision"):
            out["decision"] = details["decision"]
        return out
    out = _application_data(db, row.entity_id, sensitive)
    for k in ("decision", "new_status"):
        if details.get(k) and k not in out:
            out[k] = details[k]
    return out


def _subs(db: Session, tenant) -> list[WebhookSubscription]:
    return db.query(WebhookSubscription).filter(WebhookSubscription.tenant_id == tenant.tenant_id, WebhookSubscription.active.is_(True)).all()


def _queue(db: Session, tenant, sub: WebhookSubscription, event: str, data: dict, at: datetime) -> WebhookDelivery:
    d = WebhookDelivery(tenant_id=tenant.tenant_id, subscription_id=sub.id, event=event, payload={}, next_at=datetime.now(timezone.utc))
    db.add(d)
    db.flush()
    d.payload = {"id": str(d.id), "event": event, "occurred_at": at.isoformat(), "data": data}
    return d


def collect(db: Session, tenant, now: Optional[datetime] = None) -> int:
    """Audit rows + cards since the cursor -> deliveries. Never replays history (first run starts now)."""
    from app.hr_agents.autopilot.core import state_get, state_set
    from app.models.audit_log import AuditLog
    from app.models.intelligence import AgentSuggestion

    now = now or datetime.now(timezone.utc)
    upto = now - LAG
    saved = state_get(db, tenant, CURSOR)
    subs = _subs(db, tenant)
    if not saved or not subs:
        state_set(db, tenant, CURSOR, {"at": upto.isoformat()})
        return 0
    since = datetime.fromisoformat(saved["at"])
    by_action = {(etype, a): ev for ev, (etype, actions) in AUDIT_EVENTS.items() for a in actions}
    wanted = {ev for s in subs for ev in (s.events or [])}
    actions = [a for (etype, a), ev in by_action.items() if ev in wanted]
    rows = (db.query(AuditLog).filter(AuditLog.tenant_id == tenant.tenant_id, AuditLog.action.in_(actions), AuditLog.created_at > since,
                                      AuditLog.created_at <= upto).order_by(AuditLog.created_at).limit(BATCH).all()) if actions else []
    made = 0
    for row in rows:
        event = by_action.get((row.entity_type, row.action))
        if event is None:
            continue
        for sub in subs:
            if event not in (sub.events or []):
                continue
            data = _data(db, event, row, "sensitive" in (sub.scopes or []))
            if data is not None:
                _queue(db, tenant, sub, event, data, row.created_at)
                made += 1
    if wanted & set(CARD_EVENTS):
        cards = db.query(AgentSuggestion).filter(AgentSuggestion.tenant_id == tenant.tenant_id,
                                                 ((AgentSuggestion.created_at > since) & (AgentSuggestion.created_at <= upto))
                                                 | ((AgentSuggestion.reviewed_at > since) & (AgentSuggestion.reviewed_at <= upto))).limit(BATCH).all()
        for c in cards:
            for event, at in (("card.created", c.created_at), ("card.decided", c.reviewed_at)):
                if at is None or not (since < at <= upto) or (event == "card.decided" and c.status not in ("approved", "edited", "rejected", "closed")):
                    continue
                data = {"card_id": str(c.id), "kind": c.kind, "title": (c.title or "").split(" (Autopilot:")[0], "status": c.status,
                        "entity_type": c.entity_type, "entity_id": str(c.entity_id) if c.entity_id else None, "link": f"{_base(db)}/approvals"}
                if event == "card.decided":
                    data["decided_by"] = c.reviewed_by
                for sub in subs:
                    if event in (sub.events or []):
                        _queue(db, tenant, sub, event, data, at)
                        made += 1
    last = rows[-1].created_at if len(rows) == BATCH else upto
    db.commit()
    state_set(db, tenant, CURSOR, {"at": last.isoformat()})
    return made


# ---------------------------------------------------------------- sending


def _adapter():
    from app.platform.connectors.providers.generic_webhook import GenericWebhookAdapter

    return GenericWebhookAdapter({"timeout_seconds": 10}, {})


def attempt(db: Session, delivery: WebhookDelivery, sub: WebhookSubscription, now: Optional[datetime] = None) -> WebhookDelivery:
    from app.core.crypto import decrypt

    now = now or datetime.now(timezone.utc)
    result = _adapter().send(sub.url, delivery.payload, decrypt(sub.secret_enc),
                             headers={"X-Event": delivery.event, "X-Delivery-Id": str(delivery.id)})
    delivery.attempts = (delivery.attempts or 0) + 1
    delivery.last_status = (result.raw or {}).get("status_code") if result.raw else None
    if result.success:
        delivery.status, delivery.delivered_at, delivery.last_error, delivery.next_at = "delivered", now, None, None
    else:
        delivery.last_error = (result.error or "no answer")[:500]
        if delivery.attempts > len(RETRY):
            delivery.status, delivery.next_at = "failed", None
        else:
            delivery.status, delivery.next_at = "pending", now + RETRY[delivery.attempts - 1]
    db.commit()
    return delivery


def send_due(db: Session, tenant, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    rows = (db.query(WebhookDelivery).filter(WebhookDelivery.tenant_id == tenant.tenant_id, WebhookDelivery.status == "pending",
                                             WebhookDelivery.next_at <= now).order_by(WebhookDelivery.next_at).limit(SEND_BATCH).all())
    out = {"delivered": 0, "retrying": 0, "failed": 0}
    for d in rows:
        sub = db.get(WebhookSubscription, d.subscription_id)
        if sub is None or not sub.active:
            d.status, d.next_at, d.last_error = "failed", None, "the subscription was switched off"
            db.commit()
            out["failed"] += 1
            continue
        try:
            attempt(db, d, sub, now)
        except Exception as exc:  # noqa: BLE001 -- one bad delivery never blocks the others
            log.exception("webhook delivery %s failed", d.id)
            db.rollback()
            continue
        out[{"delivered": "delivered", "failed": "failed"}.get(d.status, "retrying")] += 1
    return out


def resend(db: Session, delivery: WebhookDelivery) -> WebhookDelivery:
    """The Developers page's Resend: try again now (a new round of retries)."""
    delivery.status, delivery.attempts, delivery.next_at, delivery.last_error = "pending", 0, datetime.now(timezone.utc), None
    db.commit()
    return delivery


def ping(db: Session, tenant, sub: WebhookSubscription) -> WebhookDelivery:
    d = _queue(db, tenant, sub, "ping", {"message": "Test ping from HR Automation"}, datetime.now(timezone.utc))
    db.commit()
    return attempt(db, d, sub)


def run(db: Session, tenant) -> dict:
    """The per-minute job: collect new events, send what is due."""
    return {"queued": collect(db, tenant), **send_due(db, tenant)}
