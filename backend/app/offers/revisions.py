"""Fix 2026-10-05: resend an offer for signature, and send a REVISED offer (v2, v3, ...).

The `offers` row is always the LATEST version (every existing reader keeps working); each version also has an
`offer_versions` row: who sent it, why, what changed. A revision:
1. re-checks the CTC against the job's band (+ approval margin) and the department budget -- above the limit it
   waits as "Needs approval" until an approver (admin / salary approver) approves it;
2. freezes the current version ("Replaced"): its sign link, view / signature, PDF and DocuSign envelope
   (voided). The old link then says "This offer was replaced by a newer version" with a button to the latest;
3. puts the new values on `offers` with a NEW sign link, unsigned -- a signed v1 still needs a new signature;
4. emails "Revised offer from <company>" with a short "What changed" list and the sign link.
When the revised version is signed, the joining date is applied everywhere (onboarding case, portal, emails) --
see esign.on_offer_signed.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.offer import Offer, OfferVersion
from app.models.user import User

log = logging.getLogger(__name__)

RESEND_COOLDOWN = timedelta(minutes=15)
REASONS = {"salary": "Salary changed", "joining_date": "Joining date changed", "designation": "Designation changed", "other": "Other"}
# status shown to HR: Sent / Viewed / Signed / Replaced / Declined (+ Needs approval / Not approved / Withdrawn)
FIELD_LABELS = {"ctc_total": "CTC", "joining_date": "Joining date", "designation": "Designation", "work_location": "Location", "terms": "Terms"}


class CooldownError(ValueError):
    def __init__(self, wait_minutes: int):
        super().__init__(f"It was sent less than 15 minutes ago. You can resend in {wait_minutes} min.")
        self.wait_minutes = wait_minutes


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _num(v) -> Optional[float]:
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def lpa(v) -> str:
    """600000 -> "6.0 LPA" (as HR says it)."""
    n = _num(v)
    return f"{n / 100000:.1f} LPA" if n is not None else "-"


def _date_text(d) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return d.strftime("%d %b %Y") if d else "-"


# ---------------------------------------------------------------- the current values

def ctc_of(offer: Offer, application: Optional[Application]) -> Optional[float]:
    b = offer.ctc_breakup_json or {}
    if _num(b.get("base_ctc")) is not None:
        return _num(b["base_ctc"])
    if application is None:
        return None
    return _num(application.approved_salary) or _num((application.salary_check or {}).get("suggestion")) or _num(application.expected_salary)


def current_values(db: Session, offer: Offer) -> dict:
    application = db.get(Application, offer.application_id)
    job = db.get(JobRole, application.job_role_id) if application else None
    breakup = offer.ctc_breakup_json or {}
    return {
        "ctc_total": ctc_of(offer, application),
        "components": [{"code": c.get("code"), "name": c.get("name"), "amount": _num(c.get("amount"))} for c in (breakup.get("components") or [])],
        "joining_date": offer.joining_date.isoformat() if offer.joining_date else None,
        "designation": offer.designation or (job.title if job else ""),
        "work_location": offer.work_location or (job.location if job else "") or "",
        "terms": offer.terms or "",
        "expiry_date": offer.expiry_date.isoformat() if offer.expiry_date else None,
    }


def _rows(db: Session, offer: Offer) -> list[OfferVersion]:
    return db.query(OfferVersion).filter(OfferVersion.offer_id == offer.id).order_by(OfferVersion.version_no.desc()).all()


def ensure_current_row(db: Session, offer: Offer) -> OfferVersion:
    """The row for the version on `offers` (v1 rows are made the first time anyone looks)."""
    row = (db.query(OfferVersion).filter(OfferVersion.offer_id == offer.id, OfferVersion.version_no == (offer.version_no or 1)).first())
    if row is not None:
        return row
    v = current_values(db, offer)
    from app.models.audit_log import AuditLog

    sent = (db.query(AuditLog).filter(AuditLog.entity_id == offer.application_id,
                                      AuditLog.action.in_(("offer_sent_for_signing", "offer_and_welcome_sent", "ai_offer_letter_generated")))
            .order_by(AuditLog.created_at).first())
    row = OfferVersion(tenant_id=offer.tenant_id, offer_id=offer.id, version_no=offer.version_no or 1, status="current",
                       letter_html=offer.offer_letter_text, ctc_total=v["ctc_total"], ctc_breakup_json=offer.ctc_breakup_json,
                       joining_date=offer.joining_date, designation=v["designation"], work_location=v["work_location"], terms=v["terms"] or None,
                       expiry_date=offer.expiry_date, sent_by=(sent.actor if sent is not None else "system"),
                       sent_at=offer.sent_at or (sent.created_at if sent is not None else offer.created_at), changes_json=[])
    db.add(row)
    db.flush()
    return row


def status_of(offer: Offer, row: OfferVersion) -> str:
    if row.status != "current":
        return row.status  # replaced | pending_approval | rejected | withdrawn
    if offer.declined_at:
        return "declined"
    if offer.signed:
        return "signed"
    if offer.viewed_at:
        return "viewed"
    return "sent" if offer.sent_at else "draft"


def sent_times(offer: Offer) -> int:
    return (1 if offer.sent_at else 0) + int(offer.resend_count or 0)


def last_sent(offer: Offer) -> Optional[datetime]:
    return offer.last_resent_at or offer.sent_at


def resend_available_at(offer: Offer) -> Optional[datetime]:
    last = last_sent(offer)
    return (last + RESEND_COOLDOWN) if last else None


def pending(db: Session, offer: Offer) -> Optional[OfferVersion]:
    return (db.query(OfferVersion).filter(OfferVersion.offer_id == offer.id, OfferVersion.status == "pending_approval")
            .order_by(OfferVersion.version_no.desc()).first())


def summary(db: Session, tenant, offer: Offer, user: Optional[User] = None) -> dict:
    from app.offers import esign

    row = ensure_current_row(db, offer)
    db.commit()
    avail = resend_available_at(offer)
    p = pending(db, offer)
    application = db.get(Application, offer.application_id)
    job = db.get(JobRole, application.job_role_id) if application else None
    return {
        "offer_id": str(offer.id), "version_no": offer.version_no or 1, "status": status_of(offer, row), "signed": bool(offer.signed),
        "sent_count": sent_times(offer), "last_sent_at": _iso(last_sent(offer)),
        "resend_available_at": _iso(avail) if avail and avail > _now() else None,
        "can_resend": not offer.signed and offer.sent_at is not None,
        "sign_url": None if offer.signed else esign.sign_url(db, offer),
        "values": current_values(db, offer),
        "band": {"min": _num(job.salary_band_min), "max": _num(job.salary_band_max)} if job else None,
        "reasons": [{"code": k, "label": v} for k, v in REASONS.items()],
        "pending": _version_dict(db, offer, p) if p is not None else None,
        "can_approve": bool(p is not None and user is not None and can_approve(db, tenant, user, job)),
        "history": [_version_dict(db, offer, r) for r in _rows(db, offer)],
    }


def _iso(v) -> Optional[str]:
    return v.isoformat() if v else None


def _version_dict(db: Session, offer: Offer, r: OfferVersion) -> dict:
    current = r.status == "current"
    return {
        "id": str(r.id), "version_no": r.version_no, "status": status_of(offer, r), "sent_at": _iso(r.sent_at), "sent_by": r.sent_by,
        "reason_code": r.reason_code, "reason": REASONS.get(r.reason_code or "", None), "reason_note": r.reason_note,
        "changes": r.changes_json or [], "ctc_total": _num(r.ctc_total), "joining_date": _iso(r.joining_date), "designation": r.designation,
        "viewed_at": _iso(offer.viewed_at if current else r.viewed_at), "signed_at": _iso(offer.signed_at if current else r.signed_at),
        "replaced_at": _iso(r.replaced_at), "resend_count": int((offer.resend_count if current else r.resend_count) or 0),
        "approval": r.approval_json, "created_at": _iso(r.created_at),
    }


# ---------------------------------------------------------------- resend

def resend(db: Session, tenant, offer: Offer, *, actor: str) -> dict:
    """Same offer, a new reminder email with the sign link. At most once every 15 minutes."""
    from app.offers import esign
    from app.platform.comms.defaults import send_default
    from app.recruitment.offer_welcome import greeting_name

    if offer.signed:
        raise ValueError("This offer is already signed - there is nothing to resend.")
    if offer.sent_at is None:
        raise ValueError("This offer hasn't been sent yet.")
    avail = resend_available_at(offer)
    if avail and avail > _now():
        raise CooldownError(max(1, int((avail - _now()).total_seconds() // 60) + 1))
    application = db.get(Application, offer.application_id)
    cand = db.get(Candidate, application.candidate_id)
    job = db.get(JobRole, application.job_role_id)
    if cand is None or not cand.email:
        raise ValueError("The candidate has no email address.")
    row = ensure_current_row(db, offer)
    m = send_default(db, tenant, "recruitment.offer_resend", to=[cand.email], related_entity_type="application", related_entity_id=application.id,
                     ctx={"candidate_first_name": greeting_name(db, cand), "job_title": (offer.designation or (job.title if job else "")),
                          "sign_link": esign.sign_url(db, offer), "expiry_date": offer.expiry_date.strftime("%d %B %Y") if offer.expiry_date else "soon",
                          "version_note": f" (version {offer.version_no})" if (offer.version_no or 1) > 1 else ""})
    now = _now()
    offer.resend_count = int(offer.resend_count or 0) + 1
    offer.last_resent_at = now
    row.resend_count = offer.resend_count
    db.commit()
    log_action(db, "application", application.id, "offer_resent", actor[:50],
               {"version": offer.version_no, "sent_times": sent_times(offer), "to": cand.email, "email_status": m.status})
    return {"email_status": m.status, "sent_count": sent_times(offer), "last_sent_at": now.isoformat()}


# ---------------------------------------------------------------- revise

def _salary_problems(db: Session, tenant, application: Application, job: JobRole, amount: Optional[float]) -> list[dict]:
    """Same limits as the salary stage: above the job's band max, or more than the department budget left."""
    from app.recruitment import budgets
    from app.recruitment.salary_auto import _setting

    out: list[dict] = []
    if amount is None:
        return out
    hi = _num(job.salary_band_max)
    if hi is not None and amount > hi:
        out.append({"code": "above_band", "band_max": hi, "over_pct": round(100 * (amount - hi) / hi, 1) if hi else None,
                    "margin_pct": float(_setting(db, tenant, "recruitment.salary.approval_margin_pct") or 0)})
    b = budgets.check(db, tenant, application, job, amount)
    if not b.get("ok", True):
        out.append({"code": "budget_short", "short_by": b.get("short_by"), "department": b.get("department"), "block": b.get("on_exceed") == "block"})
    return out


