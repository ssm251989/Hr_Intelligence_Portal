"""Part 21.1: closed jobs go to the Recycle bin after N days (Settings > Hiring > Closed jobs).

- `recruitment.jobs.recycle_enabled` (on) + `recruitment.jobs.recycle_after_days` (30; 0 = at the next daily run).
- Daily (`closed_jobs_cleanup`): every job closed more than N days ago -> the job and its job-specific data go to the
  Recycle bin (soft delete, restorable, hidden everywhere by the global filter in app/recruitment/removal.py):
  applications (and through them screening scores, shortlist, interviews + scorecards, offers, documents), with their
  open links (interview negotiation, confirmation, salary / document forms) stopped.
  * People who were hired / are employees are never touched (their application stays with the job's history).
  * `recruitment.jobs.keep_candidates_in_pool` (on): the candidate profile + resume stay in the talent pool;
    off: a candidate with nothing else open goes to the bin too.
- 3 days before, the Jobs page shows "Will move to the Recycle bin on <date>" with [Keep this job] (pauses it).
- Recycle bin > Jobs: Restore (the job and exactly what moved with it) / Delete permanently. Binned jobs are deleted
  permanently after the recycle-bin time limit (`recruitment.candidates.recycle_days`), like candidates.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.recruitment.removal import INCLUDE_REMOVED, _cancel_pending

REASON = "job_cleanup"
WARN_DAYS = 3
PROTECTED_STATUSES = ("offer_sent", "onboarding_started", "onboarding_completed", "left_after_joining")


class CleanupError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _setting(db: Session, tenant, key: str):
    from app.platform.settings.resolver import SettingContext, SettingsService

    return SettingsService(db).get(key, SettingContext(tenant=tenant))


def _q(db: Session, model):
    return db.query(model).execution_options(**{INCLUDE_REMOVED: True})


def settings(db: Session, tenant) -> dict:
    days = _setting(db, tenant, "recruitment.jobs.recycle_after_days")
    return {"enabled": _setting(db, tenant, "recruitment.jobs.recycle_enabled") is not False,
            "days": max(0, int(days)) if days is not None else 30,
            "keep_in_pool": _setting(db, tenant, "recruitment.jobs.keep_candidates_in_pool") is not False,
            "bin_days": int(_setting(db, tenant, "recruitment.candidates.recycle_days") or 30)}


def closed_on(db: Session, job: JobRole) -> Optional[datetime]:
    """closed_at, else when an automatic close (deadline / positions filled) was logged."""
    if job.closed_at is not None:
        return job.closed_at
    row = (db.query(AuditLog).filter(AuditLog.entity_id == job.id, AuditLog.action.in_(("job_closed", "job_auto_closed_deadline_passed", "job_auto_closed_positions_filled")))
           .order_by(AuditLog.created_at.desc()).first())
    return row.created_at if row is not None else None


def moves_on(db: Session, tenant, job: JobRole, cfg: Optional[dict] = None) -> Optional[datetime]:
    cfg = cfg or settings(db, tenant)
    if not cfg["enabled"] or job.status != "closed" or job.deleted_at is not None or job.cleanup_paused_at is not None:
        return None
    closed = closed_on(db, job)
    return closed + timedelta(days=cfg["days"]) if closed is not None else None


def warning(db: Session, tenant, job: JobRole, cfg: Optional[dict] = None) -> Optional[dict]:
    """For the Jobs page: shown from WARN_DAYS before the move (or when it is due)."""
    when = moves_on(db, tenant, job, cfg)
    if when is None or when - _now() > timedelta(days=WARN_DAYS):
        return None
    return {"moves_on": when.isoformat()}


def _protected(db: Session, app: Application) -> bool:
    from app.models.core_hr import Employee
    from app.models.offer import Offer
    from app.models.onboarding import PreboardingCase

    if app.status in PROTECTED_STATUSES:
        return True
    if _q(db, Offer).filter(Offer.application_id == app.id, Offer.signed.is_(True)).first() is not None:
        return True
    if _q(db, PreboardingCase).filter(PreboardingCase.application_id == app.id, PreboardingCase.employee_id.isnot(None)).first() is not None:
        return True
    return db.query(Employee).filter(Employee.candidate_id == app.candidate_id).first() is not None


def move_to_bin(db: Session, tenant, job: JobRole, *, actor: str) -> dict:
    from app.recruitment import budgets

    if job.deleted_at is not None:
        return {"skipped": "already in the bin"}
    cfg = settings(db, tenant)
    now = _now()
    moved, kept, cands = 0, 0, 0
    for app in db.query(Application).filter(Application.job_role_id == job.id).all():  # not already removed
        if _protected(db, app):
            kept += 1
            continue
        cand = _q(db, Candidate).filter(Candidate.id == app.candidate_id).first()
        if cand is not None:
            _cancel_pending(db, tenant, cand, [app.id])
        budgets.release(db, tenant, app.id, reason=f"{(cand.full_name if cand else None) or 'A candidate'} - job closed ({job.title})")
        app.removed_at, app.removed_reason = now, REASON
        moved += 1
        if cand is not None and not cfg["keep_in_pool"] and cand.deleted_at is None:
            others = db.query(Application).filter(Application.candidate_id == cand.id, Application.id != app.id).count()
            if not others:
                cand.deleted_at, cand.deleted_by, cand.delete_reason, cand.delete_note = now, actor[:200], REASON, f"job {job.title} went to the Recycle bin"
                cands += 1
    job.deleted_at, job.deleted_by = now, actor[:200]
    db.commit()
    result = {"applications": moved, "kept_hired": kept, "candidates": cands, "kept_in_pool": cfg["keep_in_pool"]}
    log_action(db, "job_role", job.id, "job_moved_to_recycle_bin", actor[:50], {"title": job.title, **result})
    return result


def keep(db: Session, tenant, job: JobRole, *, actor: str) -> None:
    job.cleanup_paused_at, job.cleanup_paused_by = _now(), actor[:200]
    db.commit()
    log_action(db, "job_role", job.id, "job_cleanup_paused", actor[:50], {})


def restore(db: Session, tenant, job: JobRole, *, actor: str) -> dict:
    if job.deleted_at is None:
        raise CleanupError("This job isn't in the Recycle bin.")
    apps = _q(db, Application).filter(Application.job_role_id == job.id, Application.removed_reason == REASON).all()
    for a in apps:
        a.removed_at = a.removed_reason = None
        c = _q(db, Candidate).filter(Candidate.id == a.candidate_id).first()
        if c is not None and c.delete_reason == REASON:
            c.deleted_at = c.deleted_by = c.delete_reason = c.delete_note = None
    job.deleted_at = job.deleted_by = None
    job.cleanup_paused_at, job.cleanup_paused_by = _now(), actor[:200]  # restored -> don't move it again tomorrow
    db.commit()
    log_action(db, "job_role", job.id, "job_restored_from_recycle_bin", actor[:50], {"applications": len(apps)})
    return {"applications": len(apps)}


def delete_permanently(db: Session, tenant, job: JobRole, *, actor: str, confirm: str) -> dict:
    """The job, its binned applications and everything under them; candidates who went to the bin with it and have
    nothing else. Hired people's applications stay (their records belong to the employee)."""
    from app.recruitment.removal import _dependents

    if confirm != "DELETE":
        raise CleanupError('Type DELETE to confirm.')
    if job.deleted_at is None:
        raise CleanupError("Put the job in the Recycle bin first.")
    if _q(db, Application).filter(Application.job_role_id == job.id, Application.removed_reason.is_(None)).first() is not None:
        raise CleanupError("Someone hired through this job is still linked to it, so the job is kept (only its other data can go). "
                           "Restore it if you need it back.")
    app_ids = [a.id for a in _q(db, Application).filter(Application.job_role_id == job.id).all()]
    cand_ids = [a.candidate_id for a in _q(db, Application).filter(Application.job_role_id == job.id).all()]
    counts: dict[str, int] = {}
    for table, pk, rows in _dependents(db, "applications", app_ids, set()):
        db.execute(table.delete().where(pk.in_(rows)))
        counts[table.name] = counts.get(table.name, 0) + len(rows)
    db.query(Application).execution_options(**{INCLUDE_REMOVED: True}).filter(Application.id.in_(app_ids or [None])).delete(synchronize_session=False)
    gone = 0
    for cid in set(cand_ids):
        c = _q(db, Candidate).filter(Candidate.id == cid).first()
        if c is not None and c.delete_reason == REASON and _q(db, Application).filter(Application.candidate_id == cid).count() == 0:
            from app.recruitment.removal import delete_permanently as delete_candidate

            try:
                delete_candidate(db, tenant, c, reason="other", actor=actor, confirm="DELETE")
                gone += 1
            except Exception:  # noqa: BLE001 -- the candidate stays in the bin; listed there
                db.rollback()
    for table, pk, rows in _dependents(db, "job_roles", [job.id], set()):
        db.execute(table.delete().where(pk.in_(rows)))
    title = job.title
    db.delete(job)
    db.commit()
    log_action(db, "job_role", None, "job_deleted_permanently", actor[:50], {"title": title, "applications": len(app_ids), "candidates": gone, "rows": counts})
    return {"applications": len(app_ids), "candidates": gone}


