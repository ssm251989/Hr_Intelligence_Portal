"""Part 21.2: when a person's exit is completed, their HIRING data goes to the Recycle bin.

Settings > Onboarding & employees > After exit:
  `employees.after_exit.move_hiring_data` (on), `employees.after_exit.days` (0 = straight away; else the daily job),
  `employees.after_exit.categories` (all on by default):
    - candidate_profile          the candidate record (+ resume, payslips from the salary form)
    - applications_interviews    applications, screening results / AI scores, shortlist, interviews + scorecards
    - links_forms                interview negotiation / confirmation links, salary / document form links (stopped)
    - inbox_emails               candidate emails in the HR inbox
    - portal_access              the pre-joining welcome portal (link stopped)
KEPT (never moved): the employee record, the signed offer letter, joining documents, BGV result, relieving /
experience letters, the exit record + exit interview, the audit log -- HR / legal records (Settings > Data & privacy >
Retention decides how long).

The bin: the candidate shows in Recycle bin > Candidates with reason "exit" and can be restored. After the bin's time
limit only the hiring-only rows are deleted for good (interviews, screening results, links, inbox emails, resume,
payslips); the candidate / application / offer rows behind the KEPT records stay, hidden.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.core_hr import Employee
from app.models.service_desk import Separation
from app.recruitment.removal import INCLUDE_REMOVED

REASON = "exit"
DONE_ACTION = "hiring_data_moved_on_exit"
CATEGORIES = ("candidate_profile", "applications_interviews", "links_forms", "inbox_emails", "portal_access")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _setting(db: Session, tenant, key: str):
    from app.platform.settings.resolver import SettingContext, SettingsService

    return SettingsService(db).get(key, SettingContext(tenant=tenant))


def _q(db: Session, model):
    return db.query(model).execution_options(**{INCLUDE_REMOVED: True})


def settings(db: Session, tenant) -> dict:
    cats = _setting(db, tenant, "employees.after_exit.categories")
    return {"enabled": _setting(db, tenant, "employees.after_exit.move_hiring_data") is not False,
            "days": max(0, int(_setting(db, tenant, "employees.after_exit.days") or 0)),
            "categories": [c for c in (cats if isinstance(cats, list) else CATEGORIES) if c in CATEGORIES]}


def _already(db: Session, s: Separation) -> bool:
    from app.models.audit_log import AuditLog

    return db.query(AuditLog).filter(AuditLog.entity_id == s.id, AuditLog.action == DONE_ACTION).first() is not None


def move(db: Session, tenant, s: Separation, *, actor: str) -> dict:
    """Idempotent. Moves the chosen categories of this person's hiring data to the bin."""
    from app.models.hr_inbound_email import HrInboundEmail
    from app.models.onboarding import PreboardingCase
    from app.recruitment.removal import _cancel_pending

    cfg = settings(db, tenant)
    if _already(db, s):
        return {"skipped": "already moved"}
    e = db.get(Employee, s.employee_id)
    cand = _q(db, Candidate).filter(Candidate.id == e.candidate_id).first() if e is not None and e.candidate_id else None
    if cand is None:
        log_action(db, "separation", s.id, DONE_ACTION, actor[:50], {"note": "no hiring record linked to this employee"})
        return {"moved": {}, "note": "no hiring record"}
    now = _now()
    apps = _q(db, Application).filter(Application.candidate_id == cand.id).all()
    moved: dict[str, int] = {}
    if "links_forms" in cfg["categories"]:
        moved.update({k: v for k, v in _cancel_pending(db, tenant, cand, [a.id for a in apps]).items() if v})
    if "applications_interviews" in cfg["categories"]:
        for a in apps:
            if a.removed_at is None:
                a.removed_at, a.removed_reason = now, REASON
                moved["applications"] = moved.get("applications", 0) + 1
    if "candidate_profile" in cfg["categories"] and cand.deleted_at is None:
        cand.deleted_at, cand.deleted_by, cand.delete_reason = now, actor[:200], REASON
        cand.delete_note = f"Hiring data moved to the Recycle bin on exit ({now.date().strftime('%d %b %Y')})"
        moved["candidate"] = 1
    if "inbox_emails" in cfg["categories"]:
        # hidden with the candidate (global filter in removal.py); deleted for good with the hiring data
        moved["inbox_emails"] = db.query(HrInboundEmail).filter(HrInboundEmail.matched_candidate_id == cand.id).count()
    if "portal_access" in cfg["categories"]:
        for case in _q(db, PreboardingCase).filter(PreboardingCase.candidate_id == cand.id).all():
            if case.portal_token_expires_at is None or case.portal_token_expires_at > now:
                case.portal_token_expires_at = now
                moved["portal_links"] = moved.get("portal_links", 0) + 1
    db.commit()
    log_action(db, "separation", s.id, DONE_ACTION, actor[:50], {"candidate_id": str(cand.id), "moved": moved, "categories": cfg["categories"]})
    log_action(db, "candidate", cand.id, DONE_ACTION, actor[:50], {"note": f"Hiring data moved to Recycle bin on exit ({now.date().isoformat()})", "moved": moved})
    return {"moved": moved, "candidate_id": str(cand.id)}


