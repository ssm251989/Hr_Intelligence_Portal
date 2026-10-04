"""Part 18.20 (+ fix 2026-10-04): once the candidate confirms a joining date, the agent sends
1. the OFFER LETTER -- the company's offer template (Settings > Offers) filled with the approved
   salary and the chosen date -- for SIGNING: through DocuSign when it is connected and works,
   otherwise with a "Review & sign" link to the in-app signing page (app/offers/esign.py). Never
   "reply to sign".
2. only AFTER the offer is signed (app/offers/esign.on_offer_signed), the WELCOME email + the
   welcome portal case -- unless the company switches on "Send the welcome with the offer"
   (offers.welcome_with_offer, off by default).
The greeting uses the person's preferred / first name when known, otherwise their full name --
never just the first word of a full name (that is often the surname).
"""

import html as _html
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.offer import Offer
from app.models.user import User


def _setting(db, tenant, key):
    from app.platform.settings.resolver import SettingContext, SettingsService

    return SettingsService(db).get(key, SettingContext(tenant=tenant))


def contacts_for(db: Session, tenant, department: Optional[str]) -> list[dict]:
    """Settings > Hiring > Contacts: {"default": [...], "<department>": [...]} -> the department's
    own contacts first, then the company default ones (no duplicates by email)."""
    data = _setting(db, tenant, "recruitment.contacts") or {}
    rows = list(data.get(department or "", []) or []) + list(data.get("default", []) or [])
    seen, out = set(), []
    for r in rows:
        key = (r.get("email") or r.get("name") or "").lower()
        if key and key not in seen:
            seen.add(key)
            out.append({k: r.get(k) for k in ("name", "role", "email", "phone")})
    return out


def _expiry_days(db) -> int:
    from app.experience.ui_offers_router import _expiry_days as offer_expiry_days  # the Offers page's own setting (default 7)

    return offer_expiry_days(db)


def _money(v) -> str:
    n = int(round(float(v)))
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
    return f"{head},{tail}"


def render_offer(db: Session, tenant, application: Application, joining: date) -> str:
    from app.experience.ui_offers_router import DEFAULT_TEMPLATE, OFFER_TEMPLATE_KEY
    from app.models.core_hr import LetterTemplate
    from app.platform.comms.renderer import render_string
    from app.platform.comms.theme import get_theme_and_org_context

    job = db.get(JobRole, application.job_role_id)
    cand = db.get(Candidate, application.candidate_id)
    tpl = (db.query(LetterTemplate).filter(LetterTemplate.tenant_id == tenant.tenant_id, LetterTemplate.key == OFFER_TEMPLATE_KEY)
           .order_by(LetterTemplate.version.desc()).first())
    manager = db.get(User, job.hiring_manager_id) if job and job.hiring_manager_id else None
    salary = application.approved_salary or (application.salary_check or {}).get("suggestion") or application.expected_salary
    days = _expiry_days(db)
    # fix 2026-10-04: never a blank salary amount in the letter
    ctx = {**get_theme_and_org_context(db, tenant), "candidate_name": cand.full_name if cand else "", "job_title": job.title if job else "",
           "salary": _money(salary) if salary is not None else "as agreed with HR", "start_date": joining.strftime("%d %B %Y"),
           "reporting_manager": (manager.full_name or manager.email) if manager else "your manager",
           "expiry_date": (date.today() + timedelta(days=days)).strftime("%d %B %Y")}
    return render_string(tpl.html_tpl if tpl else DEFAULT_TEMPLATE, ctx)


def _text(html_text: str) -> str:
    t = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", html_text)
    return _html.unescape(re.sub(r"<[^>]+>", "", t)).strip()


def _docusign_sender(db, tenant, job) -> Optional[User]:
    from app.models.user_integration import UserIntegration

    ids = [i for i in (job.created_by, job.hiring_manager_id) if i] if job else []
    q = db.query(User).join(UserIntegration, UserIntegration.user_id == User.id).filter(User.tenant_id == tenant.tenant_id, UserIntegration.provider == "docusign")
    return (q.filter(User.id.in_(ids)).first() if ids else None) or q.first()


def greeting_name(db: Session, cand: Optional[Candidate], case=None) -> str:
    """Preferred name, else the first name they gave in the joining details, else the full name."""
    if case is not None:
        jd = ((case.form_submissions_json or {}).get("joining_details") or {}).get("data") or {}
        for key in ("preferred_name", "first_name"):
            if str(jd.get(key) or "").strip():
                return str(jd[key]).strip()
    full = ((cand.full_name if cand else "") or "").replace("Demo - ", "").strip()
    return full or "there"


def contact_people(db: Session, tenant, job: Optional[JobRole]) -> list[dict]:
    """HR / department head / management from Settings > Hiring > Contacts (the job's department first),
    plus the job's hiring manager. Only filled-in details; nobody with neither email nor phone."""
    people = contacts_for(db, tenant, job.department if job else None)
    if job is not None and job.hiring_manager_id:
        mgr = db.get(User, job.hiring_manager_id)
        if mgr is not None and mgr.email and all((p.get("email") or "").lower() != mgr.email.lower() for p in people):
            people.append({"name": mgr.full_name or mgr.email, "role": "Hiring manager", "email": mgr.email, "phone": getattr(mgr, "phone", None)})
    return [p for p in people if p.get("name") and (p.get("email") or p.get("phone"))]


