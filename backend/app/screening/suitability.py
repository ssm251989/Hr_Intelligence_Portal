"""Suitable-For job suggestion -- Part B of the screening feature.

For a candidate whose resume has just been parsed, suggests which *published* job they
best fit -- independent of, and never touching, whichever job(s) they actually applied
for (see app/screening/service.py for that, application-scoped, screening). Purely
informational: stored on the candidate as suitable_job_id/suitable_job_score.

Two-stage to control AI cost, same principle as batching a JD's cache_control block in
app/ai_services/resume_matcher.py, just applied the other direction: a cheap, local,
no-AI keyword pre-filter ranks every published job by skill overlap against the
candidate's parsed skills, and only the top few of those go to a real Haiku call (reusing
match_resume -- the exact call Part A's screening already makes) that keeps whichever
scores highest. A candidate is never compared against every published job via AI, no
matter how many are published.
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.ai_services.resume_matcher import ResumeMatchError, match_resume
from app.audit.service import log_action
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.screening.service import composite_score

# "Top 2-3" per the feature spec -- 3 is the cap, not a guarantee; fewer published jobs
# (or fewer with jd_text) simply means fewer AI calls, never more.
PRE_FILTER_TOP_N = 3


def _keyword_overlap_score(candidate_skills: list[str], job_skills: list[str]) -> float:
    """Cheap, local, no-AI heuristic: fraction of the job's required skills the
    candidate's parsed skills cover, case-insensitively. Used only to rank jobs before
    spending a real AI call on the few most plausible ones -- never stored or returned as
    a suitability score itself, since it has no idea about experience/location/certs."""
    job_set = {s.strip().lower() for s in job_skills if s}
    if not job_set:
        return 0.0
    candidate_set = {s.strip().lower() for s in candidate_skills if s}
    return len(candidate_set & job_set) / len(job_set)


def pre_filter_published_jobs(db: Session, candidate: Candidate, top_n: int = PRE_FILTER_TOP_N) -> list[JobRole]:
    """Ranks every *published* job by local keyword overlap against the candidate's parsed
    skills and returns only the top `top_n` -- the AI comparison call in
    attempt_auto_suggest_suitable_job is only ever spent on this short list, never on every
    published job. Draft/on_hold/closed/ready_for_publishing jobs are never candidates for
    a suitability suggestion, same as they're never candidates for a real application.

    Also excludes any published job with no jd_text up front, at the query level -- there's
    nothing for match_resume to compare against, so a job like that must never occupy one
    of the scarce top_n slots (ties on keyword overlap are common; letting a
    can-never-be-scored job win a tie would silently starve out real candidates)."""
    candidate_skills = (candidate.parsed_fields or {}).get("skills") or []
    published_jobs = (
        db.query(JobRole)
        .filter(JobRole.status == "published", JobRole.jd_text.isnot(None))
        .all()
    )
    ranked = sorted(
        published_jobs,
        key=lambda job: _keyword_overlap_score(candidate_skills, job.skills or []),
        reverse=True,
    )
    return ranked[:top_n]


def attempt_auto_suggest_suitable_job(db: Session, candidate: Candidate, actor: str = "system") -> Optional[Candidate]:
    """Best-effort automatic trigger, called right after a resume is parsed (see
    app/candidates/router.py parse_and_apply_resume) -- silently does nothing if the
    candidate isn't parsed yet or no published job survives the pre-filter, and a
    per-job AI failure just drops that one job from consideration rather than aborting the
    whole scan (so one flaky job among the top few can't hide a perfectly good match on
    another).

    Compares the candidate against only the pre-filtered candidate jobs (one real AI call
    each, reusing app/ai_services/resume_matcher.match_resume) and keeps whichever scores
    highest by the same composite_score used for application screening, for an
    apples-to-apples number between "suitable for" and "screened against". Never reads or
    writes any Application row, so it can never change which job a candidate is actually
    recorded as having applied for.
    """
    if not candidate.parsed_fields:
        return None

    candidate_jobs = pre_filter_published_jobs(db, candidate)
    if not candidate_jobs:
        return None

    best_job: Optional[JobRole] = None
    best_score: Optional[float] = None
    for job in candidate_jobs:
        try:
            result = match_resume(job.jd_text, candidate.parsed_fields, candidate.location, job.location)
        except ResumeMatchError:
            continue
        score = composite_score(result)
        if best_score is None or score > best_score:
            best_job, best_score = job, score

    if best_job is None:
        return None

    candidate.suitable_job_id = best_job.id
    candidate.suitable_job_score = best_score
    db.commit()
    db.refresh(candidate)

    log_action(
        db,
        "candidate",
        candidate.id,
        "ai_suitability_scored",
        actor,
        {
            "suitable_job_id": str(best_job.id),
            "suitable_job_title": best_job.title,
            "suitable_job_score": best_score,
            "jobs_considered": [str(job.id) for job in candidate_jobs],
        },
    )
    return candidate
