"""Part 17.13 logic: talent pool re-matching, duplicate candidates, reminders, job health and
the candidate's own status page. Each piece only reads/creates -- nothing is deleted.

- talent_pool(job):  past candidates (not selected before, or last applied > 90 days ago, or
                     never applied) scored against this job with ITS scoring rules; the ones at/above
                     the shortlist threshold are "past candidates who match this job".
- find_duplicate():  same email, same phone (last 10 digits) or the same resume file (SHA-256).
- send_reminders():  pending approvals, missing interview scorecards, offers about to expire,
                     joiners with documents still pending -- each at most once a day, in-app,
                     all switchable and timed by `recruitment.reminders.*` settings.
- job_health():      open jobs with no applicants in 7 days, or candidates waiting longer than the
                     stage's time limit, with plain suggestions.
- status page:       a long-lived link per application; the candidate sees plain progress only.
"""

import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.application import TERMINAL_APPLICATION_STATUSES, Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.user import User
from app.candidates.names import given_name as _given  # fix 2026-10-05: first / preferred name, never the surname

STALE_DAYS = 90


def _setting(db: Session, tenant, key: str):
    from app.platform.settings.resolver import SettingContext, SettingsService

    return SettingsService(db).get(key, SettingContext(tenant=tenant))


# ---------------------------------------------------------------- talent pool

def talent_pool(db: Session, tenant, job: JobRole, *, limit: int = 50) -> dict:
    from types import SimpleNamespace

    from app.recruitment.scoring.engine import compute, gather, rules_for_job, threshold_for_job

    rules, _row, _src = rules_for_job(db, tenant, job)
    threshold, _ = threshold_for_job(db, tenant, job, rules)
    applied_here = {c for (c,) in db.query(Application.candidate_id).filter(Application.tenant_id == tenant.tenant_id, Application.job_role_id == job.id)}
    cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_DAYS)
    candidates = (db.query(Candidate).filter(Candidate.tenant_id == tenant.tenant_id, Candidate.parsed_fields.isnot(None))
                  .order_by(Candidate.created_at.desc()).limit(1000).all())
    open_elsewhere = {c for (c,) in db.query(Application.candidate_id).filter(
        Application.tenant_id == tenant.tenant_id, Application.status.notin_(TERMINAL_APPLICATION_STATUSES), Application.created_at >= cutoff)}
    out = []
    for cand in candidates:
        if cand.id in applied_here or cand.id in open_elsewhere or getattr(cand, "deleted_at", None):
            continue
        # the AI fit isn't known for this job yet -> that factor counts as neutral
        fake = SimpleNamespace(match_score=None, expected_salary=cand.expected_ctc, status="talent_pool")
        res = compute(gather(db, tenant, fake, job, cand), rules)
        out.append({"candidate_id": str(cand.id), "name": cand.full_name, "location": cand.location, "score": res["score"],
                    "knocked_out": res["knocked_out"], "years": (cand.parsed_fields or {}).get("total_experience_years"),
                    "last_seen": cand.created_at.isoformat() if cand.created_at else None})
    out.sort(key=lambda r: -r["score"])
    matches = [r for r in out if r["score"] >= threshold and not r["knocked_out"]]
    return {"job_id": str(job.id), "threshold": threshold, "checked": len(out), "matching": len(matches), "items": out[:limit]}


def add_from_talent_pool(db: Session, tenant, job: JobRole, candidate: Candidate, *, actor: str) -> Application:
    from app.recruitment.scoring.engine import score_application

    existing = db.query(Application).filter(Application.tenant_id == tenant.tenant_id, Application.job_role_id == job.id, Application.candidate_id == candidate.id).first()
    if existing is not None:
        return existing
    app = Application(tenant_id=tenant.tenant_id, job_role_id=job.id, candidate_id=candidate.id, status="screened", expected_salary=candidate.expected_ctc)
    db.add(app)
    db.commit()
    db.refresh(app)
    score_application(db, tenant, app, job=job, candidate=candidate)
    log_action(db, "application", app.id, "added_from_talent_pool", actor[:50], {"job_id": str(job.id), "candidate_id": str(candidate.id)})
    from app.models.intelligence import AgentSuggestion  # fix 2026-10-05: the "Position open again" to-do is done

    for todo in db.query(AgentSuggestion).filter(AgentSuggestion.tenant_id == tenant.tenant_id, AgentSuggestion.kind == "position_open_again",
                                                 AgentSuggestion.entity_id == job.id, AgentSuggestion.status == "pending").all():
        todo.status, todo.reviewed_by, todo.reviewed_at = "approved", actor[:200], datetime.now(timezone.utc)
    db.commit()
    return app


