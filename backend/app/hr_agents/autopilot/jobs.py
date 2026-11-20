"""Part 30.1: the Job agent (steps 1-2 of the flow: a new job -> its JD -> published).

A new job (audit event job_role_created) wakes the agent. When the job has no JD and the company allows the AI,
the agent drafts one (the same drafting as the HR assistant's JD draft, feature agents.job, metered and masked).
Then it raises the card "Publish <title>" with the JD, the publishing choices and the fields still missing.
Approving the card (approvals.py, agent_job_publish) saves the JD - HR may change it in the card - and publishes
through the same function the Jobs screen's Publish uses. The agent never publishes a job on its own.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.hr_agents.autopilot.core import Run, card, enabled, record, state_get, state_set, waiting_card

log = logging.getLogger(__name__)

KIND = "agent_job_publish"
WAITING = "job.waiting"  # autopilot_state: {job_id: when it was created} -- new jobs waiting for HR to stop editing
QUIET = timedelta(minutes=10)  # no save for this long = HR has left the job as it is
GIVE_UP = timedelta(days=7)  # a job still being edited after a week is left alone
PERMISSION = "recruitment.job.edit"
# a job in these states is not published yet; "ready_for_publishing" was saved without the careers page on purpose
NOT_PUBLISHED = ("draft",)
# field -> (what HR reads on the card, blocks publishing?). Proof 30.1g: no screen can set a job's hiring manager
# (the wizard does not send it, PATCH /jobs ignores it), so it is a reminder only -- the job owner stands in for it.
FIELDS = {
    "salary_band": ("Salary band", True),
    "hiring_manager": ("Hiring manager", False),
    "interviewer_pool": ("Interviewer pool", True),
}


def missing_fields(db: Session, tenant, job) -> list[dict]:
    """What the job still needs before it can be published, in a fixed order."""
    from app.interview_scheduling.roster import pool_members_for_job
    from app.models.hiring_team import JobHiringTeamMember

    out = []
    if job.salary_band_min is None and job.salary_band_max is None:
        out.append("salary_band")
    if job.hiring_manager_id is None and not (
            db.query(JobHiringTeamMember.id).filter(JobHiringTeamMember.tenant_id == tenant.tenant_id, JobHiringTeamMember.job_role_id == job.id,
                                                    JobHiringTeamMember.role_in_hiring == "hiring_manager").first()):
        out.append("hiring_manager")
    if not pool_members_for_job(db, tenant, job):
        out.append("interviewer_pool")
    return [{"field": f, "label": FIELDS[f][0], "blocking": FIELDS[f][1]} for f in out]


def platforms_of(job) -> dict:
    """The publishing choices the job already has; a job that chose nothing goes on the careers page."""
    chosen = {k: bool(v) for k, v in (job.published_platforms or {}).items() if k in ("career_portal", "linkedin", "naukri")}
    if not any(chosen.values()):
        chosen = {"career_portal": True, "linkedin": False, "naukri": False}
    return {"career_portal": False, "linkedin": False, "naukri": False, **chosen}


def _draft(db: Session, tenant, job) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """(jd_text, decision_log_id, why_not) -- never raises: no draft is still a useful card."""
    from app.agents.service import draft_jd_text, job_inputs
    from app.platform.ai import governance

    if not governance.feature_enabled(db, tenant, "agents.job"):
        return None, None, "AI is not switched on for the Job agent"
    try:
        text, log_id = draft_jd_text(db, tenant, job_inputs(job), feature="agents.job", input_refs={"job_role_id": str(job.id)})
    except Exception as exc:  # noqa: BLE001 -- budget, provider or network: HR writes the JD instead
        log.warning("job agent: JD draft failed for %s: %s", job.id, exc)
        db.rollback()
        return None, None, f"the JD could not be drafted ({type(exc).__name__})"
    return (text or "").strip() or None, str(log_id) if log_id else None, None


def job_created(db: Session, tenant, job, run: Run):
    """job_role_created -> the job waits until HR stops editing it (proof 30.1g: the Jobs wizard saves the job at its
    first step, title only, and fills skills, salary and JD in the next steps; drafting then would waste an AI call on
    a title and raise a card while HR is still in the wizard). The per-minute run prepares the card once it is quiet."""
    if job is None or not enabled(db, tenant, "job", "jobs") or job.status not in NOT_PUBLISHED:
        return None
    waiting = dict(state_get(db, tenant, WAITING, {}) or {})
    waiting[str(job.id)] = datetime.now(timezone.utc).isoformat()
    state_set(db, tenant, WAITING, waiting)
    return None


def last_change(db: Session, tenant, job) -> Optional[datetime]:
    """When the job was last created / saved (its newest audit row)."""
    from sqlalchemy import func

    from app.models.audit_log import AuditLog

    return db.query(func.max(AuditLog.created_at)).filter(AuditLog.tenant_id == tenant.tenant_id, AuditLog.entity_type == "job_role",
                                                          AuditLog.entity_id == job.id).scalar()


def prepare_quiet_jobs(db: Session, tenant, run: Run, now: Optional[datetime] = None) -> int:
    """Every minute: each waiting job unchanged for QUIET gets its "Publish <title>" card (drafts only; a job published,
    deleted or moved on meanwhile simply leaves the list). Returns the cards made."""
    from uuid import UUID

    from app.models.job_role import JobRole

    waiting = dict(state_get(db, tenant, WAITING, {}) or {})
    if not waiting:
        return 0
    now = now or datetime.now(timezone.utc)
    made, keep = 0, {}
    for job_id, since in waiting.items():
        job = db.get(JobRole, UUID(job_id))
        if job is None or job.tenant_id != tenant.tenant_id or job.deleted_at is not None or job.status not in NOT_PUBLISHED:
            continue
        if now - datetime.fromisoformat(since) > GIVE_UP:
            continue
        changed = last_change(db, tenant, job)
        if changed is not None and now - changed < QUIET:
            keep[job_id] = since  # HR is still editing it
            continue
        try:
            if prepare_publish(db, tenant, job, run) is not None:
                made += 1
        except Exception as exc:  # noqa: BLE001 -- one job never blocks the others; it is not retried (no AI loop)
            log.exception("job agent: prepare_publish failed for %s", job_id)
            db.rollback()
            record(db, tenant, run, agent="job", action="prepare_publish", outcome="failed", entity_type="job_role", entity_id=job.id,
                   summary=f"prepare_publish failed: {type(exc).__name__}: {exc}"[:500])
    state_set(db, tenant, WAITING, keep)
    return made


def prepare_publish(db: Session, tenant, job, run: Run):
    """job_role_created -> the "Publish <title>" card (None when there is nothing to do)."""
    if job is None or not enabled(db, tenant, "job", "jobs"):
        return None
    if job.status not in NOT_PUBLISHED or job.deleted_at is not None:
        return None  # published (or saved for the job boards only) by the person who made it
    if waiting_card(db, tenant, KIND, job.id):
        return None
    drafted, log_id, why_not = (None, None, None)
    if not (job.jd_text or "").strip():
        drafted, log_id, why_not = _draft(db, tenant, job)
    missing = missing_fields(db, tenant, job)
    payload = {"job_id": str(job.id), "title": job.title, "jd_text": (job.jd_text or "").strip() or drafted, "jd_drafted": drafted is not None,
               "platforms": platforms_of(job), "missing": missing}
    if why_not:
        payload["jd_note"] = why_not
    c = card(db, tenant, kind=KIND, by_agent="job", title=f"Publish {job.title}", payload=payload, permission=PERMISSION,
             entity_type="job_role", entity_id=job.id)
    if log_id:
        from uuid import UUID

        c.decision_log_id = UUID(log_id)
        db.commit()
    bits = ["drafted the JD" if drafted else ("the job has its JD" if (job.jd_text or "").strip() else "no JD yet")]
    if any(m["blocking"] for m in missing):
        bits.append("fill before publishing: " + ", ".join(m["label"].lower() for m in missing if m["blocking"]))
    if any(not m["blocking"] for m in missing):
        bits.append("not set: " + ", ".join(m["label"].lower() for m in missing if not m["blocking"]))
    record(db, tenant, run, agent="job", action="propose_publish", outcome="proposed", entity_type="job_role", entity_id=job.id,
           summary=f"Prepared \"Publish {job.title}\" for HR ({'; '.join(bits)}).", details={"card_id": str(c.id), "missing": [m["field"] for m in missing]})
    return c
