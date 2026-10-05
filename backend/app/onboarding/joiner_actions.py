"""Fix 2026-10-05: what HR can do with a new joiner, stage by stage (rules in joiner_stage.py).

Before joining   withdraw_offer (company decision, reason, email to the candidate) | candidate_declined (reason list)
Joining day on   mark_joined (-> employee; the ONLY way to "joined", the Offers page uses it too) | no_show
After joining    not_reporting (reminder / show-cause / final notice emails, then HR confirms) | absconded |
                 resigned | terminated -- each a real Exit case (Exits module: clearance + asset recovery, LWD,
                 rehire eligible), records kept, never deleted.
After ANY of these closes the person (_after_close): application status, the job's opening back (re-opened if it
had closed itself as filled) + a to-do for the recruiter with the talent-pool matches, the department budget
released, pending emails / reminders / links cancelled, manager + HR told, everything in the audit log on the
application (so the candidate timeline shows the whole story) and on the onboarding case.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.offer import Offer
from app.models.onboarding import PreboardingCase
from app.onboarding import joiner_stage
from app.onboarding.joiner_stage import ActionNotAllowed

log = logging.getLogger(__name__)

DECLINE_REASONS = {
    "accepted_other_offer": "Accepted another offer", "compensation": "Salary / benefits", "location": "Location or relocation",
    "role": "Role or responsibilities", "personal": "Personal / family reasons", "counter_offer": "Counter-offer from current employer",
    "no_response": "Stopped responding", "other": "Other",
}
NO_SHOW_REASONS = {
    "no_contact": "Could not be reached", "accepted_other_offer": "Joined another company", "personal": "Personal / family reasons",
    "health": "Health reasons", "relocation": "Could not relocate", "other": "Other",
}
EXIT_REASONS = {
    "absconded": {"no_contact": "Stopped coming, not reachable", "other_job": "Joined another company", "other": "Other"},
    "resigned": {"better_offer": "Better offer elsewhere", "role_mismatch": "Role not as expected", "culture": "Team / culture fit",
                 "personal": "Personal / family reasons", "relocation": "Relocation", "health": "Health reasons", "other": "Other"},
    "terminated": {"performance": "Performance in probation", "conduct": "Conduct / policy breach", "attendance": "Attendance",
                   "background_check": "Background check finding", "other": "Other"},
}
SEPARATION_TYPE = {"absconded": "absconding", "resigned": "resignation", "terminated": "termination"}
APP_STATUS = {"withdraw_offer": "offer_withdrawn", "candidate_declined": "offer_declined", "no_show": "no_show",
              "absconded": "left_after_joining", "resigned": "left_after_joining", "terminated": "left_after_joining"}
NOTICES = (("reminder", "onboarding.not_reporting.reminder_days", 2, "onboarding.not_reporting_reminder"),
           ("show_cause", "onboarding.not_reporting.show_cause_days", 5, "onboarding.not_reporting_show_cause"),
           ("final", "onboarding.not_reporting.final_days", 10, "onboarding.not_reporting_final"))


class ActionError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _setting(db: Session, tenant, key: str, default=None):
    from app.platform.settings.resolver import SettingContext, SettingsService

    try:
        v = SettingsService(db).get(key, SettingContext(tenant=tenant))
    except Exception:  # noqa: BLE001 -- an unregistered key in an old install
        return default
    return default if v is None else v


def _ctx(db: Session, case: PreboardingCase):
    application = db.get(Application, case.application_id) if case.application_id else None
    cand = db.get(Candidate, case.candidate_id) if case.candidate_id else None
    job = db.get(JobRole, application.job_role_id) if application is not None and application.job_role_id else None
    offer = db.get(Offer, case.offer_id) if case.offer_id else None
    return application, cand, job, offer


def person_name(db: Session, case: PreboardingCase) -> str:
    cand = db.get(Candidate, case.candidate_id) if case.candidate_id else None
    return (cand.full_name if cand else None) or case.email or "This person"


def _require(db: Session, case: PreboardingCase, action: str) -> None:
    joiner_stage.require(db, case, action, name=person_name(db, case))


def _reason(text: Optional[str], code: Optional[str], allowed: Optional[dict]) -> tuple[Optional[str], str]:
    code = (code or "").strip() or None
    text = " ".join((text or "").split())
    if allowed is not None:
        if code not in allowed:
            raise ActionError("Pick a reason from the list.")
        if code == "other" and not text:
            raise ActionError("Add a short note for \"Other\".")
        return code, text or allowed[code]
    if len(text) < 3:
        raise ActionError("Please give a reason.")
    return code, text


def _outcome(case: PreboardingCase, **data) -> None:
    attrs = dict(case.attributes_json or {})
    attrs["outcome"] = {k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in data.items()}
    case.attributes_json = attrs


def _log(db: Session, case: PreboardingCase, application: Optional[Application], action: str, actor: str, details: dict) -> None:
    clean = {k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in details.items()}
    log_action(db, "preboarding_case", case.id, action, actor[:50], clean)
    if application is not None:  # the candidate timeline reads the application's audit trail
        log_action(db, "application", application.id, action, actor[:50], clean)


# ---------------------------------------------------------------- before joining

def withdraw_offer(db: Session, tenant, case: PreboardingCase, *, actor: str, reason: str, notes: Optional[str] = None) -> dict:
    _require(db, case, "withdraw_offer")
    _, text = _reason(reason, None, None)
    application, cand, job, offer = _ctx(db, case)
    _close_case(db, tenant, case, "revoked", actor=actor, reason=text)
    _outcome(case, kind="withdraw_offer", reason=text, notes=notes, at=_now(), actor=actor)
    db.commit()
    emailed = None
    if cand is not None and cand.email:
        from app.candidates.names import given_name
        from app.platform.comms.defaults import send_default

        try:
            m = send_default(db, tenant, "onboarding.offer_withdrawn", to=[cand.email], related_entity_type="application",
                             related_entity_id=application.id if application else None,
                             ctx={"candidate_first_name": given_name(cand), "job_title": job.title if job else "the role"})
            emailed = m.status
        except Exception:  # noqa: BLE001
            log.exception("offer-withdrawn email failed")
    out = _after_close(db, tenant, case, "withdraw_offer", actor=actor, reason=text)
    _log(db, case, application, "offer_withdrawn", actor, {"reason": text, "notes": notes, "email": emailed, **out})
    return {"status": case.status, "email": emailed, **out}


def candidate_declined(db: Session, tenant, case: PreboardingCase, *, actor: str, reason_code: str, notes: Optional[str] = None) -> dict:
    _require(db, case, "candidate_declined")
    code, text = _reason(notes, reason_code, DECLINE_REASONS)
    application, _cand, _job, offer = _ctx(db, case)
    _close_case(db, tenant, case, "declined", actor=actor, reason=text)
    if offer is not None:
        offer.declined_at = _now()
    _outcome(case, kind="candidate_declined", reason_code=code, reason=DECLINE_REASONS[code], notes=notes, at=_now(), actor=actor)
    db.commit()
    out = _after_close(db, tenant, case, "candidate_declined", actor=actor, reason=DECLINE_REASONS[code])
    _log(db, case, application, "offer_declined_by_candidate", actor, {"reason_code": code, "reason": DECLINE_REASONS[code], "notes": notes, **out})
    return {"status": case.status, **out}


# ---------------------------------------------------------------- joining day

def mark_joined(db: Session, tenant, case: PreboardingCase, *, actor: str) -> dict:
    """The one way to "joined": the employee record goes live AND the hiring record says Joined."""
    from app.onboarding.conversion import ConversionError, convert

    _require(db, case, "mark_joined")
    try:
        result = convert(db, tenant, case, actor=actor)
    except ConversionError as exc:
        raise ActionError(str(exc)) from exc
    application, _cand, _job, offer = _ctx(db, case)
    if application is not None and application.status != "onboarding_completed":
        previous = application.status
        application.status = "onboarding_completed"
        if offer is not None:
            offer.onboarding_status = "completed"
        db.commit()
        log_action(db, "application", application.id, "onboarding_completed", actor[:50],
                   {"previous_status": previous, "new_status": "onboarding_completed", "employee_code": result.get("employee_code")})
    return result


def no_show(db: Session, tenant, case: PreboardingCase, *, actor: str, reason_code: str, notes: Optional[str] = None,
            contacted_on: Optional[date] = None) -> dict:
    _require(db, case, "no_show")
    code, text = _reason(notes, reason_code, NO_SHOW_REASONS)
    if contacted_on is not None and contacted_on > date.today():
        raise ActionError("\"Contacted on\" can't be in the future.")
    application, *_ = _ctx(db, case)
    _close_case(db, tenant, case, "no_show", actor=actor, reason=text)
    _outcome(case, kind="no_show", reason_code=code, reason=NO_SHOW_REASONS[code], notes=notes, contacted_on=contacted_on, at=_now(), actor=actor)
    db.commit()
    out = _after_close(db, tenant, case, "no_show", actor=actor, reason=NO_SHOW_REASONS[code])
    _log(db, case, application, "marked_no_show", actor, {"reason_code": code, "reason": NO_SHOW_REASONS[code], "notes": notes,
                                                          "contacted_on": contacted_on, **out})
    return {"status": case.status, **out}


def _close_case(db: Session, tenant, case: PreboardingCase, status: str, *, actor: str, reason: str) -> None:
    from app.onboarding.portal import PreboardingPortal

    PreboardingPortal(db, tenant)._close(case, status, actor=actor, reason=reason)


# ---------------------------------------------------------------- after joining: not reporting -> absconded

def start_not_reporting(db: Session, tenant, case: PreboardingCase, *, actor: str, last_seen: date, notes: Optional[str] = None) -> dict:
    _require(db, case, "not_reporting")
    if last_seen > date.today():
        raise ActionError("The last day they came in can't be in the future.")
    attrs = dict(case.attributes_json or {})
    attrs["not_reporting"] = {"status": "active", "last_seen": last_seen.isoformat(), "started_at": _now().isoformat(), "started_by": actor,
                              "notes": notes, "notices": []}
    case.attributes_json = attrs
    db.commit()
    application, *_ = _ctx(db, case)
    _log(db, case, application, "not_reporting_started", actor, {"last_seen": last_seen, "notes": notes, "schedule": notice_schedule(db, tenant)})
    sent = run_not_reporting_notices(db, tenant, case=case)  # a long-ago last day sends what is already due
    return {"not_reporting": case.attributes_json["not_reporting"], "sent_now": sent}


def stop_not_reporting(db: Session, tenant, case: PreboardingCase, *, actor: str, note: str) -> dict:
    _require(db, case, "stop_not_reporting")
    if len((note or "").strip()) < 3:
        raise ActionError("Add a short note, e.g. \"Came back on 12 Oct, was unwell\".")
    attrs = dict(case.attributes_json or {})
    flow = dict(attrs.get("not_reporting") or {})
    flow.update({"status": "stopped", "stopped_at": _now().isoformat(), "stopped_by": actor, "stop_note": note.strip()})
    attrs["not_reporting"] = flow
    case.attributes_json = attrs
    db.commit()
    application, *_ = _ctx(db, case)
    _log(db, case, application, "not_reporting_stopped", actor, {"note": note.strip(), "notices_sent": [n["kind"] for n in flow.get("notices", [])]})
    return {"not_reporting": flow}


def notice_schedule(db: Session, tenant) -> dict:
    return {kind: int(_setting(db, tenant, key, default) or default) for kind, key, default, _tpl in NOTICES}


def run_not_reporting_notices(db: Session, tenant, *, case: Optional[PreboardingCase] = None, today: Optional[date] = None) -> int:
    """Scheduled (hourly): for everyone marked "not reporting", send each notice once its day has come
    (days counted from the last day they came in). After the final notice HR confirms Absconded."""
    from app.candidates.names import given_name
    from app.platform.comms.defaults import send_default

    today = today or date.today()
    if not _setting(db, tenant, "onboarding.not_reporting.enabled", True):
        return 0
    schedule = notice_schedule(db, tenant)
    cases = [case] if case is not None else [c for c in db.query(PreboardingCase).filter(PreboardingCase.tenant_id == tenant.tenant_id,
                                                                                          PreboardingCase.status == "joined").all()
                                             if ((c.attributes_json or {}).get("not_reporting") or {}).get("status") == "active"]
    sent = 0
    for c in cases:
        attrs = dict(c.attributes_json or {})
        flow = dict(attrs.get("not_reporting") or {})
        if flow.get("status") != "active":
            continue
        days = (today - date.fromisoformat(flow["last_seen"])).days
        done = {n["kind"] for n in flow.get("notices", [])}
        application, cand, job, _offer = _ctx(db, c)
        for kind, _key, _default, template in NOTICES:
            if kind in done or days < schedule[kind]:
                continue
            to = [e for e in {c.email, cand.email if cand else None} if e]
            try:
                m = send_default(db, tenant, template, to=to, related_entity_type="preboarding_case", related_entity_id=c.id,
                                 ctx={"candidate_first_name": given_name(cand) if cand else "", "job_title": job.title if job else "",
                                      "last_seen": date.fromisoformat(flow["last_seen"]).strftime("%d %B %Y"), "days_absent": str(days),
                                      "respond_by": (today + timedelta(days=2)).strftime("%d %B %Y"),
                                      "hr_contact": _hr_contact(db, tenant)})
                status = m.status
            except Exception as exc:  # noqa: BLE001
                status = f"failed: {exc}"[:120]
            flow.setdefault("notices", []).append({"kind": kind, "sent_at": _now().isoformat(), "day": days, "email": status, "to": to})
            attrs["not_reporting"] = flow
            c.attributes_json = attrs
            db.commit()
            _notify_internal(db, tenant, c, f"{person_name(db, c)}: {kind.replace('_', '-')} notice sent (day {days} away)"
                             + (" - you can now confirm Absconded." if kind == "final" else ""))
            _log(db, c, application, f"not_reporting_{kind}_sent", "system", {"day": days, "email": status, "to": to})
            sent += 1
    return sent


def _hr_contact(db: Session, tenant) -> str:
    from app.recruitment.offer_welcome import contacts_for

    people = contacts_for(db, tenant, None)
    first = next((p for p in people if p.get("email")), None)
    return f"{first['name']} ({first['email']})" if first else "your HR team (reply to this email)"


# ---------------------------------------------------------------- after joining: the exits

def record_exit(db: Session, tenant, case: PreboardingCase, *, kind: str, actor: str, last_working_day: date, reason_code: str,
                notes: str, rehire_eligible: Optional[bool] = None, actor_user_id=None) -> dict:
    """Absconded / resigned / terminated: an Exit case (clearance + asset recovery), employee kept, access removed."""
    from app.models.core_hr import Employee
    from app.service_desk import separations

    if kind not in SEPARATION_TYPE:
        raise ActionError("Unknown exit type.")
    _require(db, case, kind)
    code, text = _reason(notes, reason_code, EXIT_REASONS[kind])
    if len((notes or "").strip()) < 3:
        raise ActionError("Please add notes (what happened, who was told).")
    emp = db.get(Employee, case.employee_id) if case.employee_id else None
    if emp is None:
        raise ActionError("This person has no employee record.")
    if last_working_day < case.joining_date:
        raise ActionError(f"The last working day can't be before the joining date ({case.joining_date.strftime('%d %b %Y')}).")
    if kind == "absconded" and last_working_day > date.today():
        raise ActionError("For absconding, the last working day is the last day they actually came in (today or earlier).")
    rehire = rehire_eligible if rehire_eligible is not None else (kind == "resigned")
    try:
        sep = separations.initiate(db, tenant, employee_id=emp.id, separation_type=SEPARATION_TYPE[kind], actor=actor,
                                   submitted_on=min(date.today(), last_working_day), requested_lwd=last_working_day,
                                   reason_text=f"{EXIT_REASONS[kind][code]}. {notes.strip()}", actor_user_id=actor_user_id)
        if sep.status == "retention":  # the recorded exit is a fact, not a request to talk them out of
            separations.record_retention(db, sep, notes="Early leaver recorded from onboarding.", retained=False, actor=actor)
        short = max(0, (separations.standard_lwd(sep) - last_working_day).days)
        separations.approve_lwd(db, tenant, sep, lwd=last_working_day, actor=actor, waived_days=short)  # -> clearance + asset recovery
    except separations.SeparationError as exc:
        raise ActionError(str(exc)) from exc
    sep.rehire_eligible = rehire
    application, *_ = _ctx(db, case)
    if kind == "absconded":
        attrs = dict(case.attributes_json or {})
        flow = dict(attrs.get("not_reporting") or {})
        if flow.get("status") == "active":
            flow.update({"status": "confirmed", "confirmed_at": _now().isoformat(), "confirmed_by": actor})
            attrs["not_reporting"] = flow
            case.attributes_json = attrs
        sep.absconding_notices_json = [{"kind": n["kind"], "issued_at": n["sent_at"], "issued_by": "system (email)"} for n in flow.get("notices", [])]
    days_in = (last_working_day - case.joining_date).days
    case.status = "exited"
    case.history_json = [*(case.history_json or []), {"event": kind, "actor": actor, "at": _now().isoformat(), "reason": EXIT_REASONS[kind][code],
                                                      "last_working_day": last_working_day.isoformat()}]
    _outcome(case, kind=kind, reason_code=code, reason=EXIT_REASONS[kind][code], notes=notes.strip(), last_working_day=last_working_day,
             days_after_joining=days_in, rehire_eligible=rehire, separation_id=str(sep.id), at=_now(), actor=actor)
    db.commit()
    access = _revoke_access(db, tenant, case, emp, now_too=kind == "absconded" or last_working_day <= date.today())
    clearance = [{"title": i.title, "kind": i.kind, "department": i.department} for i in separations._items(db, sep)]
    out = _after_close(db, tenant, case, kind, actor=actor, reason=EXIT_REASONS[kind][code])
    _notify_internal(db, tenant, case, f"{person_name(db, case)} {kind} - last working day {last_working_day.strftime('%d %b %Y')}"
                     f" ({days_in} days after joining). Exit case and clearance checklist created.", email=True, include_manager=emp)
    _log(db, case, application, f"joiner_{kind}", actor, {"reason_code": code, "reason": EXIT_REASONS[kind][code], "notes": notes.strip(),
                                                         "last_working_day": last_working_day, "days_after_joining": days_in,
                                                         "rehire_eligible": rehire, "separation_id": str(sep.id), "access": access,
                                                         "clearance_items": len(clearance), **out})
    return {"status": case.status, "separation_id": str(sep.id), "separation_status": sep.status, "clearance": clearance, "access": access, **out}


def _revoke_access(db: Session, tenant, case: PreboardingCase, emp, *, now_too: bool) -> dict:
    """Welcome portal link dies with the case; the app login is switched off now (absconded / LWD passed) or on the LWD."""
    from app.models.user import User

    case.portal_token_expires_at = min(case.portal_token_expires_at, _now())
    out = {"portal_link": "revoked", "login": None}
    user = db.get(User, emp.user_id) if emp is not None and emp.user_id else None
    if user is not None:
        if now_too:
            user.deactivated_at = user.deactivated_at or _now()
            out["login"] = "deactivated"
        else:
            out["login"] = "until last working day"
    db.commit()
    return out


def deactivate_after_lwd(db: Session, tenant, today: Optional[date] = None) -> int:
    """Scheduled: logins of leavers whose last working day has passed are switched off."""
    from app.models.core_hr import Employee
    from app.models.user import User

    today = today or date.today()
    n = 0
    for c in db.query(PreboardingCase).filter(PreboardingCase.tenant_id == tenant.tenant_id, PreboardingCase.status == "exited").all():
        lwd = ((c.attributes_json or {}).get("outcome") or {}).get("last_working_day")
        emp = db.get(Employee, c.employee_id) if c.employee_id else None
        user = db.get(User, emp.user_id) if emp is not None and emp.user_id else None
        if lwd and date.fromisoformat(lwd) < today and user is not None and user.deactivated_at is None:
            user.deactivated_at = _now()
            n += 1
    db.commit()
    return n


# ---------------------------------------------------------------- after any close

def _after_close(db: Session, tenant, case: PreboardingCase, action: str, *, actor: str, reason: str) -> dict:
    from app.recruitment import budgets

    application, _cand, job, _offer = _ctx(db, case)
    out: dict = {}
    if application is not None:
        out["application_was"] = application.status
        application.previous_status = application.status
        application.status = APP_STATUS[action]
        db.commit()
        budgets.release(db, tenant, application.id)
        out["budget"] = "released"
    out["cancelled"] = _cancel_pending(db, tenant, case, application)
    if job is not None:
        out.update(_reopen_position(db, tenant, job, person=person_name(db, case), why=action, actor=actor))
    return out


def _cancel_pending(db: Session, tenant, case: PreboardingCase, application: Optional[Application]) -> dict:
    from app.models.iam import ActionToken
    from app.models.comms import OutboundMessage

    ids = [case.id] + ([application.id] if application is not None else [])
    msgs = (db.query(OutboundMessage).filter(OutboundMessage.tenant_id == tenant.tenant_id, OutboundMessage.related_entity_id.in_(ids),
                                             OutboundMessage.status == "queued").all())
    for m in msgs:
        m.status, m.error = "suppressed", "cancelled: the person's onboarding was closed"
    toks = (db.query(ActionToken).filter(ActionToken.tenant_id == tenant.tenant_id, ActionToken.entity_id.in_(ids),
                                         ActionToken.invalidated_at.is_(None), ActionToken.responded_at.is_(None)).all())
    for t in toks:
        t.invalidated_at = _now()
    case.portal_token_expires_at = min(case.portal_token_expires_at, _now())
    db.commit()
    return {"emails": len(msgs), "links": len(toks), "portal_link": "revoked"}


def _reopen_position(db: Session, tenant, job: JobRole, *, person: str, why: str, actor: str) -> dict:
    """The opening is free again: re-open the job if it closed itself as filled, and give the recruiter a to-do."""
    from app.experience.ui_jobs_router import _last_auto_close, _stage_counts
    from app.models.intelligence import AgentSuggestion
    from app.recruitment.automation import talent_pool

    hired = _stage_counts(db).get(job.id, {}).get("hired", 0)
    positions = job.positions_count or 1
    out = {"openings_left": max(0, positions - hired)}
    if job.status == "closed" and hired < positions and (_last_auto_close(db, [job.id]).get(job.id) or {}).get("reason") == "positions_filled":
        job.status = "published"
        db.commit()
        log_action(db, "job_role", job.id, "job_reopened_position_open_again", actor[:50], {"hired": hired, "positions_count": positions, "because": why})
        out["job_reopened"] = True
    try:
        pool = talent_pool(db, tenant, job, limit=50)
        top = [r for r in pool["items"] if r["score"] >= pool["threshold"] and not r["knocked_out"]][:5]
        n = int(pool["matching"])
    except Exception:  # noqa: BLE001 -- the to-do still goes out
        log.exception("talent pool re-match failed")
        top, n = [], 0
    label = {"withdraw_offer": "offer withdrawn", "candidate_declined": "offer declined", "no_show": "did not join",
             "absconded": "absconded", "resigned": "resigned", "terminated": "terminated"}[why]
    title = f"Position open again - {n} past candidate{'s' if n != 1 else ''} match ({job.title})"
    payload = {"job_id": str(job.id), "job_title": job.title, "matches": n, "person": person, "why": label,
               "top": [{"candidate_id": r["candidate_id"], "name": r["name"], "score": r["score"]} for r in top]}
    open_todo = (db.query(AgentSuggestion).filter(AgentSuggestion.tenant_id == tenant.tenant_id, AgentSuggestion.kind == "position_open_again",
                                                  AgentSuggestion.entity_id == job.id, AgentSuggestion.status == "pending").first())
    if open_todo is not None:  # one to-do per job: refreshed, with everyone who left
        earlier = list((open_todo.payload_json or {}).get("people") or [{"person": (open_todo.payload_json or {}).get("person"), "why": (open_todo.payload_json or {}).get("why")}])
        open_todo.title = title
        open_todo.payload_json = {**payload, "person": ", ".join(p["person"] for p in [*earlier, {"person": person}] if p.get("person")),
                                  "people": [*earlier, {"person": person, "why": label}]}
    else:
        db.add(AgentSuggestion(tenant_id=tenant.tenant_id, agent="recruiter", kind="position_open_again", title=title,
                               entity_type="job_role", entity_id=job.id, reviewer_permission="recruitment.job.edit", reviewer_user_id=job.created_by,
                               payload_json={**payload, "people": [{"person": person, "why": label}]}))
    db.commit()
    out["talent_pool_matches"] = n
    return out


def _notify_internal(db: Session, tenant, case: PreboardingCase, text: str, *, email: bool = False, include_manager=None) -> list[str]:
    """In-app (and optionally email) to the job's owner / hiring manager, the employee's reporting manager."""
    from app.models.comms import OutboundMessage
    from app.recruitment.scoring.autoshortlist import _recipients

    application, _cand, job, _offer = _ctx(db, case)
    to = set(_recipients(db, job, ["job_owner", "hiring_manager"]) if job is not None else [])
    if include_manager is not None:
        to |= set(_manager_emails(db, tenant, include_manager))
    for addr in sorted(to):
        db.add(OutboundMessage(tenant_id=tenant.tenant_id, channel="in_app", purpose="onboarding.joiner_exit", to_addresses=[addr], subject=text,
                               body_ref=f"/candidates/{application.id}" if application else "/onboarding", status="sent",
                               related_entity_type="preboarding_case", related_entity_id=case.id))
    db.commit()
    if email and to:
        from app.platform.comms.defaults import send_default

        try:
            send_default(db, tenant, "onboarding.joiner_exit_internal", to=sorted(to), related_entity_type="preboarding_case", related_entity_id=case.id,
                         ctx={"summary": text, "link": f"/candidates/{application.id}" if application else "/onboarding"})
        except Exception:  # noqa: BLE001
            log.exception("internal exit email failed")
    return sorted(to)


def _manager_emails(db: Session, tenant, emp) -> list[str]:
    from app.core_hr import lifecycle
    from app.models.core_hr import Employee
    from app.models.user import User

    rec = lifecycle.get_current_employment(db, tenant, emp.id)
    out = []
    for mid in (getattr(rec, "manager_employee_id", None), getattr(rec, "hrbp_employee_id", None)):
        m = db.get(Employee, mid) if mid else None
        u = db.get(User, m.user_id) if m is not None and m.user_id else None
        if u is not None and u.email:
            out.append(u.email)
    return out


# ---------------------------------------------------------------- report

CATEGORY = {"withdraw_offer": "offer_dropout", "candidate_declined": "offer_dropout", "no_show": "no_show",
            "resigned": "early_leaver", "terminated": "early_leaver", "absconded": "absconding"}


def dropout_report(db: Session, tenant, *, since: Optional[date] = None, early_days: int = 90) -> dict:
    """Offer dropouts, no-shows, early leavers (left within `early_days` of joining) and absconding --
    counts by job, department, recruiter and reason. Built from each case's recorded outcome."""
    from app.models.user import User

    rows = []
    q = db.query(PreboardingCase).filter(PreboardingCase.tenant_id == tenant.tenant_id,
                                         PreboardingCase.status.in_(("revoked", "declined", "no_show", "exited")))
    for c in q.all():
        o = (c.attributes_json or {}).get("outcome") or {}
        kind = o.get("kind") or {"revoked": "withdraw_offer", "no_show": "no_show", "declined": "candidate_declined"}.get(c.status)
        if kind not in CATEGORY:
            continue
        at = o.get("at") or next((h.get("at") for h in reversed(c.history_json or []) if h.get("event") in (c.status, kind)), None)
        when = datetime.fromisoformat(at).date() if at else None
        if since and when and when < since:
            continue
        if kind in ("resigned", "terminated") and (o.get("days_after_joining") or 0) > early_days:
            continue
        application, _cand, job, _offer = _ctx(db, c)
        owner = db.get(User, job.created_by) if job is not None and job.created_by else None
        reason = o.get("reason") or next((h.get("reason") for h in reversed(c.history_json or []) if h.get("reason")), None) or "Not recorded"
        rows.append({"category": CATEGORY[kind], "kind": kind, "job": job.title if job else "-", "department": (job.department if job else None) or "-",
                     "recruiter": (owner.full_name or owner.email) if owner else "-", "reason": reason, "date": when.isoformat() if when else None,
                     "name": person_name(db, c), "application_id": str(application.id) if application else None,
                     "days_after_joining": o.get("days_after_joining")})

    def by(field):
        out: dict = {}
        for r in rows:
            out.setdefault(r[field], {"offer_dropout": 0, "no_show": 0, "early_leaver": 0, "absconding": 0, "total": 0})
            out[r[field]][r["category"]] += 1
            out[r[field]]["total"] += 1
        return [{"key": k, **v} for k, v in sorted(out.items(), key=lambda kv: -kv[1]["total"])]

    totals = {k: sum(1 for r in rows if r["category"] == k) for k in ("offer_dropout", "no_show", "early_leaver", "absconding")}
    return {"since": since.isoformat() if since else None, "early_days": early_days, "totals": totals,
            "by_job": by("job"), "by_department": by("department"), "by_recruiter": by("recruiter"), "by_reason": by("reason"),
            "rows": sorted(rows, key=lambda r: r["date"] or "", reverse=True)}