# ---------------------------------------------------------------- duplicates

def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _phone_key(phone: Optional[str]) -> Optional[str]:
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:] if len(digits) >= 10 else None


def find_duplicate(db: Session, tenant, *, email: Optional[str] = None, phone: Optional[str] = None, resume_sha256: Optional[str] = None,
                   exclude_id=None) -> tuple[Optional[Candidate], Optional[str]]:
    q = db.query(Candidate).filter(Candidate.tenant_id == tenant.tenant_id)
    if exclude_id is not None:
        q = q.filter(Candidate.id != exclude_id)
    if hasattr(Candidate, "deleted_at"):
        q = q.filter(Candidate.deleted_at.is_(None))
    if email:
        hit = q.filter(func.lower(Candidate.email) == email.strip().lower()).order_by(Candidate.created_at).first()
        if hit:
            return hit, "same email"
    if resume_sha256:
        hit = q.filter(Candidate.resume_sha256 == resume_sha256).order_by(Candidate.created_at).first()
        if hit:
            return hit, "same resume file"
    key = _phone_key(phone)
    if key:
        for c in q.filter(Candidate.phone.isnot(None)).filter(Candidate.phone.like(f"%{key[-4:]}%")).all():
            if _phone_key(c.phone) == key:
                return c, "same phone number"
    return None, None


def mark_if_duplicate(db: Session, tenant, candidate: Candidate, *, actor: str) -> Optional[dict]:
    """Links the candidate to an earlier record of the same person (never merges or deletes)."""
    if candidate.duplicate_of_id:
        return None
    other, reason = find_duplicate(db, tenant, email=candidate.email, phone=candidate.phone, resume_sha256=candidate.resume_sha256, exclude_id=candidate.id)
    if other is None or (other.created_at and candidate.created_at and other.created_at > candidate.created_at):
        return None
    candidate.duplicate_of_id = other.id
    db.commit()
    log_action(db, "candidate", candidate.id, "possible_duplicate", actor[:50], {"of": str(other.id), "reason": reason})
    return {"of": str(other.id), "name": other.full_name, "reason": reason}


# ---------------------------------------------------------------- reminders

def _already(db: Session, tenant, kind: str, ref) -> bool:
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return db.query(AuditLog.id).filter(AuditLog.tenant_id == tenant.tenant_id, AuditLog.action == "reminder_sent",
                                        AuditLog.entity_id == ref, AuditLog.created_at >= today,
                                        AuditLog.details["kind"].astext == kind).first() is not None


def _remind(db: Session, tenant, kind: str, ref, to: list[str], text: str, link: str, entity: str) -> bool:
    from app.models.comms import OutboundMessage

    to = sorted({t for t in to if t})
    if not to or _already(db, tenant, kind, ref):
        return False
    for addr in to:
        db.add(OutboundMessage(tenant_id=tenant.tenant_id, channel="in_app", purpose=f"reminder.{kind}", to_addresses=[addr], subject=text,
                               body_ref=link, status="sent", related_entity_type=entity, related_entity_id=ref))
    db.commit()
    log_action(db, entity, ref, "reminder_sent", "system", {"kind": kind, "to": to})
    return True


def _admins(db: Session, tenant) -> list[str]:
    return [u.email for u in db.query(User).filter(User.tenant_id == tenant.tenant_id, User.role == "admin").limit(5)]