def can_approve(db: Session, tenant, user: User, job: Optional[JobRole]) -> bool:
    from app.recruitment.salary_auto import _approver_emails

    if (user.role or "") in ("admin", "super_admin"):
        return True
    return bool(job is not None and user.email and user.email.lower() in [e.lower() for e in _approver_emails(db, tenant, job)])


def _changes(old: dict, new: dict) -> list[dict]:
    out = []
    if _num(old["ctc_total"]) != _num(new["ctc_total"]):
        out.append({"field": "ctc_total", "label": "CTC", "old": lpa(old["ctc_total"]), "new": lpa(new["ctc_total"])})
    if (old["joining_date"] or None) != (new["joining_date"] or None):
        out.append({"field": "joining_date", "label": "Joining date", "old": _date_text(old["joining_date"]), "new": _date_text(new["joining_date"])})
    for f in ("designation", "work_location", "terms"):
        a, b = (old.get(f) or "").strip(), (new.get(f) or "").strip()
        if a != b:
            short = (lambda s: (s[:60] + "...") if len(s) > 60 else (s or "-"))
            out.append({"field": f, "label": FIELD_LABELS[f], "old": short(a), "new": short(b)})
    ctc_changed = bool(out) and out[0]["field"] == "ctc_total"
    old_c = {(c.get("code") or c.get("name")): _num(c.get("amount")) for c in old.get("components") or []}
    for c in new.get("components") or []:  # a breakup line on its own (with a new CTC the lines follow it anyway)
        key = c.get("code") or c.get("name")
        if not ctc_changed and key in old_c and old_c[key] != _num(c.get("amount")):
            out.append({"field": f"component:{key}", "label": c.get("name") or key, "old": f"{old_c[key]:,.0f}", "new": f"{_num(c.get('amount')):,.0f}"})
    return out


