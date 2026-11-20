"""What happens when HR approves an agent's approval card (My approvals).

`agent_shortlist` (Screening agent): each candidate still waiting for a decision is
shortlisted exactly as the Shortlisting screen does it (same function), which also starts
interview scheduling and the salary step. Candidates whose status changed in the meantime
are skipped and listed on the card.
"""

from app.agents.service import applier


@applier("agent_shortlist")
def _apply_agent_shortlist(db, tenant, suggestion, payload, reviewer):
    from uuid import UUID

    from app.models.user import User
    from app.schemas.application import ShortlistDecisionRequest
    from app.shortlisting.router import make_shortlist_decision

    user = db.query(User).filter(User.email == reviewer).first()
    if user is None:
        raise PermissionError("reviewer not found")
    done, skipped = [], []
    for row in payload.get("candidates") or []:
        try:
            make_shortlist_decision(UUID(row["application_id"]),
                                    ShortlistDecisionRequest(decision="select", notes=f"Approved from the Screening agent's card. {payload.get('reason') or ''}".strip(),
                                                             decided_by=reviewer), db, user)
            done.append(row.get("name"))
        except Exception as exc:  # noqa: BLE001 -- one candidate's state must not block the others
            db.rollback()
            skipped.append({"name": row.get("name"), "why": getattr(exc, "detail", None) or str(exc)[:120]})
    payload["result"] = {"shortlisted": done, "skipped": skipped}


# ---------------------------------------------------------------- hiring-to-exit cards
# Each runs the same service function the screen uses. A ValueError from the service (state
# changed, budget short, vendor gone, ...) becomes an AgentError, so the card stays pending and
# HR sees the reason (400) instead of a server error.


def _service_call(db, fn):
    from app.agents.service import AgentError

    try:
        return fn()
    except ValueError as exc:
        db.rollback()
        raise AgentError(str(exc)) from exc


def _app(db, tenant, payload):
    from uuid import UUID

    from app.agents.service import AgentError
    from app.models.application import Application

    app = db.get(Application, UUID(payload["application_id"]))
    if app is None or app.tenant_id != tenant.tenant_id:
        raise AgentError("the candidate's application no longer exists")
    return app


def _result(payload, out):
    payload["result"] = {k: v for k, v in (out or {}).items() if isinstance(v, (str, int, float, bool, type(None)))}


@applier("agent_salary_decision")
def _apply_salary(db, tenant, suggestion, payload, reviewer):
    from app.recruitment import salary_auto

    app = _app(db, tenant, payload)
    amount = payload.get("amount")
    out = _service_call(db, lambda: salary_auto.decide(db, tenant, app, decision=payload["decision"], actor=reviewer,
                                                       amount=float(amount) if amount not in (None, "") else None, reason=payload.get("reason")))
    _result(payload, out)


@applier("agent_documents_approve")
def _apply_documents(db, tenant, suggestion, payload, reviewer):
    from app.recruitment import joining_docs

    app = _app(db, tenant, payload)
    _result(payload, _service_call(db, lambda: joining_docs.approve(db, tenant, app, actor=reviewer)))


@applier("agent_bgv_assign")
def _apply_bgv_assign(db, tenant, suggestion, payload, reviewer):
    from datetime import date
    from uuid import UUID

    from app.bgv import vendors
    from app.hr_agents.autopilot.hiring import check_names

    app = _app(db, tenant, payload)
    due = date.fromisoformat(payload["due_date"]) if payload.get("due_date") else None
    _result(payload, _service_call(db, lambda: vendors.assign(db, tenant, app, agency_id=UUID(payload["agency_id"]), checks=check_names(payload.get("checks")),
                                                               due_date=due, actor=reviewer)))


@applier("agent_bgv_decision")
def _apply_bgv_decision(db, tenant, suggestion, payload, reviewer):
    from app.recruitment import bgv_decision

    app = _app(db, tenant, payload)
    _result(payload, _service_call(db, lambda: bgv_decision.decide(db, tenant, app, decision=payload["decision"], actor=reviewer,
                                                                    note=payload.get("note"), reason=payload.get("reason"))))


@applier("agent_joining_dates")
def _apply_joining_dates(db, tenant, suggestion, payload, reviewer):
    from app.recruitment import joining_dates

    app = _app(db, tenant, payload)
    _result(payload, _service_call(db, lambda: joining_dates.propose(db, tenant, app, list(payload["dates"]), actor=reviewer, note=payload.get("note"))))


@applier("agent_mark_joined")
def _apply_mark_joined(db, tenant, suggestion, payload, reviewer):
    from uuid import UUID

    from app.agents.service import AgentError
    from app.models.onboarding import PreboardingCase
    from app.onboarding import joiner_actions

    case = db.get(PreboardingCase, UUID(payload["case_id"]))
    if case is None or case.tenant_id != tenant.tenant_id:
        raise AgentError("the joiner no longer exists")
    _result(payload, _service_call(db, lambda: joiner_actions.mark_joined(db, tenant, case, actor=reviewer)))


