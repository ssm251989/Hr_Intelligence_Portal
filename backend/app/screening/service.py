"""Comprehensive automatic screening -- Part A of the screening feature.

Extends the AI resume-matching call (app/ai_services/resume_matcher.match_resume) with
an equal-weighted composite score across five factors, and decides whether an
application should auto-advance to 'screened' based on the configurable dashboard
threshold (app/models/screening_settings.py). Used by:
  - The manual "Screen Candidate" button (app/screening/router.py screen_application).
  - Automatic screening right after a resume is parsed (app/candidates/router.py
    parse_and_apply_resume), for a candidate whose application(s) already have a job
    with a generated JD at that point (career portal apply, or a re-parse).
  - Automatic screening right after an application is created (app/candidates/
    applications_router.py create_application), for a candidate whose resume was already
    parsed before being linked to a job (manual upload, local import).
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.ai_services.resume_matcher import ResumeMatchError, match_resume
from app.audit.service import log_action
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.screening_settings import ScreeningSettings

FACTOR_COUNT = 5


def get_screening_settings(db: Session) -> ScreeningSettings:
    """The singleton settings row (id=1), seeded by migration e1f3a7c9b2d4. Defensively
    creates it if somehow missing (e.g. a test DB that ran migrations before this table
    existed) rather than crashing screening outright."""
    settings_row = db.get(ScreeningSettings, 1)
    if settings_row is None:
        settings_row = ScreeningSettings(id=1, dashboard_min_score=60, dashboard_max_score=100)
        db.add(settings_row)
        db.commit()
        db.refresh(settings_row)
    return settings_row


def composite_score(result: dict) -> float:
    """Equal-weighted average of the five screening factors -- skills (skill_match_pct),
    experience, location, certificates, and the existing Resume Matcher score
    (match_score). Pure function, no AI/DB access, so it's trivially unit-testable on its
    own regardless of how the five inputs were produced."""
    factors = [
        result["skill_match_pct"],
        result["experience_score"],
        result["location_score"],
        result["certificates_score"],
        result["match_score"],
    ]
    return sum(factors) / FACTOR_COUNT


def is_eligible_for_screening(application: Application) -> bool:
    """Automatic screening (unlike the manual button) must never touch an application
    that's already moved past the point screening matters -- only a fresh, untouched
    'received' application is eligible. Re-evaluation (Part D) uses this same check."""
    return application.status == "received"


def run_screening(db: Session, application: Application, job: JobRole, candidate: Candidate, actor: str) -> Application:
    """Runs the comprehensive screening call, logs the full breakdown to audit_log
    (always -- required, not optional, since nothing else reviews this), and auto-advances
    status to 'screened' when the composite score clears the configured minimum threshold.
    A score at or above the configured maximum gets identical treatment to a score within
    [min, max] -- there is no separate high-priority outcome, so only the minimum actually
    gates the decision.

    Raises ResumeMatchError on AI failure, after logging a failure audit entry -- the
    application is left completely untouched (no status change, no composite_score) so it
    stays in a safe, still-'received' state for a human or a later retry to pick up.
    Callers driving this automatically (as opposed to the manual button) should catch and
    swallow this exception; the manual endpoint lets it propagate into its existing 502.
    """
    thresholds = get_screening_settings(db)

    try:
        result = match_resume(job.jd_text, candidate.parsed_fields, candidate.location, job.location)
    except ResumeMatchError as exc:
        log_action(
            db, "application", application.id, "ai_screening_failed", actor,
            {"error": str(exc)},
        )
        raise

    score = composite_score(result)
    previous_status = application.status
    min_score = float(thresholds.dashboard_min_score)
    max_score = float(thresholds.dashboard_max_score)
    advance = score >= min_score
    new_status = "screened" if advance else previous_status

    log_action(
        db,
        "application",
        application.id,
        "ai_screening_scored",
        actor,
        {
            "skills_score": result["skill_match_pct"],
            "experience_score": result["experience_score"],
            "location_score": result["location_score"],
            "certificates_score": result["certificates_score"],
            "resume_matcher_score": result["match_score"],
            "composite_score": score,
            "missing_skills": result["missing_skills"],
            "recommendation": result["recommendation"],
            "threshold_min": min_score,
            "threshold_max": max_score,
            "previous_status": previous_status,
            "new_status": new_status,
            "advanced": advance,
        },
    )

    application.match_score = result["match_score"]
    application.skill_match_pct = result["skill_match_pct"]
    application.missing_skills = result["missing_skills"]
    application.composite_score = score
    application.status = new_status
    db.commit()
    db.refresh(application)
    return application


def attempt_auto_screen(db: Session, application: Application, actor: str = "system") -> Optional[Application]:
    """Best-effort automatic trigger for the two hook points (parse-resume completing,
    application creation) -- silently does nothing (returns None) if the application isn't
    eligible or the job/candidate aren't both ready yet, and swallows (logs, doesn't raise)
    any AI failure, since neither hook point may let screening's own problems break the
    upload/parse or application-creation flow that's calling it.
    """
    if not is_eligible_for_screening(application):
        return None
    job = db.get(JobRole, application.job_role_id)
    candidate = db.get(Candidate, application.candidate_id)
    if not job or not job.jd_text or not candidate or not candidate.parsed_fields:
        return None
    try:
        return run_screening(db, application, job, candidate, actor)
    except ResumeMatchError:
        return None