def revise(db: Session, tenant, offer: Offer, data: dict, *, actor: str, user: Optional[User] = None) -> dict:
    """HR's revised offer. -> {"state": "sent" | "pending_approval", "version_no", "changes"}"""
    from app.recruitment.ctc import compute_ctc_breakup

    application = db.get(Application, offer.application_id)
    job = db.get(JobRole, application.job_role_id)
    reason = (data.get("reason_code") or "").strip()
    note = (data.get("reason_note") or "").strip()
    if reason not in REASONS:
        raise ValueError("Pick a reason for the revised offer.")
    if reason == "other" and not note:
        raise ValueError("Add a short note for \"Other\".")
    if offer.declined_at is None and application.status in ("onboarding_completed",):
        raise ValueError("This person has already joined.")
    old = current_values(db, offer)
    joining = data.get("joining_date") or old["joining_date"]
    try:
        jd = date.fromisoformat(joining) if joining else None
    except ValueError as exc:
        raise ValueError("The joining date doesn't look right.") from exc
    if jd is not None and jd < date.today() and joining != old["joining_date"]:
        raise ValueError("The joining date can't be in the past.")
    ctc = _num(data.get("ctc_total")) if data.get("ctc_total") not in (None, "") else old["ctc_total"]
    if ctc is not None and ctc <= 0:
        raise ValueError("Enter the CTC as a yearly amount, e.g. 650000.")
    comps = data.get("components")
    if comps:
        breakup = {"base_ctc": ctc, "components": [{"code": c.get("code") or c.get("name"), "name": c.get("name") or c.get("code"), "type": "fixed",
                                                     "amount": round(_num(c.get("amount")) or 0, 2)} for c in comps], "total": 0}
        breakup["total"] = round(sum(c["amount"] for c in breakup["components"]), 2)
    else:
        breakup = compute_ctc_breakup(db, tenant, base_ctc=ctc) if ctc is not None else None
    new = {"ctc_total": ctc, "components": (breakup or {}).get("components") or [], "joining_date": jd.isoformat() if jd else None,
           "designation": (data.get("designation") if data.get("designation") is not None else old["designation"]) or "",
           "work_location": (data.get("work_location") if data.get("work_location") is not None else old["work_location"]) or "",
           "terms": (data.get("terms") if data.get("terms") is not None else old["terms"]) or ""}
    changes = _changes(old, new)
    if not changes:
        raise ValueError("Nothing has changed from the current offer.")
    problems = _salary_problems(db, tenant, application, job, ctc) if _num(ctc) != _num(old["ctc_total"]) else []
    if any(p.get("block") for p in problems):
        p = next(p for p in problems if p.get("block"))
        raise ValueError(f"The {p['department']} budget is short by {p['short_by']:,.0f} for this CTC; raise the budget first.")
    ensure_current_row(db, offer)
    for prev in db.query(OfferVersion).filter(OfferVersion.offer_id == offer.id, OfferVersion.status == "pending_approval").all():
        prev.status = "withdrawn"  # a newer revision replaces a draft still waiting for approval
    top = max([r.version_no for r in _rows(db, offer)] + [offer.version_no or 1])
    row = OfferVersion(tenant_id=offer.tenant_id, offer_id=offer.id, version_no=top + 1, status="pending_approval",
                       ctc_total=ctc, ctc_breakup_json=breakup, joining_date=jd, designation=new["designation"] or None,
                       work_location=new["work_location"] or None, terms=new["terms"] or None, reason_code=reason, reason_note=note or None,
                       changes_json=changes, sent_by=actor[:200])
    db.add(row)
    db.flush()
    if problems:  # above the limit: an approver must approve it (in the Offer section) before it goes out
        row.approval_json = {"needed": problems, "asked_by": actor, "asked_at": _now().isoformat()}
        db.commit()
        _ask_approvers(db, tenant, application, job, row)
        log_action(db, "application", application.id, "offer_revision_needs_approval", actor[:50],
                   {"version": row.version_no, "reason": reason, "changes": changes, "problems": problems})
        return {"state": "pending_approval", "version_no": row.version_no, "changes": changes, "problems": problems}
    return apply(db, tenant, offer, row, actor=actor)