def send_reminders(db: Session, tenant) -> dict:
    from app.models.interview import Interview
    from app.models.offer import Offer
    from app.models.onboarding import PreboardingCase
    from app.models.workflow import WorkflowStep

    if not _setting(db, tenant, "recruitment.reminders.enabled"):
        return {"skipped": "reminders are switched off"}
    now = datetime.now(timezone.utc)
    sent = {"approvals": 0, "scorecards": 0, "offers": 0, "documents": 0}

    hours = int(_setting(db, tenant, "recruitment.reminders.approval_hours") or 24)
    for step in db.query(WorkflowStep).filter(WorkflowStep.tenant_id == tenant.tenant_id, WorkflowStep.status == "pending",
                                              WorkflowStep.started_at < now - timedelta(hours=hours)).limit(200):
        u = db.get(User, step.assignee_user_id) if step.assignee_user_id else None
        if _remind(db, tenant, "approval", step.id, [u.email] if u else _admins(db, tenant),
                   f"An approval has been waiting for you for more than {hours} hours.", "/approvals", "workflow_step"):
            sent["approvals"] += 1

    # Part 20.4/20.5: Settings > Onboarding & employees > interviewers decides the hours (the older recruitment setting is the fallback)
    hours = int(_setting(db, tenant, "employees.interviewer.scorecard_reminder_hours") or _setting(db, tenant, "recruitment.reminders.scorecard_hours") or 24)
    for iv in db.query(Interview).filter(Interview.tenant_id == tenant.tenant_id, Interview.decision.is_(None), Interview.overall_rating.is_(None),
                                         Interview.scheduled_at < now - timedelta(hours=hours), Interview.scheduled_at > now - timedelta(days=30)).limit(200):
        if _remind(db, tenant, "scorecard", iv.id, [iv.interviewer_email], "Please give your interview feedback - the candidate is waiting for a decision.",
                   "/interviews/my", "interview"):
            sent["scorecards"] += 1

    days = int(_setting(db, tenant, "recruitment.reminders.offer_expiry_days") or 2)
    for offer, app, job in (db.query(Offer, Application, JobRole).join(Application, Application.id == Offer.application_id)
                            .join(JobRole, JobRole.id == Application.job_role_id)
                            .filter(Offer.tenant_id == tenant.tenant_id, or_(Offer.signed.is_(False), Offer.signed.is_(None)),
                                    Offer.expiry_date.isnot(None), Offer.expiry_date <= date.today() + timedelta(days=days), Offer.expiry_date >= date.today())
                            .limit(200)):
        owner = db.get(User, job.created_by) if job.created_by else None
        if _remind(db, tenant, "offer_expiry", offer.id, [owner.email] if owner else _admins(db, tenant),
                   f"An offer for {job.title} expires on {offer.expiry_date:%d %b} and isn't signed yet.", f"/candidates/{app.id}", "offer"):
            sent["offers"] += 1

    days = int(_setting(db, tenant, "recruitment.reminders.documents_days") or 3)
    for case in db.query(PreboardingCase).filter(PreboardingCase.tenant_id == tenant.tenant_id, PreboardingCase.status.in_(("invited", "in_progress")),
                                                 PreboardingCase.joining_date <= date.today() + timedelta(days=days), PreboardingCase.joining_date >= date.today()).limit(200):
        if _remind(db, tenant, "documents", case.id, _admins(db, tenant),
                   f"A joiner starting on {case.joining_date:%d %b} still has documents pending.", "/onboarding", "preboarding_case"):
            sent["documents"] += 1
    return sent


# ---------------------------------------------------------------- job health

