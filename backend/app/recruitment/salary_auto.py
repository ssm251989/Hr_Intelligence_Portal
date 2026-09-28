"""Part 17.8: salary data collected automatically and checked against the job's band.

Where the figures come from (first one wins, never overwriting what's there):
  1. the careers apply form (current CTC, expected CTC, notice period);
  2. the resume (parser fields current_ctc / expected_ctc / notice_period_days);
  3. the candidate's own "Salary & joining details" form -- emailed automatically once the
     candidate is shortlisted and something is still missing, with one reminder after 24h.

check() runs whenever figures arrive and stores applications.salary_check:
  waiting (nothing yet) | in_band | needs_approval (above the band by <= X%, setting
  recruitment.salary.approval_margin_pct) | flagged (more than X% above) | no_band.
At the salary stage (after the interview is passed) apply_stage() moves the application:
  in band -> salary_approved (auto-approved), needs approval -> salary_above_band + a request
  to the approver, flagged -> salary_above_band marked "flagged". A person can always edit.
suggestion(): an offer figure inside the band, used to pre-fill the offer.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.user import User

FORM_ACTION = "salary_details_form"
SALARY_STAGE = "interview_selected"
FORM_TTL_DAYS = 14
REMINDER_AFTER = timedelta(hours=24)


def _setting(db: Session, tenant, key: str):
    from app.platform.settings.resolver import SettingContext, SettingsService

    return SettingsService(db).get(key, SettingContext(tenant=tenant))


def _num(v) -> Optional[float]:
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def missing_fields(candidate: Candidate) -> list[str]:
    need = []
    if candidate.expected_ctc is None:
        need.append("expected_ctc")
    if candidate.current_ctc is None:
        need.append("current_ctc")
    if candidate.notice_period_days is None:
        need.append("notice_period_days")
    return need


def suggestion(db: Session, tenant, job: JobRole, candidate: Candidate, application: Application) -> Optional[float]:
    """Inside the band: the current CTC plus the usual hike (setting
    recruitment.salary.target_hike_pct), at least what they expect when that fits the band,
    rounded to the nearest 10,000."""
    lo, hi = _num(job.salary_band_min), _num(job.salary_band_max)
    if hi is None:
        return None
    lo = lo if lo is not None else 0.0
    expected = _num(candidate.expected_ctc) or _num(application.expected_salary)
    current = _num(candidate.current_ctc)
    hike = float(_setting(db, tenant, "recruitment.salary.target_hike_pct") or 0)
    target = current * (1 + hike / 100) if current else expected
    if target is None:
        return None
    if expected is not None and expected <= hi:
        target = max(target, expected)
    return round(min(max(target, lo), hi) / 10000) * 10000


def check(db: Session, tenant, application: Application, *, job: Optional[JobRole] = None,
          candidate: Optional[Candidate] = None, actor: str = "system") -> dict:
    job = job or db.get(JobRole, application.job_role_id)
    candidate = candidate or db.get(Candidate, application.candidate_id)
    if application.expected_salary is None and candidate.expected_ctc is not None:
        application.expected_salary = candidate.expected_ctc
    expected = _num(application.expected_salary)
    lo, hi = _num(job.salary_band_min), _num(job.salary_band_max)
    margin = float(_setting(db, tenant, "recruitment.salary.approval_margin_pct") or 0)
    result: dict = {"expected": expected, "current": _num(candidate.current_ctc), "notice_days": candidate.notice_period_days,
                    "band_min": lo, "band_max": hi, "margin_pct": margin, "missing": missing_fields(candidate),
                    "checked_at": datetime.now(timezone.utc).isoformat()}
    # Part 18.13: auto-approve only when ALL pass -- hike <= X%, inside the band, budget left.
    hike_limit = float(_setting(db, tenant, "recruitment.salary.auto_approve_hike_pct") or 20)
    current = result["current"]
    reasons: list[dict] = []
    result["hike_limit_pct"] = hike_limit
    if expected is not None and current:
        result["hike_pct"] = round(100 * (expected - current) / current, 1)
        if result["hike_pct"] > hike_limit:
            reasons.append({"code": "hike", "hike_pct": result["hike_pct"], "limit_pct": hike_limit})
    elif expected is not None:
        reasons.append({"code": "no_current"})
    if hi is None:
        result["state"] = "no_band"
        if expected is not None:
            reasons.append({"code": "no_band"})
    elif expected is None:
        result["state"] = "waiting"
    else:
        over = 100 * (expected - hi) / hi if hi else 0.0
        span = (hi - (lo or 0)) or 1
        result["position_pct"] = round(100 * (expected - (lo or 0)) / span)
        result["over_pct"] = round(max(over, 0), 1)
        if expected > hi:
            reasons.append({"code": "above_band", "over_pct": result["over_pct"], "band_max": hi})
    if expected is not None:
        from app.recruitment import budgets

        result["budget"] = budgets.check(db, tenant, application, job, expected)
        if not result["budget"]["ok"]:
            reasons.append({"code": "budget_short", "short_by": result["budget"]["short_by"], "department": result["budget"]["department"],
                            "block": result["budget"].get("on_exceed") == "block"})
    result["reasons"] = reasons
    if expected is not None and hi is not None:
        far = any(r["code"] == "above_band" and r["over_pct"] > margin for r in reasons)
        result["state"] = "in_band" if not reasons else "flagged" if far else "needs_approval"
    result["auto_approvable"] = expected is not None and not reasons
    result["suggestion"] = suggestion(db, tenant, job, candidate, application)
    changed = (application.salary_check or {}).get("state") != result["state"]
    application.salary_check = result
    db.commit()
    if changed:
        log_action(db, "application", application.id, "salary_checked", actor[:50], {k: result.get(k) for k in ("state", "expected", "band_min", "band_max", "over_pct")})
    apply_stage(db, tenant, application, job=job, actor=actor)
    return result


def _approver_emails(db: Session, tenant, job: JobRole) -> list[str]:
    configured = _setting(db, tenant, "recruitment.salary.approvers") or []
    out = [str(e).strip().lower() for e in configured if "@" in str(e)]
    if not out and job.hiring_manager_id:
        u = db.get(User, job.hiring_manager_id)
        if u and u.email:
            out.append(u.email)
    if not out:
        out = [u.email for u in db.query(User).filter(User.tenant_id == tenant.tenant_id, User.role == "admin").order_by(User.created_at).limit(3) if u.email]
    return out


def apply_stage(db: Session, tenant, application: Application, *, job: JobRole, actor: str = "system") -> Optional[str]:
    """At the salary stage only: move the application on from its salary check."""
    from app.models.comms import OutboundMessage

    state = (application.salary_check or {}).get("state")
    # new figures back inside the band while waiting for approval -> approved as well
    if application.status == "salary_above_band" and state == "in_band":
        pass
    elif application.status != SALARY_STAGE or state not in ("in_band", "needs_approval", "flagged"):
        return None
    previous = application.status
    if state == "in_band":
        application.status = "salary_approved"
        # Part 18.13: auto-approved at what the candidate asked (all rules passed)
        application.approved_salary = application.expected_salary or application.salary_check.get("suggestion")
        note = "hike, band and budget all fine - approved automatically"
        from app.recruitment import budgets

        budgets.reserve(db, tenant, application, job, _num(application.approved_salary))
    else:
        application.status = "salary_above_band"
        note = "above the band - needs approval" if state == "needs_approval" else "far above the band - flagged"
        candidate = db.get(Candidate, application.candidate_id)
        for addr in _approver_emails(db, tenant, job):
            db.add(OutboundMessage(
                tenant_id=tenant.tenant_id, channel="in_app", purpose="recruitment.salary", to_addresses=[addr],
                subject=f"Salary approval needed: {(candidate.full_name if candidate else None) or 'a candidate'} for {job.title} "
                        f"expects {application.salary_check.get('expected'):,.0f} ({application.salary_check.get('over_pct')}% above the band).",
                body_ref="/salary", status="sent", related_entity_type="application", related_entity_id=application.id))
    db.commit()
    log_action(db, "application", application.id, "salary_auto_decided", actor[:50],
               {"state": state, "previous_status": previous, "new_status": application.status, "note": note})
    return application.status


def take_figures(db: Session, tenant, candidate: Candidate, figures: dict, *, source: str, overwrite: bool = False) -> list[str]:
    """Save the given figures on the candidate (only empty ones unless overwrite), then re-check
    every open application. -> names of the fields that were set."""
    set_fields = []
    for key in ("current_ctc", "expected_ctc", "notice_period_days", "willing_to_relocate"):
        value = figures.get(key)
        if value in (None, ""):
            continue
        if key == "notice_period_days":
            value = int(float(value))
        elif key != "willing_to_relocate":
            value = float(value)
        if overwrite or getattr(candidate, key) is None:
            setattr(candidate, key, value)
            set_fields.append(key)
    db.commit()
    if set_fields:
        log_action(db, "candidate", candidate.id, "salary_details_received", source[:50], {"fields": set_fields})
        for app in db.query(Application).filter(Application.tenant_id == tenant.tenant_id, Application.candidate_id == candidate.id).all():
            if app.status not in ("hr_rejected", "interview_rejected", "salary_rejected", "bgv_rejected", "onboarding_completed"):
                check(db, tenant, app, candidate=candidate, actor=source)
    return set_fields


# ---------------------------------------------------------------- the candidate's form

def form_link(token: str) -> str:
    from app.core.config import settings as app_settings

    return f"{app_settings.FRONTEND_URL.rstrip('/')}/salary-details/{token}"


def send_form(db: Session, tenant, application: Application, *, actor: str = "system", reminder: bool = False) -> dict:
    """Create (or reuse) the candidate's form link and email it through the company mailbox
    (template recruitment.salary_details_request). -> {"sent", "link"} (link only when mail failed)."""
    from app.models.iam import ActionToken
    from app.platform.iam.action_tokens import create_action_token

    candidate = db.get(Candidate, application.candidate_id)
    job = db.get(JobRole, application.job_role_id)
    if candidate is None or not candidate.email:
        return {"sent": False, "reason": "no email"}
    row = (db.query(ActionToken).filter(ActionToken.tenant_id == tenant.tenant_id, ActionToken.entity_type == "application",
                                        ActionToken.entity_id == application.id, ActionToken.action == FORM_ACTION,
                                        ActionToken.responded_at.is_(None), ActionToken.invalidated_at.is_(None),
                                        ActionToken.expires_at > datetime.now(timezone.utc)).first())
    if row is None:
        row = create_action_token(db, tenant, entity_type="application", entity_id=application.id, action=FORM_ACTION,
                                  payload={"reminded": False}, created_by=actor[:50], ttl_days=FORM_TTL_DAYS)
    link = form_link(row.token)
    try:
        from app.platform.comms.defaults import send_default  # Part 18.12: default wording on first use

        msg = send_default(db, tenant, "recruitment.salary_details_request", to=[candidate.email], related_entity_type="application",
                           related_entity_id=application.id,
                   ctx={"candidate_name": candidate.full_name or "", "candidate_first_name": (candidate.full_name or "").split(" ")[0],
                        "job_title": job.title if job else "", "form_link": link, "reminder": reminder},
                   purpose="email.outbound.recruitment")
        sent = msg.status in ("sent", "queued")
    except Exception:  # noqa: BLE001 -- no mailbox / template yet: HR can share the link instead
        sent = False
    if reminder:
        row.payload_json = {**(row.payload_json or {}), "reminded": True, "reminded_at": datetime.now(timezone.utc).isoformat()}
        db.commit()
    log_action(db, "application", application.id, "salary_form_reminder" if reminder else "salary_form_sent", actor[:50],
               {"sent": sent, "to": candidate.email})
    return {"sent": sent, "link": None if sent else link}


def after_shortlist(db: Session, tenant, application: Application, actor: str = "system") -> Optional[dict]:
    """Called when an application becomes Shortlisted: check the band, and ask the candidate
    for anything still missing (setting recruitment.salary.ask_after_shortlist)."""
    candidate = db.get(Candidate, application.candidate_id)
    check(db, tenant, application, candidate=candidate, actor=actor)
    # Part 18.12: the form goes out at the moment chosen in Settings (default: interview cleared)
    if (_setting(db, tenant, "recruitment.salary.form_trigger") or "interview_cleared") != "shortlisted":
        return None
    if candidate is not None and missing_fields(candidate) and _setting(db, tenant, "recruitment.salary.ask_after_shortlist"):
        return send_form(db, tenant, application, actor=actor)
    return None


def _already_answered(db: Session, tenant, application: Application) -> bool:
    from app.models.iam import ActionToken

    return db.query(ActionToken.id).filter(ActionToken.tenant_id == tenant.tenant_id, ActionToken.entity_type == "application",
                                           ActionToken.entity_id == application.id, ActionToken.action == FORM_ACTION,
                                           ActionToken.responded_at.isnot(None)).first() is not None


def after_interview(db: Session, tenant, application: Application, interview, actor: str = "system") -> Optional[dict]:
    """Part 18.12: an interview was marked "selected". If Settings say the salary form goes out
    when the interview is cleared (recruitment.salary.form_trigger) and this is the chosen round
    (recruitment.salary.form_after_round: 0 = the final decision, N = from round N on), email the
    branded form once; reminders follow recruitment.salary.reminder_hours."""
    from app.models.interview import Interview

    if (_setting(db, tenant, "recruitment.salary.form_trigger") or "interview_cleared") != "interview_cleared":
        return None
    wanted = int(_setting(db, tenant, "recruitment.salary.form_after_round") or 0)
    rounds = [i.id for i in db.query(Interview).filter(Interview.application_id == application.id)
              .order_by(Interview.scheduled_at.asc().nullslast(), Interview.created_at.asc())]
    this_round = rounds.index(interview.id) + 1 if interview.id in rounds else len(rounds)
    if wanted and this_round < wanted:
        return None
    if _already_answered(db, tenant, application):
        return {"sent": False, "reason": "already answered"}
    return send_form(db, tenant, application, actor=actor)


def remind_due(db: Session, tenant) -> int:
    """Scheduled (hourly): reminders at each of recruitment.salary.reminder_hours (default 24 and
    48 hours) after the form was sent, while it is still not filled in. Part 18.12."""
    from app.models.iam import ActionToken

    hours = sorted(int(h) for h in (_setting(db, tenant, "recruitment.salary.reminder_hours") or [24, 48]) if int(h) > 0)
    if not hours:
        return 0
    now = datetime.now(timezone.utc)
    rows = (db.query(ActionToken).filter(ActionToken.tenant_id == tenant.tenant_id, ActionToken.action == FORM_ACTION,
                                         ActionToken.responded_at.is_(None), ActionToken.invalidated_at.is_(None),
                                         ActionToken.created_at < now - timedelta(hours=hours[0]), ActionToken.expires_at > now).all())
    done = 0
    for row in rows:
        payload = row.payload_json or {}
        sent = int(payload.get("reminders", 1 if payload.get("reminded") else 0))
        if sent >= len(hours) or now - row.created_at < timedelta(hours=hours[sent]):
            continue
        app = db.get(Application, row.entity_id)
        if app is None:
            continue
        send_form(db, tenant, app, reminder=True)
        row.payload_json = {**(row.payload_json or {}), "reminders": sent + 1}
        db.commit()
        done += 1
    return done


# ---------------------------------------------------------------- Part 18.13: HR decision

DECISIONS = ("approve", "counter", "reject")


def decide(db: Session, tenant, application: Application, *, decision: str, actor: str, amount: Optional[float] = None,
           reason: Optional[str] = None) -> dict:
    """HR's decision for a candidate who needs approval: approve (at `amount` or what they asked),
    counter-offer an amount (the candidate is emailed), or reject with a reason."""
    from app.recruitment import budgets

    if decision not in DECISIONS:
        raise ValueError("decision must be approve, counter or reject")
    job = db.get(JobRole, application.job_role_id)
    candidate = db.get(Candidate, application.candidate_id)
    check_ = dict(application.salary_check or {})
    if application.status not in ("salary_above_band", SALARY_STAGE, "salary_ok"):
        raise ValueError("This candidate is not waiting for a salary decision.")
    if decision == "approve":
        final = amount if amount is not None else _num(application.expected_salary)
        if final is None:
            raise ValueError("Enter the approved amount.")
        b = budgets.check(db, tenant, application, job, final)
        if not b["ok"] and b.get("on_exceed") == "block":
            raise ValueError(f"The {b['department']} budget for {b['fiscal_year']} is short by {b['short_by']:,.0f}; "
                             "raise the budget in Settings > Hiring > Department budgets first.")
        application.status, application.approved_salary = "salary_approved", final
        check_["decision"] = {"by": actor, "at": datetime.now(timezone.utc).isoformat(), "decision": "approved", "amount": final}
        application.salary_check = check_
        db.commit()
        budgets.reserve(db, tenant, application, job, final)
    elif decision == "counter":
        if amount is None or amount <= 0:
            raise ValueError("Enter the counter-offer amount.")
        check_["counter"] = {"amount": amount, "by": actor, "at": datetime.now(timezone.utc).isoformat(), "note": reason}
        application.salary_check = check_
        db.commit()
        if candidate and candidate.email:
            try:
                from app.platform.comms.defaults import send_default

                send_default(db, tenant, "recruitment.salary_counter_offer", to=[candidate.email], related_entity_type="application",
                             related_entity_id=application.id,
                             ctx={"candidate_first_name": (candidate.full_name or "").split(" ")[0], "job_title": job.title if job else "",
                                  "amount": f"{amount:,.0f}", "note": reason or ""})
            except Exception:  # noqa: BLE001 -- recorded either way; HR can call the candidate
                pass
    else:
        if not (reason or "").strip():
            raise ValueError("Please give a reason.")
        application.status = "salary_rejected"
        check_["decision"] = {"by": actor, "at": datetime.now(timezone.utc).isoformat(), "decision": "rejected", "reason": reason}
        application.salary_check = check_
        db.commit()
        budgets.release(db, tenant, application.id)
    log_action(db, "application", application.id, f"salary_{decision}", actor[:50], {"amount": amount, "reason": reason})
    return {"status": application.status, "approved_salary": _num(application.approved_salary), "salary_check": application.salary_check}
