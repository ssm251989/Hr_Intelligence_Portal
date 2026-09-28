"""Part 18: ready-to-use wording for every automatic candidate email.

The first time a message is needed and the company has no template with that key yet, a
PUBLISHED template is created from the wording below; from then on it is an ordinary
template the company edits in Settings > Communication > Templates (their edits win -- this
never overwrites an existing template). Placeholders use the same {{ name }} syntax as
every other template; the company logo/colours wrapper is added at send time (17.11).
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

# key -> (subject, plain-text body, required variables)
DEFAULTS: dict[str, tuple[str, str, list[str]]] = {
    "recruitment.salary_details_request": (
        "{{ job_title }}: your salary and joining details",
        "Hi {{ candidate_first_name }},\n\nThank you for your time in the interview for {{ job_title }}. To move to the next step, "
        "please share your salary and joining details (it takes about 2 minutes):\n\n{{ form_link }}\n\n"
        "Your answers are only seen by the hiring team.\n\nBest regards,\n{{ company_name }} HR",
        ["candidate_first_name", "job_title", "form_link"],
    ),
    "recruitment.salary_counter_offer": (
        "{{ job_title }}: our salary offer",
        "Hi {{ candidate_first_name }},\n\nThank you for sharing your salary details for {{ job_title }}. After reviewing them, we would "
        "like to offer {{ amount }} per year.\n\n{{ note }}\n\nPlease reply to this email to let us know if this works for you, or if "
        "you would like to talk it through.\n\nBest regards,\n{{ company_name }} HR",
        ["candidate_first_name", "job_title", "amount"],
    ),
    "recruitment.job_closed_candidate": (
        "Update on your application for {{ job_title }}",
        "Hi {{ candidate_first_name }},\n\nThank you for applying for {{ job_title }}. This position has been closed for now, so "
        "your application is on hold. If the role opens again, we will pick up your application from where it was - "
        "you don't need to apply again.\n\nThank you for your interest in {{ company_name }}.\n\nBest regards,\n{{ company_name }} HR",
        ["candidate_first_name", "job_title"],
    ),
}


def _html(text: str) -> str:
    paras = [p.replace("\n", "<br>") for p in text.split("\n\n")]
    return "".join(f"<p>{p}</p>" for p in paras)


def ensure_template(db: Session, tenant, key: str, *, locale: str = "en") -> bool:
    """Creates the default published template for `key` if the company has none. True if it exists afterwards."""
    from app.models.comms import MessageTemplate

    if db.query(MessageTemplate.id).filter(MessageTemplate.tenant_id == tenant.tenant_id, MessageTemplate.key == key).first():
        return True
    if key not in DEFAULTS:
        return False
    subject, body, required = DEFAULTS[key]
    db.add(MessageTemplate(tenant_id=tenant.tenant_id, key=key, channel="email", locale=locale, version=1, status="published",
                           subject_tpl=subject, text_tpl=body, html_tpl=_html(body), variables_schema_json={"required": required},
                           published_by="system (default wording)", published_at=datetime.now(timezone.utc)))
    db.commit()
    return True


def send_default(db: Session, tenant, key: str, *, to: list[str], ctx: dict, purpose: str = "email.outbound.recruitment",
                 related_entity_type: Optional[str] = None, related_entity_id: Optional[UUID] = None):
    """ensure_template + comms.send, with the company name filled in. Returns the OutboundMessage."""
    from app.platform.comms.service import send
    from app.platform.settings.resolver import SettingContext, SettingsService

    ensure_template(db, tenant, key)
    company = SettingsService(db).get("org.display_name", SettingContext(tenant=tenant)) or ""
    return send(db, tenant, template_key=key, to=to, ctx={"company_name": company, **ctx}, purpose=purpose,
                related_entity_type=related_entity_type, related_entity_id=related_entity_id)
