"""Part 17.12: interviews without Excel. The app is the only source of interviewers, their
emails and their availability. Same function names as the old Excel `tracker` module, so
negotiation.py / confirmation.py keep their flow; `path` arguments are accepted and ignored.

- eligible_interviewers_for_job(_path, job_title) -> names, from interviewer pools:
    pools for that job first, then pools whose skills match the job (title + skill lists),
    in each pool's member order, active pools only.
- email_for_interviewer(_path, name) -> the email behind that name.
- append/update_interview_log_row, sync_interviewer_pool_job_titles -> nothing to do: the
  app already stores every negotiation and interview.
"""

import re
from typing import Optional

from app.interview_scheduling.tracker import TrackerFileLockedError  # noqa: F401 -- kept for callers' except clauses

_NAME_TO_EMAIL: dict[tuple[str, str], str] = {}


def _session():
    from app.core.database import SessionLocal

    return SessionLocal()


def _words(text: Optional[str]) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9+#.]{2,}", (text or "").lower())}


def pool_members_for_job(db, tenant, job) -> list[tuple[str, str]]:
    """[(name, email)] in the order they are tried, no duplicates."""
    from app.models.interviewer_availability import InterviewerAvailability
    from app.models.interviewer_pool import InterviewerPool

    pools = db.query(InterviewerPool).filter(InterviewerPool.tenant_id == tenant.tenant_id, InterviewerPool.active.is_(True)).all()
    job_words = _words(job.title) | set().union(*(_words(s) for s in (job.technical_skills_must_have or []) + (job.technical_skills_good_to_have or [])))
    exact = [p for p in pools if p.job_role_id == job.id]
    by_skill = sorted((p for p in pools if p.job_role_id is None and any(_words(s) & job_words for s in (p.skills_json or []))),
                      key=lambda p: -len(set().union(*(_words(s) for s in p.skills_json or [])) & job_words))
    general = [p for p in pools if p.job_role_id is None and not p.skills_json]
    emails: list[str] = []
    for pool in exact + by_skill + general:
        for e in pool.member_emails_json or []:
            e = str(e).strip().lower()
            if e and e not in emails:
                emails.append(e)
    names = {r.interviewer_email: (r.interviewer_name or r.interviewer_email) for r in
             db.query(InterviewerAvailability).filter(InterviewerAvailability.tenant_id == tenant.tenant_id,
                                                     InterviewerAvailability.interviewer_email.in_(emails)).all()} if emails else {}
    return [(names.get(e, e), e) for e in emails]


def eligible_interviewers_for_job(_path, job_title: str, job=None) -> list[str]:
    from app.models.job_role import JobRole
    from app.platform.tenancy.context import require_current_tenant

    tenant = require_current_tenant()
    db = _session()
    try:
        if job is None:
            job = db.query(JobRole).filter(JobRole.tenant_id == tenant.tenant_id, JobRole.title == job_title).order_by(JobRole.created_at.desc()).first()
        if job is None:
            return []
        members = pool_members_for_job(db, tenant, job)
    finally:
        db.close()
    for name, email in members:
        _NAME_TO_EMAIL[(str(tenant.tenant_id), name.strip().lower())] = email
    return [name for name, _email in members]


def email_for_interviewer(_path, interviewer_name: str) -> Optional[str]:
    from app.models.interviewer_availability import InterviewerAvailability
    from app.platform.tenancy.context import require_current_tenant

    tenant = require_current_tenant()
    key = (str(tenant.tenant_id), (interviewer_name or "").strip().lower())
    if key in _NAME_TO_EMAIL:
        return _NAME_TO_EMAIL[key]
    if "@" in (interviewer_name or ""):
        return interviewer_name.strip().lower()
    db = _session()
    try:
        row = (db.query(InterviewerAvailability).filter(InterviewerAvailability.tenant_id == tenant.tenant_id)
               .filter(InterviewerAvailability.interviewer_name.ilike(interviewer_name.strip())).first())
        return row.interviewer_email if row else None
    finally:
        db.close()


def append_interview_log_row(_path, _values: dict) -> None:
    return None


def update_interview_log_row(*_args, **_kwargs) -> bool:
    return True


def sync_interviewer_pool_job_titles(_db, _path) -> dict:
    return {"synced": 0, "source": "app"}