def _ask_approvers(db: Session, tenant, application: Application, job: JobRole, row: OfferVersion) -> None:
    from app.models.comms import OutboundMessage
    from app.recruitment.salary_auto import _approver_emails

    cand = db.get(Candidate, application.candidate_id)
    what = ", ".join(f"{c['label']} {c['old']} -> {c['new']}" for c in row.changes_json or [])
    for addr in _approver_emails(db, tenant, job):
        db.add(OutboundMessage(tenant_id=tenant.tenant_id, channel="in_app", purpose="recruitment.salary", to_addresses=[addr],
                               subject=f"Revised offer needs approval: {(cand.full_name if cand else None) or 'a candidate'} for {job.title} ({what}) - above the limit.",
                               body_ref=f"/candidates/{application.id}", status="sent", related_entity_type="application", related_entity_id=application.id))
    db.commit()


def decide(db: Session, tenant, offer: Offer, version_id, *, approve: bool, user: User, note: Optional[str] = None) -> dict:
    application = db.get(Application, offer.application_id)
    job = db.get(JobRole, application.job_role_id)
    row = db.get(OfferVersion, version_id)
    if row is None or row.offer_id != offer.id or row.status != "pending_approval":
        raise ValueError("This revised offer isn't waiting for approval any more.")
    if not can_approve(db, tenant, user, job):
        raise PermissionError("Only an admin or a salary approver can approve this.")
    appr = dict(row.approval_json or {})
    if not approve:
        appr.update({"rejected_by": user.email, "rejected_at": _now().isoformat(), "note": note})
        row.approval_json, row.status = appr, "rejected"
        db.commit()
        log_action(db, "application", application.id, "offer_revision_rejected", user.email[:50], {"version": row.version_no, "note": note})
        return {"state": "rejected", "version_no": row.version_no}
    appr.update({"approved_by": user.email, "approved_at": _now().isoformat(), "note": note})
    row.approval_json = appr
    log_action(db, "application", application.id, "offer_revision_approved", user.email[:50], {"version": row.version_no, "note": note})
    return apply(db, tenant, offer, row, actor=user.email)