@applier("agent_exit_letters")
def _apply_exit_letters(db, tenant, suggestion, payload, reviewer):
    from uuid import UUID

    from app.agents.service import AgentError
    from app.employees import exit_checklist
    from app.models.service_desk import Separation

    s = db.get(Separation, UUID(payload["separation_id"]))
    if s is None or s.tenant_id != tenant.tenant_id:
        raise AgentError("the exit no longer exists")
    _result(payload, _service_call(db, lambda: exit_checklist.generate_letters(db, tenant, s, actor=reviewer)))


# ---------------------------------------------------------------- Part 29: agents run hiring to exit


@applier("agent_interview_send")
def _apply_interview_send(db, tenant, suggestion, payload, reviewer):
    """Same as [Send interview times now] on the candidate: interviewer first, then the candidate."""
    from app.agents.service import AgentError
    from app.interview_scheduling import automation
    from app.models.user import User

    app = _app(db, tenant, payload)
    user = db.query(User).filter(User.email == reviewer).first()
    out = automation.start(db, tenant, app, user, trigger="send_now", force=True)
    if out.get("outcome") not in ("started", "retrying"):
        raise AgentError(out.get("reason") or "the interview times could not be sent")
    _result(payload, out)


@applier("agent_resignation_approve")
def _apply_resignation(db, tenant, suggestion, payload, reviewer):
    """Same as approving the last working day on the Exits screen (clearance checklist starts)."""
    from datetime import date
    from uuid import UUID

    from app.agents.service import AgentError
    from app.models.service_desk import Separation
    from app.service_desk import separations

    s = db.get(Separation, UUID(payload["separation_id"]))
    if s is None or s.tenant_id != tenant.tenant_id:
        raise AgentError("the resignation no longer exists")
    try:
        lwd = date.fromisoformat(str(payload["last_working_day"]))
        waived, buyout = int(payload.get("waived_days") or 0), int(payload.get("buyout_days") or 0)
    except (KeyError, TypeError, ValueError) as exc:
        raise AgentError("last_working_day must be a date (YYYY-MM-DD); waived_days / buyout_days whole numbers") from exc
    row = _service_call(db, lambda: separations.approve_lwd(db, tenant, s, lwd=lwd, actor=reviewer, waived_days=waived, buyout_days=buyout))
    payload["result"] = {"status": row.status, "approved_lwd": row.approved_lwd.isoformat() if row.approved_lwd else None}


# ---------------------------------------------------------------- Part 30.1: Job agent


@applier("agent_job_publish")
def _apply_job_publish(db, tenant, suggestion, payload, reviewer):
    """Saves the JD (HR may have changed it in the card) and publishes with the Jobs screen's own Publish."""
    from uuid import UUID

    from fastapi import HTTPException

    from app.agents.service import AgentError
    from app.hr_agents.autopilot.jobs import missing_fields
    from app.jobs import router as jobs_router
    from app.models.job_role import JobRole
    from app.models.user import User
    from app.schemas.job import PublishPlatformsRequest

    job = db.get(JobRole, UUID(str(payload.get("job_id") or suggestion.entity_id)))
    if job is None or job.tenant_id != tenant.tenant_id or job.deleted_at is not None:
        raise AgentError("the job no longer exists")
    user = db.query(User).filter(User.email == reviewer).first()
    if user is None:
        raise PermissionError("reviewer not found")
    if user.role not in ("recruiter", "admin"):  # the Jobs screen's Publish is for recruiters and admins
        raise PermissionError("only a recruiter or an admin can publish a job")
    jd = (payload.get("jd_text") or "").strip() or (job.jd_text or "").strip()
    if not jd:
        raise AgentError("Write the JD first - in the card (Change and approve) or on the job - then approve again.")
    missing = missing_fields(db, tenant, job)
    if missing:
        raise AgentError("Fill before publishing: " + ", ".join(m["label"].lower() for m in missing) + ". Add it on the job, then approve again.")
    chosen = payload.get("platforms") or {}
    kept = job.publish_settings or {}  # the wizard's own choices (new-application emails, deadline) stay as they were
    request = PublishPlatformsRequest(career_portal=bool(chosen.get("career_portal")), linkedin=bool(chosen.get("linkedin")),
                                      naukri=bool(chosen.get("naukri")), email_notifications=bool(kept.get("email_notifications")),
                                      application_deadline=kept.get("application_deadline") or None)
    job.jd_text = jd
    try:
        jobs_router.publish_job_platforms(job.id, request, db, user)
    except HTTPException as exc:
        db.rollback()
        raise AgentError(str(exc.detail)) from exc
    payload["result"] = {"status": job.status}
