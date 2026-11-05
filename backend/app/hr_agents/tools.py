"""The tools each HR agent can use. A tool is a plain function `fn(ctx, **args) -> dict`.

Rules every tool follows:
- the asking user's permission is checked first (`_need`); no permission -> an error the
  agent reads back and explains, never an exception that breaks the conversation;
- results are small, plain dicts (ids as strings) the model can read;
- tools reuse the app's own services (screening, interview scheduling, JD drafting) so an
  agent does exactly what the screens do, with the same audit trail.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.user import User
from app.platform.tenancy.context import TenantContext


@dataclass
class AgentContext:
    db: Session
    tenant: TenantContext
    user: User
    conversation_id: Optional[UUID] = None
    suggestions: list = field(default_factory=list)  # approval cards created in this run
    links: list = field(default_factory=list)  # {"label", "path"} for the UI


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    fn: Callable[..., dict]
    permission: Optional[str] = None

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


class ToolDenied(Exception):
    pass


def _need(ctx: AgentContext, permission: Optional[str]) -> None:
    if not permission:
        return
    from app.platform.iam.authz import has_permission

    if not has_permission(ctx.db, ctx.tenant, ctx.user, permission):
        raise ToolDenied(permission)


def run_tool(ctx: AgentContext, tool: ToolSpec, args: dict) -> dict:
    try:
        _need(ctx, tool.permission)
        return tool.fn(ctx, **(args or {}))
    except ToolDenied as exc:
        return {"error": f"The person asking does not have permission '{exc}'. Tell them who can do this (an HR admin)."}
    except (ValueError, LookupError, TypeError) as exc:
        ctx.db.rollback()
        return {"error": str(exc)[:300]}


def _uuid(value: Any, what: str) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        raise ValueError(f"{what} must be an id from an earlier tool result, got {value!r}") from None


def _str_list(value: Any) -> Optional[list[str]]:
    if value is None:
        return None
    if isinstance(value, str):
        value = [v.strip() for v in value.split(",")]
    return [str(v).strip() for v in value if str(v).strip()] or None


# ------------------------------------------------------------------ Job agent


def list_jobs(ctx: AgentContext, status: Optional[str] = None, search: Optional[str] = None) -> dict:
    from sqlalchemy import func

    from app.models.application import Application
    from app.models.job_role import JobRole

    q = ctx.db.query(JobRole).filter(JobRole.tenant_id == ctx.tenant.tenant_id)
    if status:
        q = q.filter(JobRole.status == status)
    if search:
        q = q.filter(JobRole.title.ilike(f"%{search.strip()}%"))
    jobs = q.order_by(JobRole.created_at.desc()).limit(25).all()
    counts = dict(ctx.db.query(Application.job_role_id, func.count(Application.id))
                  .filter(Application.job_role_id.in_([j.id for j in jobs] or [None]), Application.removed_at.is_(None))
                  .group_by(Application.job_role_id).all()) if jobs else {}
    return {"jobs": [{"job_id": str(j.id), "title": j.title, "status": j.status, "department": j.department, "location": j.location,
                      "has_jd": bool(j.jd_text), "applications": int(counts.get(j.id, 0))} for j in jobs]}


def create_job_draft(ctx: AgentContext, title: str, department: Optional[str] = None, location: Optional[str] = None,
                     experience_min_years: Optional[float] = None, experience_max_years: Optional[float] = None,
                     must_have_skills: Any = None, good_to_have_skills: Any = None, key_responsibilities: Optional[str] = None,
                     positions_count: Optional[int] = None, salary_band_min: Optional[float] = None, salary_band_max: Optional[float] = None,
                     job_type: Optional[str] = None) -> dict:
    from app.audit.service import log_action
    from app.models.job_role import JobRole
    from app.schemas.job import JobRoleCreate

    data = JobRoleCreate(
        title=(title or "").strip(), department=department, location=location, experience_min_years=experience_min_years,
        experience_max_years=experience_max_years, technical_skills_must_have=_str_list(must_have_skills),
        technical_skills_good_to_have=_str_list(good_to_have_skills), key_responsibilities=key_responsibilities,
        positions_count=positions_count or 1, salary_band_min=salary_band_min, salary_band_max=salary_band_max,
        **({"job_type": job_type} if job_type else {}),
    ).model_dump()
    if not data["title"]:
        raise ValueError("a job title is required")
    data["created_by"] = ctx.user.id
    job = JobRole(**data)  # status = draft: nothing is published by an agent
    ctx.db.add(job)
    ctx.db.commit()
    ctx.db.refresh(job)
    log_action(ctx.db, "job_role", job.id, "job_role_created", ctx.user.email[:50], {"status": job.status, "by_agent": "job"})
    ctx.links.append({"label": job.title, "path": f"/jobs/{job.id}"})
    return {"job_id": str(job.id), "title": job.title, "status": job.status}


def draft_job_description(ctx: AgentContext, job_id: str) -> dict:
    """The same AI JD drafting as Jobs > Generate JD (counted on the job's AI cost)."""
    from app.ai_services.jd_generator import JDGenerationError, generate_jd
    from app.audit.service import log_action
    from app.jobs.router import _render_jd_text
    from app.models.job_role import JobRole
    from app.platform.ai.tracked import ai_subject

    job = ctx.db.get(JobRole, _uuid(job_id, "job_id"))
    if job is None or job.tenant_id != ctx.tenant.tenant_id:
        raise LookupError("job not found")
    if job.status == "on_hold":
        raise ValueError("the job is on hold; resume it before drafting the JD")
    fields = ("title", "department", "location", "experience_min_years", "experience_max_years", "technical_skills_must_have",
              "technical_skills_good_to_have", "soft_skills_must_have", "soft_skills_good_to_have", "key_responsibilities",
              "education_degree_level", "education_field", "preferred_certifications", "salary_band_min", "salary_band_max",
              "benefits", "additional_notes")
    try:
        with ai_subject("job", job.id):
            result = generate_jd({f: getattr(job, f, None) for f in fields})
    except JDGenerationError as exc:
        raise ValueError(f"JD drafting failed: {exc}") from exc
    log_action(ctx.db, "job_role", job.id, "ai_jd_generator_scored", ctx.user.email[:50], {**result, "by_agent": "job"})
    job.jd_text = _render_jd_text(result)
    if job.status == "draft":
        job.status = "ready_for_publishing"
    ctx.db.commit()
    return {"job_id": str(job.id), "status": job.status, "jd_preview": (job.jd_text or "")[:600],
            "next": "HR reviews the JD and publishes the job from Jobs (agents never publish)."}


# ------------------------------------------------------------------ Screening agent


def _job(ctx: AgentContext, job_id: str):
    from app.models.job_role import JobRole

    job = ctx.db.get(JobRole, _uuid(job_id, "job_id"))
    if job is None or job.tenant_id != ctx.tenant.tenant_id:
        raise LookupError("job not found")
    return job


def _app_row(app, cand) -> dict:
    return {"application_id": str(app.id), "candidate": getattr(cand, "full_name", None), "status": app.status,
            "score": float(app.composite_score) if app.composite_score is not None else None,
            "skill_match_pct": float(app.skill_match_pct) if app.skill_match_pct is not None else None,
            "missing_skills": (app.missing_skills or [])[:5]}


def list_applications(ctx: AgentContext, job_id: str, status: Optional[str] = None) -> dict:
    from app.models.application import Application
    from app.models.candidate import Candidate

    job = _job(ctx, job_id)
    q = (ctx.db.query(Application, Candidate).join(Candidate, Candidate.id == Application.candidate_id)
         .filter(Application.job_role_id == job.id, Application.removed_at.is_(None)))
    if status:
        q = q.filter(Application.status == status)
    rows = q.order_by(Application.composite_score.desc().nullslast(), Application.created_at.asc()).limit(50).all()
    return {"job": job.title, "applications": [_app_row(a, c) for a, c in rows]}


def screen_new_applications(ctx: AgentContext, job_id: str, limit: int = 20) -> dict:
    """Runs the app's own AI screening on applications that are still 'received'."""
    from app.models.application import Application
    from app.models.candidate import Candidate
    from app.screening.service import ResumeMatchError, is_eligible_for_screening, run_screening

    job = _job(ctx, job_id)
    if not job.jd_text:
        raise ValueError("the job has no JD yet; ask the Job agent to draft it first")
    pending = (ctx.db.query(Application).filter(Application.job_role_id == job.id, Application.status == "received",
                                                Application.removed_at.is_(None)).limit(max(1, min(int(limit), 50))).all())
    done, skipped, failed = [], [], []
    for app in pending:
        cand = ctx.db.get(Candidate, app.candidate_id)
        if not is_eligible_for_screening(app) or cand is None or not cand.parsed_fields:
            skipped.append(str(app.id))
            continue
        try:
            app = run_screening(ctx.db, app, job, cand, ctx.user.email)
            done.append(_app_row(app, cand))
        except ResumeMatchError as exc:
            failed.append({"application_id": str(app.id), "error": str(exc)[:120]})
    return {"job": job.title, "screened": done, "skipped_not_ready": skipped, "failed": failed}


def top_candidates(ctx: AgentContext, job_id: str, n: int = 5) -> dict:
    from app.models.application import Application
    from app.models.candidate import Candidate

    job = _job(ctx, job_id)
    rows = (ctx.db.query(Application, Candidate).join(Candidate, Candidate.id == Application.candidate_id)
            .filter(Application.job_role_id == job.id, Application.status == "screened", Application.removed_at.is_(None),
                    Application.composite_score.isnot(None))
            .order_by(Application.composite_score.desc()).limit(max(1, min(int(n), 20))).all())
    return {"job": job.title, "top": [_app_row(a, c) for a, c in rows]}


def propose_shortlist(ctx: AgentContext, job_id: str, application_ids: Any, reason: str = "") -> dict:
    """Never shortlists by itself: creates ONE approval card in My approvals for HR."""
    from app.agents.service import suggest
    from app.models.application import Application
    from app.models.candidate import Candidate

    job = _job(ctx, job_id)
    ids = [_uuid(i, "application_id") for i in (application_ids if isinstance(application_ids, list) else [application_ids])]
    rows = (ctx.db.query(Application, Candidate).join(Candidate, Candidate.id == Application.candidate_id)
            .filter(Application.id.in_(ids), Application.job_role_id == job.id).all())
    eligible = [(a, c) for a, c in rows if a.status == "screened"]
    if not eligible:
        raise ValueError("none of these applications is waiting for a shortlist decision (status 'screened')")
    # agent_suggestions.agent is limited by a DB check to the original agents; "recruiter" is the
    # hiring one, and the card names the team agent that proposed it (no migration needed)
    card = suggest(ctx.db, ctx.tenant, agent="recruiter", kind="agent_shortlist", title=f"Shortlist {len(eligible)} for {job.title} (Screening agent)",
                   payload={"by_agent": "screening", "job_id": str(job.id), "job": job.title, "reason": (reason or "")[:500],
                            "candidates": [{"application_id": str(a.id), "name": c.full_name,
                                            "score": float(a.composite_score) if a.composite_score is not None else None} for a, c in eligible]},
                   reviewer_permission="recruitment.shortlisting.edit", entity_type="job_role", entity_id=None)
    ctx.suggestions.append({"id": str(card.id), "title": card.title})
    return {"approval_card_id": str(card.id), "candidates": len(eligible),
            "next": "HR approves in My approvals; on approval each candidate is shortlisted and interview scheduling starts."}


# ------------------------------------------------------------------ Scheduling agent


def waiting_for_interview(ctx: AgentContext, job_id: Optional[str] = None) -> dict:
    from app.models.application import Application
    from app.models.candidate import Candidate
    from app.models.job_role import JobRole

    q = (ctx.db.query(Application, Candidate, JobRole).join(Candidate, Candidate.id == Application.candidate_id)
         .join(JobRole, JobRole.id == Application.job_role_id)
         .filter(Application.tenant_id == ctx.tenant.tenant_id, Application.status == "hr_selected", Application.removed_at.is_(None)))
    if job_id:
        q = q.filter(Application.job_role_id == _uuid(job_id, "job_id"))
    rows = q.order_by(Application.updated_at.asc()).limit(30).all()
    return {"waiting": [{"application_id": str(a.id), "candidate": c.full_name, "job": j.title} for a, c, j in rows]}


def scheduling_problems(ctx: AgentContext, job_id: Optional[str] = None) -> dict:
    from app.interview_scheduling import automation

    return {"problems": automation.problems(ctx.db, ctx.tenant, _uuid(job_id, "job_id") if job_id else None)[:20]}


def start_interview_scheduling(ctx: AgentContext, application_id: str) -> dict:
    """The same start as after a shortlist: emails the interviewer and candidate their slots.
    Only for an application HR has already shortlisted (status hr_selected)."""
    from app.interview_scheduling import automation
    from app.models.application import Application

    app = ctx.db.get(Application, _uuid(application_id, "application_id"))
    if app is None or app.tenant_id != ctx.tenant.tenant_id:
        raise LookupError("application not found")
    if app.status != "hr_selected":
        raise ValueError(f"scheduling starts only after HR shortlisted the candidate (status is '{app.status}')")
    result = automation.start(ctx.db, ctx.tenant, app, ctx.user, trigger="agent")
    return {"application_id": str(app.id), "result": {k: v for k, v in (result or {}).items() if isinstance(v, (str, int, float, bool, type(None)))}}


# ------------------------------------------------------------------ catalog

_JOB_ID = {"type": "string", "description": "job_id from list_jobs or create_job_draft"}

JOB_TOOLS = (
    ToolSpec("list_jobs", "List jobs (newest first) with status, whether a JD exists and the number of applications.",
             {"type": "object", "properties": {"status": {"type": "string", "enum": ["draft", "ready_for_publishing", "published", "closed", "on_hold"]},
                                               "search": {"type": "string", "description": "part of the title"}}}, list_jobs, "recruitment.job.view"),
    ToolSpec("create_job_draft", "Create a new job as a DRAFT from the details the person gave. Ask for nothing you can leave empty; never invent salary figures.",
             {"type": "object", "required": ["title"], "properties": {
                 "title": {"type": "string"}, "department": {"type": "string"}, "location": {"type": "string"},
                 "experience_min_years": {"type": "number"}, "experience_max_years": {"type": "number"},
                 "must_have_skills": {"type": "array", "items": {"type": "string"}}, "good_to_have_skills": {"type": "array", "items": {"type": "string"}},
                 "key_responsibilities": {"type": "string"}, "positions_count": {"type": "integer"},
                 "salary_band_min": {"type": "number"}, "salary_band_max": {"type": "number"},
                 "job_type": {"type": "string", "description": "e.g. Full-time"}}}, create_job_draft, "recruitment.job.create"),
    ToolSpec("draft_job_description", "Draft the job description with AI for a job (same as Generate JD on the Jobs screen). The job becomes ready for publishing; HR publishes.",
             {"type": "object", "required": ["job_id"], "properties": {"job_id": _JOB_ID}}, draft_job_description, "recruitment.job.edit"),
)

SCREENING_TOOLS = (
    ToolSpec("list_jobs", "List jobs to find a job_id.", {"type": "object", "properties": {"search": {"type": "string"}}}, list_jobs, "recruitment.job.view"),
    ToolSpec("list_applications", "List a job's applications with status and screening score.",
             {"type": "object", "required": ["job_id"], "properties": {"job_id": _JOB_ID, "status": {"type": "string"}}}, list_applications, "recruitment.screening.view"),
    ToolSpec("screen_new_applications", "Run AI screening on the job's applications that are not screened yet.",
             {"type": "object", "required": ["job_id"], "properties": {"job_id": _JOB_ID, "limit": {"type": "integer"}}}, screen_new_applications, "recruitment.screening.edit"),
    ToolSpec("top_candidates", "The best screened candidates for a job, by score, with missing skills.",
             {"type": "object", "required": ["job_id"], "properties": {"job_id": _JOB_ID, "n": {"type": "integer"}}}, top_candidates, "recruitment.screening.view"),
    ToolSpec("propose_shortlist", "Propose candidates for the shortlist. Creates ONE approval card for HR; nobody is shortlisted until HR approves.",
             {"type": "object", "required": ["job_id", "application_ids"], "properties": {
                 "job_id": _JOB_ID, "application_ids": {"type": "array", "items": {"type": "string"}},
                 "reason": {"type": "string", "description": "one or two sentences HR will read"}}}, propose_shortlist, "recruitment.screening.view"),
)

SCHEDULING_TOOLS = (
    ToolSpec("waiting_for_interview", "Shortlisted candidates who are waiting for an interview (optionally for one job).",
             {"type": "object", "properties": {"job_id": _JOB_ID}}, waiting_for_interview, "recruitment.interview.view"),
    ToolSpec("scheduling_problems", "Interview scheduling problems that need HR (no interviewer, mailbox failure, ...).",
             {"type": "object", "properties": {"job_id": _JOB_ID}}, scheduling_problems, "recruitment.interview.view"),
    ToolSpec("start_interview_scheduling", "Start interview scheduling for a candidate HR has already shortlisted (sends the slot emails).",
             {"type": "object", "required": ["application_id"], "properties": {"application_id": {"type": "string"}}},
             start_interview_scheduling, "recruitment.interview.edit"),
)