def apply(db: Session, tenant, offer: Offer, row: OfferVersion, *, actor: str) -> dict:
    """Replace the current version by `row`: freeze the old one, void its envelope, new letter + link, email."""
    from app.offers import esign
    from app.recruitment import budgets
    from app.recruitment.offer_welcome import _expiry_days, _text, render_offer

    application = db.get(Application, offer.application_id)
    job = db.get(JobRole, application.job_role_id)
    cand = db.get(Candidate, application.candidate_id)
    now = _now()
    cur = ensure_current_row(db, offer)
    was_signed = bool(offer.signed)
    cur.status, cur.replaced_at = "replaced", now
    cur.sign_token, cur.viewed_at, cur.signed_at, cur.signed_name = offer.sign_token, offer.viewed_at, offer.signed_at, offer.signed_name
    cur.signed_ip, cur.sign_method, cur.signed_pdf_path = offer.signed_ip, offer.sign_method, offer.signed_pdf_path
    cur.docusign_envelope_id, cur.letter_html, cur.resend_count = offer.docusign_envelope_id, offer.offer_letter_text, int(offer.resend_count or 0)
    cur.expiry_date = offer.expiry_date
    voided = _void_envelope(db, offer, row.version_no)
    offer.sign_token = None  # the old token now lives on the replaced row only
    db.flush()

    joining = row.joining_date or offer.joining_date
    expiry = date.today() + timedelta(days=_expiry_days(db))
    job_location = ((job.location if job else "") or "").strip()
    letter = render_offer(db, tenant, application, joining, salary=_num(row.ctc_total), designation=row.designation,
                          location=row.work_location if (row.work_location or "").strip() != job_location else None,  # only when HR changed it
                          terms=row.terms, expiry=expiry)
    offer.offer_letter_text, offer.joining_date, offer.expiry_date = letter, joining, expiry
    offer.designation, offer.work_location, offer.terms = row.designation, row.work_location, row.terms
    offer.ctc_breakup_json = row.ctc_breakup_json
    offer.signed, offer.signed_at, offer.signed_name, offer.signed_ip, offer.signed_user_agent = False, None, None, None, None
    offer.signed_pdf_path, offer.sign_method, offer.viewed_at, offer.declined_at = None, None, None, None
    offer.docusign_envelope_id, offer.docusign_sender_id = None, None
    offer.version_no, offer.resend_count, offer.last_resent_at, offer.sent_at = row.version_no, 0, None, now
    esign.ensure_token(offer)
    row.status, row.letter_html, row.sent_at, row.expiry_date = "current", letter, now, expiry
    row.sent_by = row.sent_by or actor[:200]
    if _num(row.ctc_total) is not None and _num(row.ctc_total) != _num(application.approved_salary):
        application.approved_salary = row.ctc_total
    if application.status == "onboarding_started":
        application.status = "offer_sent"  # a signed v1 still needs v2 signed
    db.commit()
    try:
        if _num(row.ctc_total) is not None:
            budgets.reserve(db, tenant, application, job, _num(row.ctc_total))
    except Exception:  # noqa: BLE001
        log.exception("budget reserve after revision failed")

    result = {"state": "sent", "version_no": row.version_no, "previous_version": cur.version_no, "changes": row.changes_json,
              "was_signed": was_signed, "docusign_voided": voided, "esign": False, "emailed": False}
    # DocuSign when it works (same rule as the first offer), else the in-app "Review & sign" link
    try:
        from app.offers.router import _try_create_docusign_envelope
        from app.recruitment.offer_welcome import _docusign_sender

        sender = _docusign_sender(db, tenant, job)
        if sender is not None and cand is not None and cand.email:
            env = _try_create_docusign_envelope(db, type("O", (), {"offer_letter_text": _text(letter), "application_id": application.id})(), cand, sender)
            if env:
                offer.docusign_envelope_id, offer.docusign_sender_id = env, sender.id
                db.commit()
                result["esign"] = True
    except Exception as exc:  # noqa: BLE001
        result["docusign_error"] = str(exc)[:200]
    if cand is not None and cand.email:
        result.update(_email_revised(db, tenant, offer, row, cand, job, docusign=result["esign"]))
    log_action(db, "application", application.id, "offer_revised", actor[:50],
               {"version": row.version_no, "previous_version": cur.version_no, "reason": row.reason_code, "note": row.reason_note,
                "changes": row.changes_json, "was_signed": was_signed, "docusign_voided": voided, "emailed": result["emailed"],
                "approval": row.approval_json})
    return result


