"""Communication Engine API (docs/HRMS_COMPLETE_SPEC.txt Part 4 section 6) -- scoped down
the same way Part 2's Settings API / Part 3's Connections API were (see those routers' own
docstrings, and docs/build_log.md's Part 4 entry for the exact scope decision here): CRUD +
publish/preview for templates, CRUD for rules, a single default brand_theme (not the full
multi-theme/multi-entity model), a read-only + resend message log, and a token-based
candidate/employee preferences page -- not the spec's full split-view template editor,
diff/versions UI, or per-message delivery timeline. Gated by require_roles("admin") --
interim stand-in for platform.comms.manage until Part 5's IAM/RBAC exists (same interim
pattern connectors/api_router.py and settings/router.py already use).
"""

from datetime import datetime, timezone
from html import escape
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import require_roles
from app.core.config import settings
from app.core.database import get_db
from app.models.comms import BrandTheme, NotificationPreference, NotificationRule, OutboundMessage, SuppressionListEntry
from app.models.user import User
from app.platform.comms.renderer import TemplateRenderError, VariablesValidationError
from app.platform.comms.suppression import is_opted_in
from app.platform.comms.templates import create_draft, publish, preview as preview_template
from app.platform.connectors.registry import NotYetImplementedProviderError, get_provider
from app.platform.connectors.router import ConnectorRouter, NoConnectionForPurposeError
from app.platform.tenancy.context import TenantContext, require_current_tenant, tenant_context

router = APIRouter(prefix="/api/v1/comms", tags=["comms"])
public_router = APIRouter(prefix="/api/v1/public/comms", tags=["comms-public"])

_PREFERENCES_TOKEN_PURPOSE = "comms.preferences"


# ---- templates ----


class TemplateCreate(BaseModel):
    key: str
    channel: str = "email"
    locale: str = "en"
    subject_tpl: Optional[str] = None
    html_tpl: Optional[str] = None
    text_tpl: Optional[str] = None
    variables_schema: dict = {}


class TemplateRead(BaseModel):
    id: UUID
    key: str
    channel: str
    locale: str
    version: int
    status: str
    subject_tpl: Optional[str]
    html_tpl: Optional[str]
    text_tpl: Optional[str]
    variables_schema_json: dict
    published_by: Optional[str]
    published_at: Optional[datetime]


def _template_read(t) -> TemplateRead:
    return TemplateRead(
        id=t.id, key=t.key, channel=t.channel, locale=t.locale, version=t.version, status=t.status,
        subject_tpl=t.subject_tpl, html_tpl=t.html_tpl, text_tpl=t.text_tpl,
        variables_schema_json=t.variables_schema_json or {}, published_by=t.published_by, published_at=t.published_at,
    )


