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

# The two actions run_screening ever logs (see run_screening below) -- the complete set of
# audit_log rows the Candidates List's Remarks column (Part C) needs to look at. Any other
# action on an application (shortlisting, salary, BGV, offers, ranking, ...) is out of
# scope for Remarks, which is specifically "what did screening conclude about this
# application," not a general activity feed.
SCREENING_REMARKS_ACTIONS = ("ai_screening_scored", "ai_screening_failed")

_RECOMMENDATION_LABELS = {
    "strong_fit": "Strong fit",
    "possible_fit": "Possible fit",
    "weak_fit": "Weak fit",
}


def describe_screening_audit_entry(action: str, details: dict) -> str:
    """Turns one ai_screening_scored/ai_screening_failed audit_log entry -- the exact
    breakdown run_screening already writes below -- into the Candidates List's
    human-readable Remarks text. Pure function, no AI/DB access: Remarks is only ever a
    different rendering of that same audit trail, never a separately maintained string
    that could drift out of sync with what screening actually concluded.
    """
    if action == "ai_screening_failed":
        return f"AI screening failed: {details.get('error') or 'unknown error'}"

    recommendation = _RECOMMENDATION_LABELS.get(details.get("recommendation"), "Screened")
    composite = details.get("composite_score")
    score_text = f" (score {round(composite)})" if composite is not None else ""
    missing_skills = details.get("missing_skills") or []
    if missing_skills:
        return f"{recommendation}{score_text} -- missing {', '.join(missing_skills)}"
    return f"{recommendation}{score_text}"


def describe_interview_readiness(action: str, details: dict) -> str:
    """Part F: the Screening List's Remarks column -- a different rendering of the exact
    same ai_screening_scored/ai_screening_failed audit_log entry describe_screening_audit_
    entry above renders for the Candidates List, but describing something different:
    whether the score cleared the *separate*, Screening-owned interview_min_score threshold
    (see app/models/screening_settings.py), not the Candidates Dashboard's own threshold.

    Purely descriptive -- interview_ready is a computed indicator recorded on the audit_log
    entry at scoring time (see run_screening below), never a status change. Whether an
    application actually reaches interview_scheduled stays a fully human-driven decision
    (shortlisting + scheduling), same as every other transition past 'screened'.
    """
    if action == "ai_screening_failed":
        return f"AI screening failed: {details.get('error') or 'unknown error'}"

    composite = details.get("composite_score")
    score_text = f" (score {round(composite)})" if composite is not None else ""
    interview_ready = details.get("interview_ready")
    # None (key absent) means this entry predates Part F -- interview-readiness was never
    # evaluated for it, which reads as a plain "Screened," not a false "Below threshold."
    if interview_ready is None:
        return f"Screened{score_text}"
    if interview_ready:
        return f"Interview ready{score_text}"
    return f"Below interview threshold{score_text}"


def get_screening_settings(db: Session) -> ScreeningSettings:
    """The singleton settings row (id=1), seeded by migration e1f3a7c9b2d4 (dashboard
    threshold) and b3f8e6a2d5c9 (interview threshold). Defensively creates it if somehow
    missing (e.g. a test DB that ran migrations before this table existed) rather than
    crashing screening outright."""
    settings_row = db.get(ScreeningSettings, 1)
    if settings_row is None:
        settings_row = ScreeningSettings(
            id=1, dashboard_min_score=60, dashboard_max_score=100,
            interview_min_score=75, interview_max_score=100,
        )
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
    'received' application is eligible."""
    return application.status == "received"


def is_eligible_for_reevaluation(application: Application) -> bool:
    """Re-evaluate All (Part D) is deliberately broader than is_eligible_for_screening
    above: it must also revisit already-'screened' applications (so a raised/lowered
    threshold retroactively applies to them, not just to new uploads), but must never touch
    an application whose status reflects a human decision already made (hr_selected
    onward) -- that's the whole point of "never overwrite a human decision." 'on_hold' is
    excluded too: it's a deliberately paused state (see app/candidates/hold.py), not
    something a bulk background action should silently resolve out from under it."""
    return application.status in ("received", "screened")


def run_screening(db: Session, application: Application, job: JobRole, candidate: Candidate, actor: str) -> Application:
    """Runs the comprehensive screening call, logs the full breakdown to audit_log
    (always -- required, not optional, since nothing else reviews this), and auto-advances
    status to 'screened' when the composite score clears the configured minimum threshold.
    A score at or above the configured maximum gets identical treatment to a score within
    [min, max] -- there is no separate high-priority outcome, so only the minimum actually
    gates the decision.

    Also evaluates the same composite score against the separate, Part F interview
    threshold (interview_min_score) and records the result as interview_ready -- purely
    informational (see describe_interview_readiness), never a second status change. Both
    thresholds are read from the *current* settings row and stamped onto this one audit
    entry, so a historical Remarks reading reflects whatever thresholds were in effect when
    this particular screening call actually ran, not whatever they've since been changed to.

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

    interview_min_score = float(thresholds.interview_min_score)
    interview_max_score = float(thresholds.interview_max_score)
    interview_ready = score >= interview_min_score

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
            "interview_threshold_min": interview_min_score,
            "interview_threshold_max": interview_max_score,
            "interview_ready": interview_ready,
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


def re_evaluate_all(db: Session, actor: str) -> dict:
    """Re-evaluate All (Part D) -- re-runs run_screening against the *current*
    screening_settings thresholds for every application still in screening's own
    territory (see is_eligible_for_reevaluation), so a just-changed min/max threshold
    applies retroactively to existing candidates, not only to new uploads. Every other
    application (already past a human decision, or on_hold) is left completely untouched.

    Loads the whole applications table -- an admin-triggered bulk action, not a hot path,
    and this app's applications table is small enough that pagination would be pure
    overhead. One row at a time so a single AI failure or not-yet-parsed candidate can't
    stop the rest of the batch from being re-evaluated.
    """
    all_applications = db.query(Application).all()
    considered = [a for a in all_applications if is_eligible_for_reevaluation(a)]

    updated = 0
    advanced = 0
    not_ready = 0
    failed = 0
    for application in considered:
        job = db.get(JobRole, application.job_role_id)
        candidate = db.get(Candidate, application.candidate_id)
        if not job or not job.jd_text or not candidate or not candidate.parsed_fields:
            not_ready += 1
            continue
        previous_status = application.status
        try:
            run_screening(db, application, job, candidate, actor)
        except ResumeMatchError:
            failed += 1
            continue
        updated += 1
        if application.status != previous_status:
            advanced += 1

    return {
        "considered": len(considered),
        "skipped_already_decided": len(all_applications) - len(considered),
        "updated": updated,
        "advanced_to_screened": advanced,
        "not_ready": not_ready,
        "failed": failed,
    }