def _void_envelope(db: Session, offer: Offer, new_version: int) -> Optional[bool]:
    if not offer.docusign_envelope_id or not offer.docusign_sender_id or offer.signed:
        return None
    try:
        from app.core.crypto import decrypt
        from app.integrations.docusign import void_envelope
        from app.offers.router import _get_docusign_integration

        integ = _get_docusign_integration(db, offer.docusign_sender_id)
        if integ is None:
            return False
        void_envelope(decrypt(integ.refresh_token), offer.docusign_envelope_id, f"Replaced by a revised offer (version {new_version}).")
        return True
    except Exception as exc:  # noqa: BLE001 -- the old in-app link is retired either way
        log_action(db, "application", offer.application_id, "docusign_void_failed", "system", {"error": str(exc)[:300]})
        return False


def _email_revised(db: Session, tenant, offer: Offer, row: OfferVersion, cand: Candidate, job: Optional[JobRole], *, docusign: bool) -> dict:
    from app.offers import esign
    from app.platform.comms.defaults import send_default
    from app.recruitment.offer_welcome import _text, greeting_name

    # the text goes through the HTML-escaping renderer: no "&", "<", ">" or quotes inside variables
    what = "\n".join(f"- {c['label']}: {c['old']} → {c['new']}" for c in row.changes_json or [])
    note = "\n(It was also sent to you through DocuSign; you can sign there instead.)" if docusign else ""
    try:
        m = send_default(db, tenant, "recruitment.offer_revised", to=[cand.email], related_entity_type="application", related_entity_id=offer.application_id,
                         ctx={"candidate_first_name": greeting_name(db, cand), "job_title": offer.designation or (job.title if job else ""),
                              "what_changed": what, "sign_link": esign.sign_url(db, offer), "docusign_note": note,
                              "expiry_date": offer.expiry_date.strftime("%d %B %Y"), "version_no": str(row.version_no), "letter": _text(offer.offer_letter_text or "")})
        return {"emailed": m.status in ("sent", "queued"), "email_status": m.status}
    except Exception as exc:  # noqa: BLE001
        log.exception("revised offer email failed")
        return {"emailed": False, "email_error": str(exc)[:200]}


