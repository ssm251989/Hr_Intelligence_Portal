"""Part 22.6c: Settings > Communication > Email design and Settings > Onboarding & employees > Letters.

- GET  /api/v1/ui/design/emails                        the designed emails, banner gallery (+ the company's own uploads)
- POST /api/v1/ui/design/emails/{key}/preview          {overrides} -> {subject, html, text} with sample data (no raw {{ }})
- POST /api/v1/ui/design/emails/{key}/test             send that email (sample data) to me
- POST /api/v1/ui/design/letters/{kind}/preview        {overrides} -> the letter PDF with sample data
- POST /api/v1/ui/design/letters/{kind}/test           email the sample letter PDF to me
Preview overrides are unsaved values (emails.* / letters.* / org.address / org.cin), so the preview follows the form live.
"""

import re
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.core.database import get_db
from app.models.user import User
from app.platform.iam.authz import require
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/ui/design", tags=["ui-design"])
PERM = "platform.settings.configure"

EMAILS = {
    "recruitment.offer_letter_auto": "Selection / offer email",
    "recruitment.welcome_selected": "Welcome / joining email",
    "employee.exit_letters": "Relieving / experience email",
}
LETTER_KINDS = ("offer", "joining", "appointment", "confirmation", "relieving", "experience")


def _company(db: Session, tenant) -> str:
    from app.platform.settings.resolver import SettingContext, SettingsService

    return SettingsService(db).get("org.display_name", SettingContext(tenant=tenant)) or "Your company"


def sample_ctx(db: Session, tenant, key: str) -> dict:
    from app.platform.links import public_app_url

    base = {"company_name": _company(db, tenant)}
    app_url = public_app_url(db)
    if key == "recruitment.welcome_selected":
        return {**base, "candidate_first_name": "Priya", "job_title": "Junior AI Developer", "joining_date": "Monday, 03 November 2026",
                "steps": f"1. Open your welcome portal and fill in your joining details: {app_url}/welcome/sample\n2. Join us on Monday, 03 November 2026",
                "contacts": "People you can reach out to:\n- Anita Rao (HR) - hr@example.com", "portal_link": f"{app_url}/welcome/sample",
                "people": [{"name": "Anita Rao", "role": "HR", "email": "hr@example.com"}, {"name": "Kishore G", "role": "Your manager", "email": "manager@example.com"}],
                "day_one": {"start_time": "09:30 AM", "address": "Your office address (Settings > Day one / Locations)", "map_url": None,
                            "meet": "Anita Rao at reception", "what_to_bring": ["Photo ID", "PAN card", "Bank details"]},
                "buddy": {"name": "Rahul Menon", "role": "AI Developer", "email": "buddy@example.com"}}
    if key == "employee.exit_letters":
        return {**base, "first_name": "Arun", "last_working_day": "30 Sep 2026"}
    return {**base, "candidate_first_name": "Priya", "job_title": "Junior AI Developer", "letter": "Dear Priya Sharma,\n\nWe are delighted to offer you ...",
            "sign_link": f"{app_url}/offer/sign/sample", "expiry_date": "14 October 2026", "joining_date": "Monday, 03 November 2026"}


def _fill_leftovers(text: Optional[str]) -> str:
    """A company template may use a variable the sample doesn't know -- show a readable placeholder, never raw {{ }}."""
    return re.sub(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}", lambda m: f"[{m.group(1).replace('_', ' ')}]", text or "")


def _render(db: Session, tenant, key: str, overrides: Optional[dict]) -> dict:
    from app.platform.comms import celebrate
    from app.platform.comms.defaults import DEFAULTS, _html, ensure_template
    from app.platform.comms.templates import render_template

    ctx = sample_ctx(db, tenant, key)
    ensure_template(db, tenant, key)
    from app.models.comms import MessageTemplate

    t = (db.query(MessageTemplate).filter(MessageTemplate.tenant_id == tenant.tenant_id, MessageTemplate.key == key, MessageTemplate.status == "published")
         .order_by(MessageTemplate.version.desc()).first())
    subject, text, _req = DEFAULTS[key]
    subject_tpl, text_tpl = (t.subject_tpl, t.text_tpl) if t is not None else (subject, text)
    rendered = render_template(subject_tpl=subject_tpl, html_tpl=_html(text_tpl or ""), text_tpl=text_tpl, variables_schema={"required": []}, context=ctx)
    rendered = {k: _fill_leftovers(v) if isinstance(v, str) else v for k, v in rendered.items()}
    out = celebrate.apply(db, tenant, key, ctx, rendered, overrides=overrides)
    return {"subject": out["subject"], "html": out["html"], "text": out.get("text") or ""}


class PreviewIn(BaseModel):
    overrides: dict = Field(default_factory=dict)


@router.get("/emails")
def list_emails(db: Session = Depends(get_db), current_user: User = Depends(require(PERM))):
    from app.models.experience import TenantMedia
    from app.platform.comms.celebrate import BANNERS

    tenant = require_current_tenant()
    own = [m.media_key.split(".", 2)[2] for m in db.query(TenantMedia).filter(TenantMedia.tenant_id == tenant.tenant_id,
                                                                               TenantMedia.media_key.like("email.banner.%")).all()]
    return {"emails": [{"key": k, "name": v} for k, v in EMAILS.items()],
            "banners": [{"key": k, "name": v, "url": f"/api/v1/public/email-banners/{k}.gif", "still": f"/api/v1/public/email-banners/{k}.png"} for k, v in BANNERS.items()]
            + [{"key": f"custom:{n}", "name": n, "url": f"/api/v1/public/media/email.banner.{n}", "still": f"/api/v1/public/media/email.banner.{n}"} for n in own]}


