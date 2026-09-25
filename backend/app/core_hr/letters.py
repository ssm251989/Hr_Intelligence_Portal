"""Documents & letters (docs/HRMS_COMPLETE_SPEC.txt Part 7 section 4) -- letter templates
render through Part 4's own Jinja sandbox (`platform.comms.renderer`), the same safe,
XSS-resistant template engine every email already uses, not a second one invented here.

**PDF/DOCX generation is a documented gap, not attempted**: every letter is generated as
rendered HTML (real, tested, verifiable) -- converting that to a real PDF/DOCX binary
needs a document-generation service this installation doesn't have, the identical gap
Part 5's own `engine.py` already documented for its `generate_document` workflow action.
e-sign is Part 3's own `esign.*` connection purpose -- already real, not rebuilt here.

**Digital verification is a token + URL, not a QR image**: `verification_token` is a real,
unique, unguessable value a `letter_records` row can be looked up by (`verify_letter()`);
no `qrcode` library was added to render it as an actual QR code image -- the same "skip a
new dependency for a rendering nicety" decision Part 5 made for TOTP enrollment's own QR
code (a manual-entry secret works identically in every authenticator app).
"""

import secrets
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.core_hr import LETTER_TEMPLATE_KEYS, LetterRecord, LetterTemplate
from app.platform.tenancy.context import TenantContext


class LetterTemplateNotFoundError(Exception):
    pass


class LetterNotFoundError(Exception):
    pass


def get_published_template(db: Session, tenant: TenantContext, key: str) -> LetterTemplate:
    template = (
        db.query(LetterTemplate)
        .filter(LetterTemplate.tenant_id == tenant.tenant_id, LetterTemplate.key == key, LetterTemplate.status == "published")
        .order_by(LetterTemplate.version.desc())
        .first()
    )
    if template is None:
        raise LetterTemplateNotFoundError(f"No published letter_template for key: {key}")
    return template


def create_draft(db: Session, tenant: TenantContext, *, key: str, name: str, html_tpl: str, variables_schema: Optional[dict] = None) -> LetterTemplate:
    latest = (
        db.query(LetterTemplate)
        .filter(LetterTemplate.tenant_id == tenant.tenant_id, LetterTemplate.key == key)
        .order_by(LetterTemplate.version.desc())
        .first()
    )
    template = LetterTemplate(
        tenant_id=tenant.tenant_id, key=key, name=name, version=(latest.version + 1) if latest else 1,
        status="draft", html_tpl=html_tpl, variables_schema_json=variables_schema or {},
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def publish(db: Session, template: LetterTemplate) -> LetterTemplate:
    from app.platform.comms.renderer import render_string

    render_string(template.html_tpl, {key: f"[{key}]" for key in (template.variables_schema_json or {}).get("required", [])})
    template.status = "published"
    db.commit()
    db.refresh(template)
    return template


def generate_letter(db: Session, tenant: TenantContext, *, employee_id: UUID, template_key: str, context: dict, generated_by: Optional[str] = None) -> LetterRecord:
    from app.platform.comms.renderer import render_string
    from app.platform.comms.theme import get_theme_and_org_context

    template = get_published_template(db, tenant, template_key)
    full_context = {**context, **get_theme_and_org_context(db, tenant)}
    rendered_html = render_string(template.html_tpl, full_context)

    record = LetterRecord(
        tenant_id=tenant.tenant_id, employee_id=employee_id, template_key=template_key, template_version=template.version,
        rendered_html=rendered_html, verification_token=secrets.token_urlsafe(24), generated_by=generated_by,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def verify_letter(db: Session, tenant: TenantContext, verification_token: str) -> LetterRecord:
    record = db.query(LetterRecord).filter(LetterRecord.tenant_id == tenant.tenant_id, LetterRecord.verification_token == verification_token).first()
    if record is None:
        raise LetterNotFoundError("No letter found for this verification token")
    return record


def letter_history(db: Session, tenant: TenantContext, employee_id: UUID) -> list[LetterRecord]:
    return (
        db.query(LetterRecord)
        .filter(LetterRecord.tenant_id == tenant.tenant_id, LetterRecord.employee_id == employee_id)
        .order_by(LetterRecord.generated_at.desc())
        .all()
    )