def on_exit_completed(db: Session, tenant, s: Separation, *, actor: str) -> Optional[dict]:
    cfg = settings(db, tenant)
    if not cfg["enabled"] or cfg["days"] > 0:
        return None  # the daily job does it after N days
    return move(db, tenant, s, actor="system (exit completed)")


def purge_hiring_data(db: Session, tenant, cand: Candidate, *, actor: str) -> dict:
    """After the bin's time limit: delete only the hiring-only rows; the rows behind KEPT records stay (hidden)."""
    from app.candidates.storage import resolve_resume_path
    from app.models.hr_inbound_email import HrInboundEmail
    from app.models.iam import ActionToken
    from app.models.interview import Interview
    from app.models.interview_confirmation_token import InterviewConfirmationToken
    from app.models.jd_screening import JdScreeningResult
    from app.models.negotiation_token import NegotiationToken
    from app.recruitment.removal import _dependents

    app_ids = [a.id for a in _q(db, Application).filter(Application.candidate_id == cand.id).all()]
    counts: dict[str, int] = {}
    iv_ids = [i.id for i in _q(db, Interview).filter(Interview.application_id.in_(app_ids or [None])).all()]
    for table, pk, rows in _dependents(db, "interviews", iv_ids, set()):
        db.execute(table.delete().where(pk.in_(rows)))
    for model, col, ids in ((Interview, Interview.id, iv_ids), (NegotiationToken, NegotiationToken.application_id, app_ids),
                            (InterviewConfirmationToken, InterviewConfirmationToken.application_id, app_ids),
                            (JdScreeningResult, JdScreeningResult.candidate_id, [cand.id]), (HrInboundEmail, HrInboundEmail.matched_candidate_id, [cand.id])):
        if ids:
            n = db.query(model).execution_options(**{INCLUDE_REMOVED: True}).filter(col.in_(ids)).delete(synchronize_session=False)
            counts[model.__tablename__] = n
    counts["action_tokens"] = db.query(ActionToken).filter(ActionToken.entity_type == "application", ActionToken.entity_id.in_(app_ids or [None])).delete(synchronize_session=False)
    if cand.resume_path:
        try:
            p = resolve_resume_path(cand.resume_path)
            if p.exists():
                p.unlink()
        except Exception:  # noqa: BLE001
            pass
        cand.resume_path = None
    cf = dict(cand.custom_fields or {})
    cf.pop("payslips", None)
    cf["hiring_data_purged_at"] = _now().isoformat()
    cand.custom_fields = cf
    db.commit()
    log_action(db, "candidate", cand.id, "hiring_data_deleted_permanently", actor[:50], counts)
    return counts


def run_daily(db: Session, tenant) -> dict:
    """Exits completed N days ago -> move; binned exit data past the bin's time limit -> delete the hiring-only rows."""
    cfg = settings(db, tenant)
    moved = purged = 0
    if cfg["enabled"]:
        cutoff = _now() - timedelta(days=cfg["days"])
        for s in db.query(Separation).filter(Separation.tenant_id == tenant.tenant_id, Separation.status == "completed",
                                             Separation.completed_at.isnot(None), Separation.completed_at <= cutoff).all():
            if not _already(db, s):
                move(db, tenant, s, actor=f"system ({cfg['days']} days after exit)")
                moved += 1
    bin_days = int(_setting(db, tenant, "recruitment.candidates.recycle_days") or 30)
    limit = _now() - timedelta(days=bin_days)
    for cand in _q(db, Candidate).filter(Candidate.tenant_id == tenant.tenant_id, Candidate.delete_reason == REASON, Candidate.deleted_at < limit).limit(100).all():
        if not (cand.custom_fields or {}).get("hiring_data_purged_at"):
            purge_hiring_data(db, tenant, cand, actor="system (recycle bin time limit)")
            purged += 1
    return {"moved": moved, "purged": purged}