def job_health(db: Session, tenant) -> dict:
    """Part 18.7: health of every live job, built for 100+ jobs -- a handful of grouped queries
    (not a few per job). Each job: level green / amber / red, issues with numbers (the page
    words them in the user's language), and tip codes. Plus summary counts for the chips."""
    from app.models.pipeline import PipelineStage, PipelineTemplate

    now = datetime.now(timezone.utc)
    week = now - timedelta(days=7)
    sla: dict = {}
    tpl = db.query(PipelineTemplate).filter(PipelineTemplate.tenant_id == tenant.tenant_id, PipelineTemplate.is_default.is_(True)).first()
    if tpl:
        sla = {s.code: s.sla_days for s in db.query(PipelineStage).filter(PipelineStage.template_id == tpl.id) if s.sla_days}
    jobs = db.query(JobRole).filter(JobRole.tenant_id == tenant.tenant_id, JobRole.status == "published").all()
    ids = [j.id for j in jobs]
    counts = {r[0]: r[1:] for r in db.query(
        Application.job_role_id, func.count(Application.id), func.count(Application.id).filter(Application.created_at >= week),
        func.max(Application.created_at), func.count(Application.id).filter(Application.status == "screened"),
    ).filter(Application.tenant_id == tenant.tenant_id, Application.job_role_id.in_(ids or [None])).group_by(Application.job_role_id)}
    slow: dict = {}
    for job_id, status, scored_at, created_at in db.query(Application.job_role_id, Application.status, Application.scored_at, Application.created_at).filter(
            Application.tenant_id == tenant.tenant_id, Application.job_role_id.in_(ids or [None]), Application.status.notin_(TERMINAL_APPLICATION_STATUSES)):
        limit, since = sla.get(status), scored_at or created_at
        if limit and since and (now - since).days > limit:
            over = (now - since).days - limit
            n, worst = slow.get(job_id, (0, 0))
            slow[job_id] = (n + 1, max(worst, over))
    out = []
    for job in jobs:
        total, recent, last_at, screened = counts.get(job.id, (0, 0, None, 0))
        age = (now - job.created_at).days if job.created_at else 0
        issues, tips = [], []
        if recent == 0 and age >= 7:
            quiet = (now - last_at).days if last_at else age
            issues.append({"kind": "no_applicants", "days": quiet, "count": 0})
            tips += ["share_again", "widen_location", "relax_skills"]
        n_slow, worst = slow.get(job.id, (0, 0))
        if n_slow:
            issues.append({"kind": "slow_stage", "days": worst, "count": n_slow})
            tips.append("decide_waiting")
        if total >= 10 and screened >= total * 0.8:
            issues.append({"kind": "low_scores", "days": 0, "count": screened})
            tips.append("check_scoring")
        level = "green" if not issues else "red" if len(issues) >= 2 or n_slow >= 5 or (issues[0]["kind"] == "no_applicants" and issues[0]["days"] >= 21) else "amber"
        out.append({"job_id": str(job.id), "title": job.title, "department": job.department, "location": job.location,
                    "applicants_7d": recent, "applicants_total": total, "age_days": age, "level": level, "healthy": not issues,
                    "issues": issues, "tips": list(dict.fromkeys(tips))})
    order = {"red": 0, "amber": 1, "green": 2}
    out.sort(key=lambda r: (order[r["level"]], -max([i["days"] for i in r["issues"]] or [0])))
    summary = {
        "jobs": len(out),
        "need_attention": sum(1 for r in out if r["level"] != "green"),
        "red": sum(1 for r in out if r["level"] == "red"),
        "no_applicants": sum(1 for r in out if any(i["kind"] == "no_applicants" for i in r["issues"])),
        "waiting_too_long": sum(i["count"] for r in out for i in r["issues"] if i["kind"] == "slow_stage"),
        "jobs_with_waiting": sum(1 for r in out if any(i["kind"] == "slow_stage" for i in r["issues"])),
        "low_scores": sum(1 for r in out if any(i["kind"] == "low_scores" for i in r["issues"])),
    }
    return {"summary": summary, "jobs": out, "checked_at": now.isoformat()}


# ---------------------------------------------------------------- candidate status page

STATUS_ACTION = "candidate_status_page"
_STEPS = ("applied", "reviewed", "shortlisted", "interview", "offer", "joined")
_STEP_OF = {"received": 0, "screened": 1, "hr_selected": 2, "on_hold": 2, "interview_scheduled": 3, "interview_selected": 3,
            "salary_ok": 3, "salary_above_band": 3, "salary_approved": 3, "bgv_requested": 3, "bgv_pending": 3, "bgv_cleared": 3,
            "offer_sent": 4, "onboarding_started": 5, "onboarding_completed": 5}


def status_link(db: Session, tenant, application: Application) -> str:
    from app.core.config import settings as app_settings
    from app.models.iam import ActionToken
    from app.platform.iam.action_tokens import create_action_token

    row = (db.query(ActionToken).filter(ActionToken.tenant_id == tenant.tenant_id, ActionToken.entity_type == "application",
                                        ActionToken.entity_id == application.id, ActionToken.action == STATUS_ACTION,
                                        ActionToken.invalidated_at.is_(None), ActionToken.expires_at > datetime.now(timezone.utc)).first())
    if row is None:
        row = create_action_token(db, tenant, entity_type="application", entity_id=application.id, action=STATUS_ACTION, created_by="system", ttl_days=365)
    return f"{app_settings.FRONTEND_URL.rstrip('/')}/status/{row.token}"


_CLOSED_AT = {"hr_rejected": 1, "interview_rejected": 3, "salary_rejected": 3, "bgv_rejected": 3}  # the step they reached


def status_view(db: Session, tenant, application: Application) -> dict:
    """Plain progress only -- never scores, notes or reasons."""
    cand = db.get(Candidate, application.candidate_id)
    job = db.get(JobRole, application.job_role_id)
    status = application.status or "received"
    closed = status in _CLOSED_AT
    current = _CLOSED_AT[status] if closed else _STEP_OF.get(status, 0)
    steps = []
    for i, key in enumerate(_STEPS):
        state = "done" if i < current else ("closed" if closed else "current") if i == current else "todo"
        steps.append({"key": key, "state": state})
    return {"first_name": _given(cand), "job_title": job.title if job else "",
            "steps": steps, "closed": closed, "applied_on": application.created_at.date().isoformat() if application.created_at else None}