def bin_list(db: Session, tenant) -> list[dict]:
    cfg = settings(db, tenant)
    out = []
    for j in _q(db, JobRole).filter(JobRole.tenant_id == tenant.tenant_id, JobRole.deleted_at.isnot(None)).order_by(JobRole.deleted_at.desc()).all():
        n = _q(db, Application).filter(Application.job_role_id == j.id, Application.removed_reason == REASON).count()
        out.append({"id": str(j.id), "title": j.title, "department": j.department, "closed_on": (closed_on(db, j) or j.deleted_at).isoformat(),
                    "moved_on": j.deleted_at.isoformat(), "by": j.deleted_by, "applications": n,
                    "deleted_permanently_on": (j.deleted_at + timedelta(days=cfg["bin_days"])).isoformat()})
    return out


def run_daily(db: Session, tenant) -> dict:
    cfg = settings(db, tenant)
    if not cfg["enabled"]:
        return {"enabled": False}
    now = _now()
    moved, totals = [], {"applications": 0, "candidates": 0, "kept_hired": 0}
    for job in db.query(JobRole).filter(JobRole.tenant_id == tenant.tenant_id, JobRole.status == "closed", JobRole.deleted_at.is_(None),
                                        JobRole.cleanup_paused_at.is_(None)).all():
        when = moves_on(db, tenant, job, cfg)
        if when is None or when > now:
            continue
        r = move_to_bin(db, tenant, job, actor=f"system (closed {cfg['days']}+ days)")
        moved.append(job.title)
        for k in totals:
            totals[k] += r.get(k, 0)
    purged = 0
    limit = now - timedelta(days=cfg["bin_days"])
    for job in _q(db, JobRole).filter(JobRole.tenant_id == tenant.tenant_id, JobRole.deleted_at.isnot(None), JobRole.deleted_at < limit).limit(50).all():
        try:
            delete_permanently(db, tenant, job, actor="system (recycle bin time limit)", confirm="DELETE")
            purged += 1
        except CleanupError:
            pass
    result = {"jobs_moved": moved, **totals, "purged": purged}
    if moved or purged:
        log_action(db, "job_role", None, "closed_jobs_cleanup_run", "system", result)
    return result