def _contact_lines(people: list[dict]) -> str:
    if not people:
        return ""
    lines = []
    for p in people:
        bits = [p["name"] + (f" ({p['role']})" if p.get("role") else "")]
        bits += [b for b in (p.get("email"), p.get("phone")) if b]
        lines.append("- " + " - ".join(bits))
    return "People you can reach out to:\n" + "\n".join(lines)


def after_joining_date_chosen(db: Session, tenant, application: Application) -> dict:
    from app.offers import esign
    from app.platform.comms.defaults import send_default
    from app.recruitment.joining_dates import info

    if application.status != "bgv_cleared":
        return {"skipped": f"status is {application.status}"}
    chosen = info(application).get("chosen")
    if not chosen:
        return {"skipped": "no date"}
    joining = date.fromisoformat(chosen)
    job = db.get(JobRole, application.job_role_id)
    cand = db.get(Candidate, application.candidate_id)
    letter = render_offer(db, tenant, application, joining)

    offer = db.query(Offer).filter(Offer.application_id == application.id).one_or_none()
    if offer is None:
        offer = Offer(tenant_id=tenant.tenant_id, application_id=application.id)
        db.add(offer)
    offer.offer_letter_text = letter
    offer.joining_date = joining
    offer.expiry_date = date.today() + timedelta(days=_expiry_days(db))
    esign.ensure_token(offer)
    db.flush()
    result: dict = {"offer_id": None, "esign": False, "docusign_error": None, "offer_emailed": False, "sign_link": False,
                    "welcome_emailed": False, "onboarding_case": None, "welcome_with_offer": bool(_setting(db, tenant, "offers.welcome_with_offer"))}

    sender = _docusign_sender(db, tenant, job)
    if sender is not None and cand and cand.email:
        try:
            from app.offers.router import _try_create_docusign_envelope

            envelope = _try_create_docusign_envelope(db, type("O", (), {"offer_letter_text": _text(letter), "application_id": application.id})(), cand, sender)
            if envelope:
                offer.docusign_envelope_id, offer.docusign_sender_id = envelope, sender.id
                result["esign"] = True
        except Exception as exc:  # noqa: BLE001 -- falls back to the in-app "Review & sign" page
            result["docusign_error"] = str(exc)[:200]
    application.status = "offer_sent"
    offer.sent_at = datetime.now(timezone.utc)
    db.commit()
    result["offer_id"] = str(offer.id)

    if cand and cand.email and not result["esign"]:
        try:
            m = send_default(db, tenant, "recruitment.offer_letter_auto", to=[cand.email], related_entity_type="application", related_entity_id=application.id,
                             ctx={"candidate_first_name": greeting_name(db, cand), "job_title": job.title if job else "", "letter": _text(letter),
                                  "sign_link": esign.sign_url(db, offer), "expiry_date": offer.expiry_date.strftime("%d %B %Y")})
            result["offer_emailed"] = m.status in ("sent", "queued")
            result["sign_link"] = True
        except Exception:  # noqa: BLE001
            pass
    if result["welcome_with_offer"]:
        result.update(send_welcome(db, tenant, application, offer))
    log_action(db, "application", application.id, "offer_sent_for_signing", "system", result)
    return result


def send_welcome(db: Session, tenant, application: Application, offer: Offer) -> dict:
    """The welcome email + welcome portal case. Normally right after the offer is signed. Once only."""
    from app.models.audit_log import AuditLog
    from app.platform.comms.defaults import send_default

    out = {"welcome_emailed": False, "onboarding_case": None}
    if db.query(AuditLog).filter(AuditLog.entity_id == application.id, AuditLog.action == "welcome_sent").first() is not None:
        return {**out, "welcome_skipped": "already sent"}
    job = db.get(JobRole, application.job_role_id)
    cand = db.get(Candidate, application.candidate_id)
    if cand is None or not cand.email:
        return out
    joining = offer.joining_date
    portal_link, case = "", None
    try:
        from app.platform.modules import enabled_modules

        if "onboarding" in enabled_modules(db, tenant):
            from app.onboarding.portal import PreboardingPortal
            from app.platform.links import public_app_url

            case = PreboardingPortal(db, tenant).create_case_from_offer(offer.id, joining_date=joining, created_by="system (offer signed)")
            out["onboarding_case"] = str(case.id)
            portal_link = f"{public_app_url(db)}/welcome/{case.portal_token}"
    except Exception:  # noqa: BLE001 -- the welcome still goes out
        db.rollback()
    signed = bool(offer.signed)
    steps = []
    if not signed:
        from app.offers import esign

        steps.append(f"Sign your offer letter: {esign.sign_url(db, offer)}")
    if portal_link:
        steps.append(f"Open your welcome portal and fill in your joining details: {portal_link}")
    else:
        steps.append("Keep your documents handy for day one")
    if joining:
        steps.append(f"Join us on {joining.strftime('%A, %d %B %Y')}")
    try:
        m = send_default(db, tenant, "recruitment.welcome_selected", to=[cand.email], related_entity_type="application", related_entity_id=application.id,
                         ctx={"candidate_first_name": greeting_name(db, cand, case), "job_title": job.title if job else "",
                              "joining_date": joining.strftime("%A, %d %B %Y") if joining else "",
                              "steps": "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)),
                              "contacts": _contact_lines(contact_people(db, tenant, job)), "portal_link": portal_link})
        out["welcome_emailed"] = m.status in ("sent", "queued")
    except Exception:  # noqa: BLE001
        pass
    if out["welcome_emailed"]:
        log_action(db, "application", application.id, "welcome_sent", "system", {"case": out["onboarding_case"], "after_signing": signed})
    return out
