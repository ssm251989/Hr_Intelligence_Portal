"""Part 18.20: once the candidate confirms a joining date, the agent sends
1. the OFFER LETTER -- the company's offer template (Settings > Offers) filled with the approved
   salary and the chosen date; sent for e-signature through DocuSign when someone in the company
   has connected it, otherwise emailed as a letter to reply to;
2. a happy WELCOME email -- "Congratulations on your selection", the onboarding steps and the
   contacts to reach (Settings > Hiring > Contacts: HR, the department head, management -- per
   department, with a company default);
and moves the candidate to Onboarding (the pre-joining portal case, when that module is on).
"""

import html as _html
import re
from datetime import date, timedelta
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
    ctx = {**get_theme_and_org_context(db, tenant), "candidate_name": cand.full_name if cand else "", "job_title": job.title if job else "",
           "salary": _money(salary) if salary is not None else "", "start_date": joining.strftime("%d %B %Y"),
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


def after_joining_date_chosen(db: Session, tenant, application: Application) -> dict:
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
    first = (cand.full_name or "").replace("Demo - ", "").split(" ")[0] if cand else ""
    letter = render_offer(db, tenant, application, joining)

    offer = db.query(Offer).filter(Offer.application_id == application.id).one_or_none()
    if offer is None:
        offer = Offer(tenant_id=tenant.tenant_id, application_id=application.id)
        db.add(offer)
    offer.offer_letter_text = letter
    offer.joining_date = joining
    offer.expiry_date = date.today() + timedelta(days=_expiry_days(db))
    db.flush()
    result: dict = {"offer_id": None, "esign": False, "offer_emailed": False, "welcome_emailed": False, "onboarding_case": None}

    sender = _docusign_sender(db, tenant, job)
    if sender is not None and cand and cand.email:
        try:
            from app.offers.router import _try_create_docusign_envelope

            envelope = _try_create_docusign_envelope(db, type("O", (), {"offer_letter_text": _text(letter), "application_id": application.id})(), cand, sender)
            if envelope:
                offer.docusign_envelope_id, offer.docusign_sender_id = envelope, sender.id
                result["esign"] = True
        except Exception:  # noqa: BLE001 -- falls back to the emailed letter
            pass
    application.status = "offer_sent"
    db.commit()
    result["offer_id"] = str(offer.id)

    if cand and cand.email:
        if not result["esign"]:
            try:
                m = send_default(db, tenant, "recruitment.offer_letter_auto", to=[cand.email], related_entity_type="application", related_entity_id=application.id,
                                 ctx={"candidate_first_name": first, "job_title": job.title if job else "", "letter": _text(letter),
                                      "expiry_date": offer.expiry_date.strftime("%d %B %Y")})
                result["offer_emailed"] = m.status in ("sent", "queued")
            except Exception:  # noqa: BLE001
                pass
        # onboarding case (pre-joining portal) when that module is on
        portal_link = ""
        try:
            from app.platform.modules import enabled_modules

            if "onboarding" in enabled_modules(db, tenant):
                from app.core.config import settings as app_settings
                from app.onboarding.portal import PreboardingPortal

                case = PreboardingPortal(db, tenant).create_case_from_offer(offer.id, joining_date=joining, created_by="system (offer sent)")
                result["onboarding_case"] = str(case.id)
                portal_link = f"{app_settings.FRONTEND_URL.rstrip('/')}/welcome/{case.portal_token}"
        except Exception:  # noqa: BLE001 -- the welcome still goes out
            db.rollback()
        people = contacts_for(db, tenant, job.department if job else None)
        contact_lines = "\n".join(f"- {p['name']}{(' (' + p['role'] + ')') if p.get('role') else ''}: {p.get('email') or ''}{('  ' + p['phone']) if p.get('phone') else ''}"
                                  for p in people) or "- Your HR team: reply to this email"
        steps = ("1. Sign your offer letter" + (" (you will get a DocuSign email)" if result["esign"] else " (reply to the offer email)") + "\n"
                 + ("2. Fill in your joining details in the welcome portal: " + portal_link + "\n" if portal_link else "2. Keep your documents handy for day one\n")
                 + f"3. Join us on {joining.strftime('%A, %d %B %Y')}")
        try:
            m = send_default(db, tenant, "recruitment.welcome_selected", to=[cand.email], related_entity_type="application", related_entity_id=application.id,
                             ctx={"candidate_first_name": first, "job_title": job.title if job else "", "joining_date": joining.strftime("%A, %d %B %Y"),
                                  "steps": steps, "contacts": contact_lines, "portal_link": portal_link})
            result["welcome_emailed"] = m.status in ("sent", "queued")
        except Exception:  # noqa: BLE001
            pass
    log_action(db, "application", application.id, "offer_and_welcome_sent", "system", result)
    return result
