import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.ai_services.candidate_ranker import CandidateRankingError, rank_candidate
from app.ai_services.resume_matcher import ResumeMatchError
from app.audit.service import log_action
from app.auth.dependencies import require_roles
from app.candidates.hold import assert_application_not_on_hold
from app.core.database import get_db
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.job_role import JobRole
from app.models.screening_settings import ScreeningSettings
from app.models.user import User
from app.schemas.application import ApplicationRead
from app.schemas.screening import ReEvaluateAllResult, ScreeningSettingsRead, ScreeningSettingsUpdate
from app.screening.service import get_screening_settings, re_evaluate_all, run_screening

router = APIRouter(prefix="/applications", tags=["screening"])

# Separate from `router` above (which is entirely "/applications/{id}/..." single-application
# actions) -- settings and the bulk Re-evaluate All action aren't about one application, so
# they get their own prefix rather than an odd-looking /applications/screening-settings.
settings_router = APIRouter(prefix="/screening", tags=["screening"])


def _get_application_or_404(db: Session, application_id: uuid.UUID) -> Application:
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


def _render_ranking_rationale(result: dict) -> str:
    sections = [
        result["rank_rationale"],
        "",
        "Strengths:",
        *[f"- {item}" for item in result["strengths"]],
        "",
        "Concerns:",
        *[f"- {item}" for item in result["concerns"]],
        "",
        f"Recommendation: {result['recommendation']}",
    ]
    return "\n".join(sections)


@router.post("/{application_id}/screen", response_model=ApplicationRead)
def screen_application(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin")),
):
    application = _get_application_or_404(db, application_id)
    assert_application_not_on_hold(application)
    job = db.get(JobRole, application.job_role_id)
    candidate = db.get(Candidate, application.candidate_id)

    if not job or not job.jd_text:
        raise HTTPException(status_code=400, detail="Job description not yet generated")
    if not candidate or not candidate.parsed_fields:
        raise HTTPException(status_code=400, detail="Candidate resume not yet parsed")

    try:
        return run_screening(db, application, job, candidate, current_user.email)
    except ResumeMatchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{application_id}/rank", response_model=ApplicationRead)
def rank_application(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin")),
):
    application = _get_application_or_404(db, application_id)
    assert_application_not_on_hold(application)
    job = db.get(JobRole, application.job_role_id)

    if application.match_score is None:
        raise HTTPException(status_code=400, detail="Application must be screened before ranking")
    if not job or not job.jd_text:
        raise HTTPException(status_code=400, detail="Job description not yet generated")

    match_data = {
        "match_score": application.match_score,
        "skill_match_pct": application.skill_match_pct,
        "missing_skills": application.missing_skills,
    }
    interviews = db.query(Interview).filter(Interview.application_id == application.id).all()
    interview_feedback = [
        {
            "technical_rating": interview.technical_rating,
            "communication_rating": interview.communication_rating,
            "overall_rating": interview.overall_rating,
            "comments": interview.comments,
            "decision": interview.decision,
        }
        for interview in interviews
    ] or None

    try:
        result = rank_candidate(job.jd_text, match_data, interview_feedback)
    except CandidateRankingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    ranking_score = float(result["composite_score"])

    log_action(
        db,
        "application",
        application.id,
        "ai_candidate_ranking_scored",
        "system",
        {**result, "composite_score": ranking_score},
    )
    application.ranking_score = ranking_score
    application.ranking_rationale = _render_ranking_rationale(result)
    db.commit()
    db.refresh(application)
    return application


@settings_router.get("/settings", response_model=ScreeningSettingsRead)
def get_settings(db: Session = Depends(get_db), current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin"))):
    return get_screening_settings(db)


@settings_router.put("/settings", response_model=ScreeningSettingsRead)
def update_settings(
    payload: ScreeningSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin")),
):
    """Saving here takes effect immediately for every screening call from this point
    forward -- new uploads (attempt_auto_screen), the manual Screen button, and Re-evaluate
    All all read this same singleton row fresh each time (get_screening_settings), never a
    value cached at some earlier point."""
    settings_row: ScreeningSettings = get_screening_settings(db)
    settings_row.dashboard_min_score = payload.dashboard_min_score
    settings_row.dashboard_max_score = payload.dashboard_max_score
    db.commit()
    db.refresh(settings_row)
    return settings_row


@settings_router.post("/re-evaluate-all", response_model=ReEvaluateAllResult)
def re_evaluate_all_applications(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin")),
):
    return re_evaluate_all(db, current_user.email)