@router.post("/emails/{key}/preview")
def preview_email(key: str, body: PreviewIn, db: Session = Depends(get_db), current_user: User = Depends(require(PERM))):
    if key not in EMAILS:
        raise HTTPException(status_code=404, detail="Not a designed email")
    return _render(db, require_current_tenant(), key, body.overrides)


@router.post("/emails/{key}/test")
def test_email(key: str, db: Session = Depends(get_db), current_user: User = Depends(require(PERM))):
    from app.platform.comms.service import send

    if key not in EMAILS:
        raise HTTPException(status_code=404, detail="Not a designed email")
    tenant = require_current_tenant()
    m = send(db, tenant, template_key=key, to=[current_user.email], ctx=sample_ctx(db, tenant, key), purpose="email.outbound.hr_letters")
    log_action(db, "message_template", None, "design_test_sent", current_user.email[:50], {"key": key, "status": m.status})
    return {"status": m.status, "to": current_user.email, "error": m.error}


SAMPLE_LETTERS = {
    "offer": "Dear Priya Sharma,\n\nWe are delighted to offer you the position of Junior AI Developer at {company}.\n\nYour terms:\n\nDesignation: Junior AI Developer\n"
             "Annual CTC: Rs. 4,00,000\nJoining date: 3 November 2026\n\nPlease sign this letter by 14 October 2026 to accept.\n\nWarm regards,",
    "joining": "Dear Priya Sharma,\n\nWelcome to {company}! We are happy to confirm that you have joined us as Junior AI Developer on 3 November 2026.\n\nBest wishes,",
    "appointment": "Dear Priya Sharma,\n\nYou are appointed as Junior AI Developer with effect from 3 November 2026 on the terms of your offer.\n\nYours sincerely,",
    "confirmation": "Dear Priya Sharma,\n\nWe are pleased to confirm your employment as Junior AI Developer with effect from 3 May 2027.\n\nYours sincerely,",
    "relieving": "Dear Arun Kumar,\n\nThis is to confirm that you have been relieved from your duties at {company} at the close of business on 30 September 2026.\n\n"
                 "We thank you for your contributions and wish you success.\n\nYours sincerely,",
    "experience": "TO WHOMSOEVER IT MAY CONCERN\n\nThis is to certify that Arun Kumar worked with {company} as Senior Software Engineer from 1 June 2023 to "
                  "30 September 2026.\n\nWe wish him every success.\n\nYours sincerely,",
}


def _letter_pdf(db: Session, tenant, kind: str, overrides: Optional[dict]) -> bytes:
    from app.platform.letters import design

    if kind not in LETTER_KINDS:
        raise HTTPException(status_code=404, detail="Unknown letter")
    brand = design.brand_for(db, tenant)
    o = overrides or {}
    if o.get("letters.signatory_name") is not None:
        brand.signatory_name = o["letters.signatory_name"]
    if o.get("letters.signatory_designation") is not None:
        brand.signatory_designation = o["letters.signatory_designation"]
    if o.get("org.address") is not None:
        brand.address = o["org.address"]
    if o.get("org.cin") is not None:
        brand.cin = o["org.cin"]
    if o.get("letters.watermark") is not None:
        brand.watermark = bool(o["letters.watermark"])
    if o.get("letters.celebration") is not None:
        brand.celebration = bool(o["letters.celebration"])
    if o.get("letters.brand_colour"):
        brand.colour = design._hex(o["letters.brand_colour"])
    today = date.today()
    token = "SAMPLE"
    return design.render(brand, design.Letter(kind=kind, body=SAMPLE_LETTERS[kind].replace("{company}", brand.company or "our company"),
                                              reference=design.reference(brand, kind, "SAMPLE", today), issued_on=today, verify_token=token,
                                              verify_link=design.verify_url(db, token)))


@router.post("/letters/{kind}/preview")
def preview_letter(kind: str, body: PreviewIn, db: Session = Depends(get_db), current_user: User = Depends(require(PERM))):
    return Response(_letter_pdf(db, require_current_tenant(), kind, body.overrides), media_type="application/pdf")


@router.post("/letters/{kind}/test")
def test_letter(kind: str, db: Session = Depends(get_db), current_user: User = Depends(require(PERM))):
    from app.platform.comms.defaults import ensure_template
    from app.platform.comms.service import send

    tenant = require_current_tenant()
    data = _letter_pdf(db, tenant, kind, None)
    ensure_template(db, tenant, "letters.test_copy")
    m = send(db, tenant, template_key="letters.test_copy", to=[current_user.email], purpose="email.outbound.hr_letters",
             ctx={"company_name": _company(db, tenant), "letter": kind.title()},
             attachments=[{"content": data, "maintype": "application", "subtype": "pdf", "filename": f"sample-{kind}-letter.pdf"}])
    log_action(db, "letter", None, "design_test_sent", current_user.email[:50], {"kind": kind, "status": m.status})
    return {"status": m.status, "to": current_user.email, "error": m.error}
