"""Template CRUD + publish/preview helpers (docs/HRMS_COMPLETE_SPEC.txt Part 4 section 6)."""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.comms import MessageTemplate
from app.platform.comms.renderer import render_template
from app.platform.comms.theme import GENERIC_FALLBACK_ORG_DISPLAY_NAME, GENERIC_FALLBACK_THEME


class TemplateNotFoundError(Exception):
    pass


def get_published_template(db: Session, tenant_id: UUID, key: str, *, channel: str = "email", locale: str = "en") -> MessageTemplate:
    template = (
        db.query(MessageTemplate)
        .filter(
            MessageTemplate.tenant_id == tenant_id, MessageTemplate.key == key,
            MessageTemplate.channel == channel, MessageTemplate.locale == locale,
            MessageTemplate.status == "published",
        )
        .order_by(MessageTemplate.version.desc())
        .first()
    )
    if template is None:
        raise TemplateNotFoundError(f"No published {channel}/{locale} template for key: {key}")
    return template


def create_draft(
    db: Session, tenant_id: UUID, *, key: str, channel: str, locale: str = "en",
    subject_tpl: Optional[str] = None, html_tpl: Optional[str] = None, text_tpl: Optional[str] = None,
    variables_schema: Optional[dict] = None,
) -> MessageTemplate:
    latest = (
        db.query(MessageTemplate)
        .filter(MessageTemplate.tenant_id == tenant_id, MessageTemplate.key == key, MessageTemplate.channel == channel, MessageTemplate.locale == locale)
        .order_by(MessageTemplate.version.desc())
        .first()
    )
    next_version = (latest.version + 1) if latest else 1
    template = MessageTemplate(
        tenant_id=tenant_id, key=key, channel=channel, locale=locale, version=next_version,
        status="draft", subject_tpl=subject_tpl, html_tpl=html_tpl, text_tpl=text_tpl,
        variables_schema_json=variables_schema or {},
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


_SAMPLE_THEME_ORG_CONTEXT = {
    # Every real send/preview merges in platform.comms.theme.get_theme_and_org_context's
    # {{ theme.* }}/{{ org.* }} -- a template that references either (section 5 explicitly
    # expects `{{ org.display_name }}` in every seeded template) must validate against
    # them too, not just its own variables_schema_json's domain variables, or a perfectly
    # valid template would fail to publish here yet render fine for a real send.
    "theme": GENERIC_FALLBACK_THEME,
    "org": {"display_name": GENERIC_FALLBACK_ORG_DISPLAY_NAME},
}


def publish(db: Session, template: MessageTemplate, *, actor: str) -> MessageTemplate:
    """Validates the template renders with a sample of its own required variables filled
    with placeholder values (section 2: "variables validated ... at publish time") before
    flipping status -- catches a syntax error before it can ever reach a real send."""
    sample_ctx = {
        **_SAMPLE_THEME_ORG_CONTEXT,
        **{key: f"[{key}]" for key in (template.variables_schema_json or {}).get("required", [])},
    }
    render_template(
        subject_tpl=template.subject_tpl, html_tpl=template.html_tpl, text_tpl=template.text_tpl,
        variables_schema=template.variables_schema_json, context=sample_ctx,
    )
    template.status = "published"
    template.published_by = actor
    template.published_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(template)
    return template


def preview(template: MessageTemplate, sample_context: dict) -> dict:
    return render_template(
        subject_tpl=template.subject_tpl, html_tpl=template.html_tpl, text_tpl=template.text_tpl,
        variables_schema=template.variables_schema_json, context=sample_context,
    )
