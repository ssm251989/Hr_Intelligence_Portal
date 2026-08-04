import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.ai_services.candidate_ranker import rank_candidate
from app.ai_services.resume_matcher import match_resume
from app.audit.service import log_action
from app.core.database import get_db
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.job_role import JobRole
from app.schemas.application import ApplicationRead

router = APIRouter(prefix="/applications", tags=["screening"])


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
def screen_application(application_id: uuid.UUID, db: Session = Depends(get_db)):
    application = _get_application_or_404(db, application_id)
    job = db.get(JobRole, application.job_role_id)
    candidate = db.get(Candidate, application.candidate_id)

    if not job or not job.jd_text:
        raise HTTPException(status_code=400, detail="Job description not yet generated")
    if not candidate or not candidate.parsed_fields:
        raise HTTPException(status_code=400, detail="Candidate resume not yet parsed")

    result = match_resume(job.jd_text, candidate.parsed_fields)

    log_action(db, "application", application.id, "ai_resume_matcher_scored", "system", result)
    application.match_score = result["match_score"]
    application.skill_match_pct = result["skill_match_pct"]
    application.missing_skills = result["missing_skills"]
    application.status = "screened"
    db.commit()
    db.refresh(application)
    return application


@router.post("/{application_id}/rank", response_model=ApplicationRead)
def rank_application(application_id: uuid.UUID, db: Session = Depends(get_db)):
    application = _get_application_or_404(db, application_id)
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

    result = rank_candidate(job.jd_text, match_data, interview_feedback)
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