@router.get("/templates", response_model=list[TemplateRead])
def list_templates(db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    """Latest version of every distinct key/channel/locale -- not every historical
    version (see /templates/{key}/versions for those)."""
    from sqlalchemy import func

    from app.models.comms import MessageTemplate

    tenant = require_current_tenant()
    latest_versions = (
        db.query(MessageTemplate.key, MessageTemplate.channel, MessageTemplate.locale, func.max(MessageTemplate.version).label("v"))
        .filter(MessageTemplate.tenant_id == tenant.tenant_id)
        .group_by(MessageTemplate.key, MessageTemplate.channel, MessageTemplate.locale)
        .subquery()
    )
    rows = (
        db.query(MessageTemplate)
        .join(
            latest_versions,
            (MessageTemplate.key == latest_versions.c.key)
            & (MessageTemplate.channel == latest_versions.c.channel)
            & (MessageTemplate.locale == latest_versions.c.locale)
            & (MessageTemplate.version == latest_versions.c.v),
        )
        .filter(MessageTemplate.tenant_id == tenant.tenant_id)
        .order_by(MessageTemplate.key)
        .all()
    )
    return [_template_read(t) for t in rows]


@router.get("/templates/{key}/versions", response_model=list[TemplateRead])
def list_template_versions(key: str, channel: str = "email", locale: str = "en", db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    from app.models.comms import MessageTemplate

    tenant = require_current_tenant()
    rows = (
        db.query(MessageTemplate)
        .filter(MessageTemplate.tenant_id == tenant.tenant_id, MessageTemplate.key == key, MessageTemplate.channel == channel, MessageTemplate.locale == locale)
        .order_by(MessageTemplate.version.desc())
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Template not found")
    return [_template_read(t) for t in rows]


@router.post("/templates", response_model=TemplateRead, status_code=201)
def create_template_draft(payload: TemplateCreate, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    tenant = require_current_tenant()
    template = create_draft(
        db, tenant.tenant_id, key=payload.key, channel=payload.channel, locale=payload.locale,
        subject_tpl=payload.subject_tpl, html_tpl=payload.html_tpl, text_tpl=payload.text_tpl,
        variables_schema=payload.variables_schema,
    )
    return _template_read(template)


@router.post("/templates/{template_id}/publish", response_model=TemplateRead)
def publish_template(template_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    from app.models.comms import MessageTemplate

    template = db.get(MessageTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    try:
        template = publish(db, template, actor=current_user.email)
    except (VariablesValidationError, TemplateRenderError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _template_read(template)


class PreviewRequest(BaseModel):
    sample_context: dict[str, Any] = {}


class PreviewResponse(BaseModel):
    subject: str
    html: str
    text: str


@router.post("/templates/{template_id}/preview", response_model=PreviewResponse)
def preview_template_route(template_id: UUID, payload: PreviewRequest, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    """Sample data merged with the same {{ theme.* }}/{{ org.* }} context a real send
    renders with (section 6: "live preview"), so the preview matches what actually goes
    out, not just the caller-supplied variables."""
    from app.models.comms import MessageTemplate
    from app.platform.comms.theme import get_theme_and_org_context

    template = db.get(MessageTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    tenant = require_current_tenant()
    sample = {key: f"[{key}]" for key in (template.variables_schema_json or {}).get("required", [])}
    ctx = {**sample, **get_theme_and_org_context(db, tenant), **payload.sample_context}
    try:
        rendered = preview_template(template, ctx)
    except (VariablesValidationError, TemplateRenderError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return PreviewResponse(**rendered)


# ---- rules ----


class RuleCreate(BaseModel):
    name: str
    event_type: str
    condition_jsonlogic: Optional[dict] = None
    recipients_json: dict
    channels: list[str] = ["email"]
    template_key: str
    delay_spec: Optional[dict] = None
    quiet_hours_respect: bool = True
    digest_mode: str = "none"
    priority: int = 1
    enabled: bool = True


class RuleUpdate(BaseModel):
    name: Optional[str] = None
    condition_jsonlogic: Optional[dict] = None
    recipients_json: Optional[dict] = None
    channels: Optional[list[str]] = None
    template_key: Optional[str] = None
    delay_spec: Optional[dict] = None
    quiet_hours_respect: Optional[bool] = None
    digest_mode: Optional[str] = None
    priority: Optional[int] = None
    enabled: Optional[bool] = None


class RuleRead(BaseModel):
    id: UUID
    name: str
    event_type: str
    condition_jsonlogic: Optional[dict]
    recipients_json: dict
    channels: list[str]
    template_key: str
    delay_spec: Optional[dict]
    quiet_hours_respect: bool
    digest_mode: str
    priority: int
    enabled: bool


def _rule_read(r: NotificationRule) -> RuleRead:
    return RuleRead(
        id=r.id, name=r.name, event_type=r.event_type, condition_jsonlogic=r.condition_jsonlogic,
        recipients_json=r.recipients_json, channels=list(r.channels or []), template_key=r.template_key,
        delay_spec=r.delay_spec, quiet_hours_respect=r.quiet_hours_respect, digest_mode=r.digest_mode,
        priority=r.priority, enabled=r.enabled,
    )


@router.get("/rules", response_model=list[RuleRead])
def list_rules(db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    tenant = require_current_tenant()
    rows = db.query(NotificationRule).filter(NotificationRule.tenant_id == tenant.tenant_id).order_by(NotificationRule.event_type, NotificationRule.priority).all()
    return [_rule_read(r) for r in rows]


@router.post("/rules", response_model=RuleRead, status_code=201)
def create_rule(payload: RuleCreate, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    tenant = require_current_tenant()
    rule = NotificationRule(tenant_id=tenant.tenant_id, **payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _rule_read(rule)


@router.patch("/rules/{rule_id}", response_model=RuleRead)
def update_rule(rule_id: UUID, payload: RuleUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    rule = db.get(NotificationRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return _rule_read(rule)


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    rule = db.get(NotificationRule, rule_id)
    if rule is not None:
        db.delete(rule)
        db.commit()


# ---- brand theme (single default theme per tenant -- not the spec's full multi-theme/
# multi-legal-entity model, same "one row is enough for this installation" scoping as
# hrctl.migrate_comms_templates' own _TENANT_1_THEME) ----


class BrandThemeUpsert(BaseModel):
    name: str = "Default"
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    gradient_from: Optional[str] = None
    gradient_to: Optional[str] = None
    font_family: Optional[str] = None
    email_footer_html: Optional[str] = None
    legal_disclaimer: Optional[str] = None


class BrandThemeRead(BaseModel):
    id: UUID
    name: str
    primary_color: Optional[str]
    secondary_color: Optional[str]
    gradient_from: Optional[str]
    gradient_to: Optional[str]
    font_family: Optional[str]
    email_footer_html: Optional[str]
    legal_disclaimer: Optional[str]


def _theme_read(t: BrandTheme) -> BrandThemeRead:
    return BrandThemeRead(
        id=t.id, name=t.name, primary_color=t.primary_color, secondary_color=t.secondary_color,
        gradient_from=t.gradient_from, gradient_to=t.gradient_to, font_family=t.font_family,
        email_footer_html=t.email_footer_html, legal_disclaimer=t.legal_disclaimer,
    )


def _get_default_theme(db: Session, tenant: TenantContext) -> Optional[BrandTheme]:
    return db.query(BrandTheme).filter(BrandTheme.tenant_id == tenant.tenant_id, BrandTheme.is_default.is_(True)).first()


@router.get("/brand-theme", response_model=Optional[BrandThemeRead])
def get_brand_theme(db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    theme = _get_default_theme(db, require_current_tenant())
    return _theme_read(theme) if theme else None


@router.put("/brand-theme", response_model=BrandThemeRead)
def upsert_brand_theme(payload: BrandThemeUpsert, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    tenant = require_current_tenant()
    theme = _get_default_theme(db, tenant)
    if theme is None:
        theme = BrandTheme(tenant_id=tenant.tenant_id, is_default=True, **payload.model_dump())
        db.add(theme)
    else:
        for field, value in payload.model_dump().items():
            setattr(theme, field, value)
    db.commit()
    db.refresh(theme)
    return _theme_read(theme)


# ---- message log ----


class OutboundRead(BaseModel):
    id: UUID
    channel: str
    purpose: Optional[str]
    to_addresses: list[str]
    subject: Optional[str]
    status: str
    attempts: int
    error: Optional[str]
    sent_at: Optional[datetime]
    created_at: Optional[datetime]


def _outbound_read(m: OutboundMessage) -> OutboundRead:
    return OutboundRead(
        id=m.id, channel=m.channel, purpose=m.purpose, to_addresses=list(m.to_addresses or []),
        subject=m.subject, status=m.status, attempts=m.attempts, error=m.error, sent_at=m.sent_at, created_at=m.created_at,
    )


@router.get("/outbound", response_model=list[OutboundRead])
def list_outbound(
    status: Optional[str] = None, channel: Optional[str] = None, limit: int = 25, offset: int = 0,
    db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin")),
):
    tenant = require_current_tenant()
    query = db.query(OutboundMessage).filter(OutboundMessage.tenant_id == tenant.tenant_id)
    if status:
        query = query.filter(OutboundMessage.status == status)
    if channel:
        query = query.filter(OutboundMessage.channel == channel)
    rows = query.order_by(OutboundMessage.created_at.desc()).offset(offset).limit(min(limit, 100)).all()
    return [_outbound_read(m) for m in rows]


@router.post("/outbound/{message_id}/resend", response_model=OutboundRead)
def resend_outbound(message_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    """Re-sends the exact content that was already rendered (subject/body_ref) through the
    same purpose's connector -- not a re-render from live data, since outbound_messages
    doesn't retain the original event context (see this module's own OutboundMessage
    docstring: body_ref IS the rendered body). A genuinely re-rendered resend would need
    the triggering event replayed, which is outside this scoped-down message log."""
    message = db.get(OutboundMessage, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    if not message.to_addresses:
        raise HTTPException(status_code=400, detail="No recipients to resend to")
    if not message.purpose:
        raise HTTPException(status_code=400, detail="This message has no purpose to route a resend through")

    try:
        resolved = ConnectorRouter(db).resolve(message.purpose, {})
        spec = get_provider(resolved.connection.provider_code)
        if spec.adapter_cls is None:
            raise NotYetImplementedProviderError(f"{resolved.connection.provider_code} has no adapter implementation yet")
        secrets: dict = {}
        if resolved.connection.secret_ref:
            import json

            from app.models.secret import Secret, SecretScope
            from app.platform.secrets.store import get_secret_store

            store = get_secret_store(db, Secret, SecretScope, str(require_current_tenant().tenant_id))
            secrets = json.loads(store.get(resolved.connection.secret_ref))
        adapter = spec.adapter_cls(resolved.connection.config_json or {}, secrets)

        from app.platform.connectors.capabilities import OutboundEmail

        result = adapter.send(OutboundEmail(
            to=list(message.to_addresses), cc=list(message.cc_addresses or []) or None,
            bcc=list(message.bcc_addresses or []) or None, subject=message.subject or "",
            body_text=message.body_ref or "", body_html=None,
        ))
    except (NoConnectionForPurposeError, NotYetImplementedProviderError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    message.attempts += 1
    if result.success:
        message.status = "sent"
        message.provider_message_id = result.provider_message_id
        message.sent_at = datetime.now(timezone.utc)
        message.error = None
    else:
        message.status = "failed"
        message.error = result.error
    db.commit()
    db.refresh(message)
    return _outbound_read(message)


# ---- suppression list (read + manual un-suppress -- adding a suppression manually isn't
# exposed here since real suppressions come from a bounce/complaint/unsubscribe, not an
# admin typing an address in) ----


class SuppressionRead(BaseModel):
    address: str
    reason: str
    created_at: Optional[datetime]


@router.get("/suppression", response_model=list[SuppressionRead])
def list_suppression(db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    tenant = require_current_tenant()
    rows = db.query(SuppressionListEntry).filter(SuppressionListEntry.tenant_id == tenant.tenant_id).order_by(SuppressionListEntry.created_at.desc()).all()
    return [SuppressionRead(address=r.address, reason=r.reason, created_at=r.created_at) for r in rows]


@router.delete("/suppression/{address}", status_code=204)
def remove_suppression(address: str, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))):
    tenant = require_current_tenant()
    db.query(SuppressionListEntry).filter(SuppressionListEntry.tenant_id == tenant.tenant_id, SuppressionListEntry.address == address.lower()).delete()
    db.commit()


# ---- candidate/employee preferences page (public, no-auth -- same "exact link from an
# email" pattern as confirm_router.py/negotiation_router.py) -- gated by a signed,
# non-expiring JWT (reusing app.core.security's own SECRET_KEY/ALGORITHM) carrying WHO
# (candidate_id or user_id) and WHICH tenant, so the link can't be forged or reused for a
# different person, but never expires the way a login token does (an unsubscribe link
# emailed months ago must keep working). ----

# The event_groups a recipient can toggle here -- the ones real notification_rules in this
# installation actually target (hrctl.migrate_comms_templates' own template keys), not
# every theoretically possible one.
PREFERENCE_EVENT_GROUPS = (
    "recruitment.negotiation.interviewer_offer",
    "recruitment.negotiation.candidate_offer",
    "recruitment.interview.confirmation",
)


def make_preferences_token(*, tenant_id: UUID, candidate_id: Optional[UUID] = None, user_id: Optional[UUID] = None) -> str:
    payload = {"purpose": _PREFERENCES_TOKEN_PURPOSE, "tenant_id": str(tenant_id)}
    if candidate_id is not None:
        payload["candidate_id"] = str(candidate_id)
    if user_id is not None:
        payload["user_id"] = str(user_id)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _decode_preferences_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=400, detail="Invalid or corrupted preferences link")
    if payload.get("purpose") != _PREFERENCES_TOKEN_PURPOSE:
        raise HTTPException(status_code=400, detail="Invalid or corrupted preferences link")
    return payload


class PreferenceEntry(BaseModel):
    event_group: str
    channel: str
    opted_in: bool


class PreferencesResponse(BaseModel):
    org_display_name: str
    preferences: list[PreferenceEntry]


def _identity_from_token(payload: dict) -> tuple[Optional[UUID], Optional[UUID]]:
    candidate_id = UUID(payload["candidate_id"]) if payload.get("candidate_id") else None
    user_id = UUID(payload["user_id"]) if payload.get("user_id") else None
    return candidate_id, user_id


def _load_preference_entries(db: Session, tenant, candidate_id: Optional[UUID], user_id: Optional[UUID]) -> list[PreferenceEntry]:
    return [
        PreferenceEntry(
            event_group=group, channel="email",
            opted_in=is_opted_in(db, tenant, user_id=user_id, candidate_id=candidate_id, channel="email", event_group=group),
        )
        for group in PREFERENCE_EVENT_GROUPS
    ]


@public_router.get("/preferences", response_model=PreferencesResponse)
def get_preferences(token: str, db: Session = Depends(get_db)):
    payload = _decode_preferences_token(token)
    with tenant_context(UUID(payload["tenant_id"])):
        tenant = require_current_tenant()
        candidate_id, user_id = _identity_from_token(payload)
        from app.platform.comms.theme import get_theme_and_org_context

        org_display_name = get_theme_and_org_context(db, tenant)["org"]["display_name"]
        entries = _load_preference_entries(db, tenant, candidate_id, user_id)
    return PreferencesResponse(org_display_name=org_display_name, preferences=entries)


class PreferenceUpdate(BaseModel):
    token: str
    event_group: str
    channel: str = "email"
    opted_in: bool


@public_router.post("/preferences", response_model=PreferenceEntry)
def set_preference(payload: PreferenceUpdate, db: Session = Depends(get_db)):
    decoded = _decode_preferences_token(payload.token)
    if payload.event_group not in PREFERENCE_EVENT_GROUPS:
        raise HTTPException(status_code=400, detail="Unknown preference")
    with tenant_context(UUID(decoded["tenant_id"])):
        tenant = require_current_tenant()
        candidate_id = UUID(decoded["candidate_id"]) if decoded.get("candidate_id") else None
        user_id = UUID(decoded["user_id"]) if decoded.get("user_id") else None

        existing = (
            db.query(NotificationPreference)
            .filter(
                NotificationPreference.tenant_id == tenant.tenant_id, NotificationPreference.channel == payload.channel,
                NotificationPreference.event_group == payload.event_group,
                NotificationPreference.user_id == user_id, NotificationPreference.candidate_id == candidate_id,
            )
            .first()
        )
        if existing is None:
            existing = NotificationPreference(
                tenant_id=tenant.tenant_id, user_id=user_id, candidate_id=candidate_id,
                channel=payload.channel, event_group=payload.event_group, opted_in=payload.opted_in,
            )
            db.add(existing)
        else:
            existing.opted_in = payload.opted_in
        db.commit()
    return PreferenceEntry(event_group=payload.event_group, channel=payload.channel, opted_in=payload.opted_in)


# ---- preferences page (self-contained HTML, no JS/build step needed -- same "last stop
# from an email link" pattern as confirm_router.py/negotiation_router.py, plain <form>
# POST rather than the JSON endpoints above driving a client-side fetch) ----

_PAGE_CSS_TEMPLATE = """
  * { box-sizing: border-box; }
  body { font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif; background: #eef1f6;
         margin: 0; padding: 0; color: #1a1f36; }
  .shell { max-width: 480px; margin: 64px auto; background: #ffffff; border-radius: 12px;
           box-shadow: 0 4px 24px rgba(20,30,60,0.08); overflow: hidden; }
  .topbar { padding: 18px 32px; background: linear-gradient(120deg, {{GRADIENT_FROM}}, {{GRADIENT_TO}}); color: #ffffff;
            font-weight: 700; letter-spacing: 0.04em; font-size: 15px; }
  .body { padding: 32px; }
  h1 { font-size: 20px; font-weight: 800; margin: 0 0 8px; color: {{GRADIENT_FROM}}; }
  p.copy { font-size: 14px; line-height: 1.5; color: #3a4257; margin: 0 0 20px; }
  .pref-row { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-top: 1px solid #eef0f5; }
  .pref-row label { font-size: 14px; color: #1a1f36; cursor: pointer; }
  .btn { margin-top: 20px; border-radius: 10px; padding: 11px 20px; font-size: 14px; font-weight: 700;
         cursor: pointer; border: none; background: {{PRIMARY}}; color: #ffffff; }
  .saved { font-size: 13px; color: #1b8a5a; margin-top: 12px; }
"""


def _preferences_page_css(theme: dict) -> str:
    return (
        _PAGE_CSS_TEMPLATE.replace("{{PRIMARY}}", theme["primary_color"])
        .replace("{{GRADIENT_FROM}}", theme["gradient_from"])
        .replace("{{GRADIENT_TO}}", theme["gradient_to"])
    )


def _render_preferences_page(*, org_display_name: str, theme: dict, entries: list[PreferenceEntry], token: str, saved: bool) -> str:
    brand_name = escape(org_display_name.upper())
    rows = "\n".join(
        f'<div class="pref-row"><input type="checkbox" id="pref-{i}" name="event_group" value="{escape(e.event_group)}" {"checked" if e.opted_in else ""} />'
        f'<label for="pref-{i}">{escape(e.event_group)}</label></div>'
        for i, e in enumerate(entries)
    )
    saved_banner = '<p class="saved">Preferences saved.</p>' if saved else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Email Preferences</title>
  <style>{_preferences_page_css(theme)}</style>
</head>
<body>
  <div class="shell">
    <div class="topbar">{brand_name}</div>
    <div class="body">
      <h1>Email Preferences</h1>
      <p class="copy">Choose which emails you'd like to keep receiving. Unchecked items are
      turned off immediately.</p>
      <form method="post">
        <input type="hidden" name="token" value="{escape(token)}" />
        {rows}
        <button type="submit" class="btn">Save preferences</button>
      </form>
      {saved_banner}
    </div>
  </div>
</body>
</html>
"""


@public_router.get("/preferences/page", response_class=HTMLResponse)
def preferences_page(token: str, db: Session = Depends(get_db)):
    payload = _decode_preferences_token(token)
    with tenant_context(UUID(payload["tenant_id"])):
        tenant = require_current_tenant()
        candidate_id, user_id = _identity_from_token(payload)
        from app.platform.comms.theme import get_theme_and_org_context

        ctx = get_theme_and_org_context(db, tenant)
        entries = _load_preference_entries(db, tenant, candidate_id, user_id)
    return HTMLResponse(_render_preferences_page(org_display_name=ctx["org"]["display_name"], theme=ctx["theme"], entries=entries, token=token, saved=False))


@public_router.post("/preferences/page", response_class=HTMLResponse)
async def submit_preferences_page(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    token = str(form.get("token", ""))
    payload = _decode_preferences_token(token)
    checked_groups = set(form.getlist("event_group"))

    with tenant_context(UUID(payload["tenant_id"])):
        tenant = require_current_tenant()
        candidate_id, user_id = _identity_from_token(payload)

        for group in PREFERENCE_EVENT_GROUPS:
            opted_in = group in checked_groups
            existing = (
                db.query(NotificationPreference)
                .filter(
                    NotificationPreference.tenant_id == tenant.tenant_id, NotificationPreference.channel == "email",
                    NotificationPreference.event_group == group,
                    NotificationPreference.user_id == user_id, NotificationPreference.candidate_id == candidate_id,
                )
                .first()
            )
            if existing is None:
                db.add(NotificationPreference(
                    tenant_id=tenant.tenant_id, user_id=user_id, candidate_id=candidate_id,
                    channel="email", event_group=group, opted_in=opted_in,
                ))
            else:
                existing.opted_in = opted_in
        db.commit()

        from app.platform.comms.theme import get_theme_and_org_context

        ctx = get_theme_and_org_context(db, tenant)
        entries = _load_preference_entries(db, tenant, candidate_id, user_id)
    return HTMLResponse(_render_preferences_page(org_display_name=ctx["org"]["display_name"], theme=ctx["theme"], entries=entries, token=token, saved=True))