# ---------------------------------------------------------------- after a revised version is signed

def apply_signed_version(db: Session, tenant, offer: Offer, *, actor: str) -> dict:
    """The joining date of the signed version goes everywhere: the hiring record, the onboarding case (and its
    plan), so the welcome portal and every later email use it. A "thank you" confirms it for v2+."""
    from app.models.onboarding import PreboardingCase
    from app.platform.comms.defaults import send_default
    from app.recruitment.offer_welcome import greeting_name

    out: dict = {"version": offer.version_no}
    application = db.get(Application, offer.application_id)
    if offer.joining_date and application is not None:
        fields = dict(application.custom_fields or {})
        joining = dict(fields.get("joining") or {})
        if joining.get("chosen") != offer.joining_date.isoformat():
            out["joining_was"] = joining.get("chosen")
            joining["chosen"] = offer.joining_date.isoformat()
            fields["joining"] = joining
            application.custom_fields = fields
            db.commit()
        case = db.query(PreboardingCase).filter(PreboardingCase.offer_id == offer.id).first()
        if case is not None and case.joining_date != offer.joining_date:
            from app.onboarding.portal import PreboardingPortal

            out["case_joining_was"] = case.joining_date.isoformat()
            PreboardingPortal(db, tenant).change_joining_date(case, offer.joining_date, actor=actor[:50], reason=f"revised offer v{offer.version_no} signed")
            out["case_joining_now"] = offer.joining_date.isoformat()
    if (offer.version_no or 1) > 1 and application is not None:
        cand = db.get(Candidate, application.candidate_id)
        job = db.get(JobRole, application.job_role_id)
        if cand is not None and cand.email:
            try:
                m = send_default(db, tenant, "recruitment.offer_revised_signed", to=[cand.email], related_entity_type="application",
                                 related_entity_id=application.id,
                                 ctx={"candidate_first_name": greeting_name(db, cand), "job_title": offer.designation or (job.title if job else ""),
                                      "joining_date": offer.joining_date.strftime("%A, %d %B %Y") if offer.joining_date else "",
                                      "version_no": str(offer.version_no)})
                out["confirmation_email"] = m.status
            except Exception:  # noqa: BLE001
                log.exception("revised-signed email failed")
    return out


# ---------------------------------------------------------------- PDFs per version

def version_pdf(db: Session, tenant, offer: Offer, version_no: int) -> Optional[bytes]:
    from pathlib import Path

    from app.offers.esign import _company, build_pdf

    if version_no == (offer.version_no or 1):
        if offer.signed and offer.signed_pdf_path and Path(offer.signed_pdf_path).exists():
            return Path(offer.signed_pdf_path).read_bytes()
        return build_pdf(offer, _company(db, tenant), db, tenant)
    r = db.query(OfferVersion).filter(OfferVersion.offer_id == offer.id, OfferVersion.version_no == version_no).first()
    if r is None or not r.letter_html:  # a revision still waiting for approval has no letter yet
        return None
    if r.signed_pdf_path and Path(r.signed_pdf_path).exists():
        return Path(r.signed_pdf_path).read_bytes()
    shim = type("V", (), {"offer_letter_text": r.letter_html or "", "signed_at": r.signed_at, "signed_name": r.signed_name,
                          "sign_method": r.sign_method, "signed_ip": r.signed_ip, "id": f"{offer.id} v{r.version_no}",
                          "version_no": r.version_no, "created_at": getattr(r, "created_at", None)})()
    return build_pdf(shim, _company(db, tenant), db, tenant)


def replaced_by_token(db: Session, token: str) -> Optional[tuple[OfferVersion, Offer]]:
    if not token:
        return None
    r = db.query(OfferVersion).filter(OfferVersion.sign_token == token).first()
    if r is None:
        return None
    return r, db.get(Offer, r.offer_id)

