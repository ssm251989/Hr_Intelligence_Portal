"""Part 30.1: the Job agent (steps 1-2 of the flow: a new job -> its JD -> published).

A new job (audit event job_role_created) wakes the agent. When the job has no JD and the company allows the AI,
the agent drafts one (the same drafting as the HR assistant's JD draft, feature agents.job, metered and masked).
Then it raises the card "Publish <title>" with the JD, the publishing choices and the fields still missing.
Approving the card (approvals.py, agent_job_publish) saves the JD - HR may change it in the card - and publishes
through the same function the Jobs screen's Publish uses. The agent never publishes a job on its own.
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.hr_agents.autopilot.core import Run, card, enabled, record, waiting_card

log = logging.getLogger(__name__)

KIND = "agent_job_publish"
PERMISSION = "recruitment.job.edit"
# a job in these states is not published yet; "ready_for_publishing" was saved without the careers page on purpose
NOT_PUBLISHED = ("draft",)
# field -> what HR reads on the card ("fill before publishing")
FIELDS = {
    "salary_band": "Salary band",
    "hiring_manager": "Hiring manager",
    "interviewer_pool": "Interviewer pool",
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
    return [{"field": f, "label": FIELDS[f]} for f in out]


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
    if missing:
        bits.append("fill before publishing: " + ", ".join(m["label"].lower() for m in missing))
    record(db, tenant, run, agent="job", action="propose_publish", outcome="proposed", entity_type="job_role", entity_id=job.id,
           summary=f"Prepared \"Publish {job.title}\" for HR ({'; '.join(bits)}).", details={"card_id": str(c.id), "missing": [m["field"] for m in missing]})
    return c
