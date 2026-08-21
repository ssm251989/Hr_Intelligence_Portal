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

import re
from typing import Optional

from sqlalchemy.orm import Session

from app.ai_services.resume_matcher import ResumeMatchError, match_resume
from app.audit.service import log_action
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.screening_settings import ScreeningSettings

FACTOR_COUNT = 5

# compute_experience_score's linear falloff -- 15 points off per year the candidate's
# total_experience_years falls outside the job's [experience_min_years,
# experience_max_years] range, floored at 0 (so it reaches 0 a little under 7 years off).
EXPERIENCE_SCORE_FALLOFF_PER_YEAR = 15
# No requirement configured on the job (both bounds null) is not a penalty -- same
# "absence of a requirement" convention as location_score/certificates_score.
EXPERIENCE_SCORE_NO_REQUIREMENT = 100
# The candidate's own total_experience_years couldn't be parsed from their resume. Unlike
# location/certificates (where missing data defaults to 100, "don't penalize what can't
# be verified"), experience is central to job fit and there's no other signal to fall
# back on here -- a neutral 50 is neither a confirmed match nor a confirmed mismatch.
EXPERIENCE_SCORE_UNKNOWN_CANDIDATE_YEARS = 50

# compute_skills_score's weighted coverage across the job's 4 categorized skill lists --
# missing a must-have technical skill costs the most, good-to-have technical and
# must-have soft skills matter roughly equally in the next tier, good-to-have soft
# skills matter least. Sums to 100 so a full match on every category scores exactly 100.
SKILLS_SCORE_WEIGHTS = {
    "technical_must_have": 50,
    "technical_good_to_have": 20,
    "soft_must_have": 20,
    "soft_good_to_have": 10,
}

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
    # Named explicitly, and never collapsed into one bare "score" -- a single unlabeled
    # number here is exactly what let Resume Match and the composite Screening Score get
    # confused for each other before (see frontend/src/utils/screeningScore.ts).
    resume_match = details.get("resume_matcher_score")
    composite = details.get("composite_score")
    scores = []
    if resume_match is not None:
        scores.append(f"Resume Match: {round(resume_match)}%")
    if composite is not None:
        scores.append(f"Screening: {round(composite)}%")
    score_text = f" ({' | '.join(scores)})" if scores else ""

    missing_required = details.get("missing_required_skills")
    missing_preferred = details.get("missing_preferred_skills")
    if missing_required is None and missing_preferred is None:
        # Predates the must-have/good-to-have categorization -- this entry's
        # missing_skills was never split by severity, so render it exactly as it always
        # has been, rather than inventing a required/preferred split for data that was
        # never categorized to begin with.
        missing_skills = details.get("missing_skills") or []
        if missing_skills:
            return f"{recommendation}{score_text} -- missing {', '.join(missing_skills)}"
        return f"{recommendation}{score_text}"

    # missing_required_skills/missing_preferred_skills are technical-only (and, before
    # this categorization existed at all, whatever missing_skills held) -- a job's soft
    # skills are display-grouped separately below, not because they're missing from
    # scoring (skill_match_pct/composite_score still weigh them exactly as before, see
    # compute_skills_score), but because a resume simply not stating a soft skill in so
    # many words isn't the same kind of gap as a genuinely absent technical requirement,
    # and interview conversation -- not a hard skills line -- is how it actually gets
    # verified.
    gaps = []
    if missing_required:
        gaps.append(f"missing required: {', '.join(missing_required)}")
    if missing_preferred:
        gaps.append(f"missing preferred: {', '.join(missing_preferred)}")
    missing_soft = details.get("missing_soft_skills")
    if missing_soft:
        gaps.append(f"Soft skills to verify in interview: {', '.join(missing_soft)}")
    if gaps:
        return f"{recommendation}{score_text} -- {'; '.join(gaps)}"
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


def compute_experience_score(
    candidate_years: Optional[float], job_min_years: Optional[float], job_max_years: Optional[float]
) -> float:
    """Deterministic replacement for what used to be an AI-judged experience_score --
    now that job_roles has real experience_min_years/experience_max_years (see
    app/models/job_role.py), comparing them against the candidate's own parsed
    total_experience_years (app/ai_services/resume_parser.py) is exact, not a holistic
    AI guess from JD prose.

    Full score (EXPERIENCE_SCORE_NO_REQUIREMENT) when the job has no experience
    requirement configured at all, or when the candidate's years fall within
    [job_min_years, job_max_years] (job_max_years null means an open-ended "X+ years"
    role -- only the floor is checked). EXPERIENCE_SCORE_UNKNOWN_CANDIDATE_YEARS when a
    requirement IS configured but the candidate's years couldn't be determined. Otherwise,
    EXPERIENCE_SCORE_FALLOFF_PER_YEAR points come off per year of shortfall (below
    job_min_years) or excess (above job_max_years), floored at 0.
    """
    if job_min_years is None and job_max_years is None:
        return EXPERIENCE_SCORE_NO_REQUIREMENT
    if candidate_years is None:
        return EXPERIENCE_SCORE_UNKNOWN_CANDIDATE_YEARS
    if job_min_years is not None and candidate_years < job_min_years:
        shortfall = job_min_years - candidate_years
        return max(0, round(100 - shortfall * EXPERIENCE_SCORE_FALLOFF_PER_YEAR))
    if job_max_years is not None and candidate_years > job_max_years:
        excess = candidate_years - job_max_years
        return max(0, round(100 - excess * EXPERIENCE_SCORE_FALLOFF_PER_YEAR))
    return EXPERIENCE_SCORE_NO_REQUIREMENT


# Filler words common in JD-style requirement bullets ("Ability to interact with business
# and technical stakeholders", "8+ years of overall IT experience") that carry no
# skill-identifying signal of their own -- stripped before comparing token sets so a
# requirement's *meaningful* words drive the match, not its connective/qualifier language.
# Deliberately NOT length-based (no "drop tokens shorter than N characters"): that would
# silently treat real short technical terms -- "AI", "OCR", "SQL", "IT", "UI" -- as filler
# too, which is exactly the kind of token a requirement most needs credit for.
#
# document/processing/platforms/solutions/tools/teams/technical are here for the same
# reason but a narrower one: they're generic nouns that pad out an otherwise single-concept
# compound requirement ("OCR and document processing", "Cloud platforms such as
# Azure/AWS", "Ability to lead technical teams") without being the concept itself, so
# leaving them in the denominator was penalizing a real, specific match (e.g. "OCR") for
# not *also* repeating generic surrounding words no resume would naturally state verbatim.
# Deliberately singular/plural-specific, not stemmed equivalents of these: "solutions" and
# "platforms" are filler, but "solution" and "platform" are left alone since they're exactly
# the meaningful word in other real skills here ("RPA Solution Architecture", "Solution
# Discovery") -- stopwording those too would strip real signal, not just padding. Same
# reasoning for "process" (kept -- "Process mining" is a specific technique, not filler)
# vs. "processing" (dropped -- only ever appears here as padding after a real noun).
_SKILL_MATCH_STOPWORDS = {
    "a", "an", "the", "and", "or", "with", "of", "to", "for", "in", "on", "at", "by", "is",
    "are", "be", "as", "such", "other", "overall", "across", "including", "include",
    "includes", "using", "use", "used", "ability", "abilities", "able", "strong", "strongly",
    "excellent", "good", "great", "solid", "proven", "demonstrated", "experience",
    "experienced", "skill", "skills", "knowledge", "understanding", "familiarity",
    "proficiency", "years", "year", "yrs",
    "document", "processing", "platforms", "solutions", "tools", "teams", "technical",
}

_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")

# A small, fixed set of common English derivational suffixes, checked in this exact order
# against the token as it stands after each prior rule -- so a word can cascade through
# more than one rule in the same pass ("leadership" -> strip "ship" -> "leader" -> strip
# "er" -> "lead"). NOT a real stemmer (no vowel/consonant-doubling rules, no dictionary) --
# deliberately lightweight, so it only unifies the common, low-risk cases this suffix list
# actually covers (e.g. "developer"/"develop", "solutions"/"solution") and leaves anything
# outside that list (e.g. "architecture" vs "architect", which differ by "-ture" -- not one
# of these suffixes) unstemmed rather than guessed at.
# ("ers" before "er", "ions" before "ion": the longer suffix is tried first so a plural
# ("developers", "solutions") reduces to the same stem as its singular ("developer",
# "solution") in one pass, rather than the "er"/"ion" rule firing first and leaving a
# trailing "s" behind for no later rule to clean up.)
_STEM_SUFFIX_RULES = [
    ("ship", ""), ("ing", ""), ("ers", ""), ("er", ""), ("ions", ""), ("ion", ""),
    ("ies", "y"), ("ed", ""), ("s", ""),
]
# Never strip a suffix if doing so would leave less than this many characters -- the same
# "protect short technical terms" guarantee _SKILL_MATCH_STOPWORDS gives short acronyms
# extends to stemming too, since none of "AI"/"OCR"/"SQL"/"IT"/"UI" are anywhere near long
# enough to have a suffix removed and still clear this floor.
_STEM_MIN_RESULT_LENGTH = 4


def _stem(word: str) -> str:
    """One pass through _STEM_SUFFIX_RULES, applying each rule in order to whatever the
    word has become so far -- e.g. "leadership" clears the "ship" rule (-> "leader") then
    the "er" rule (-> "lead") in that same pass. A rule only fires if the result would still
    be at least _STEM_MIN_RESULT_LENGTH characters, so short words/acronyms are never
    touched regardless of what they happen to end in."""
    for suffix, replacement in _STEM_SUFFIX_RULES:
        if word.endswith(suffix) and len(word) - len(suffix) + len(replacement) >= _STEM_MIN_RESULT_LENGTH:
            word = word[: -len(suffix)] + replacement
    return word


def _tokenize(text: str) -> set[str]:
    """Lowercase, split on anything that isn't a letter/digit (whitespace, slashes,
    hyphens, punctuation), drop filler words, then stem what's left -- e.g. "SQL /
    database integration" -> {"sql", "database", "integration"} (none of these end in a
    stemmed suffix, so stemming is a no-op here), "Ability to lead technical teams" ->
    {"lead"} (stopwords strip "ability"/"to"/"technical"/"teams", leaving just "lead"),
    "Technical Leadership" -> {"lead"} too (stopwords strip "technical", stemming reduces
    "leadership" -> "lead"). Stopword-filtering happens on the raw (unstemmed) word, since
    _SKILL_MATCH_STOPWORDS is written in surface-word form."""
    words = _TOKEN_SPLIT_RE.split(text.lower())
    return {_stem(word) for word in words if word and word not in _SKILL_MATCH_STOPWORDS}


def _tokenize_all(items: Optional[list[str]]) -> set[str]:
    """Union of _tokenize's output across every item -- e.g. a candidate's separate
    parsed skills "SQL Server" and "API Integration" contribute {"sql", "server"} and
    {"api", "integration"} to one combined pool, so a job requirement's tokens can be
    satisfied by evidence spread across several of the candidate's own skill entries."""
    tokens: set[str] = set()
    for item in items or []:
        if item and item.strip():
            tokens |= _tokenize(item)
    return tokens


# Requirement bullets sometimes state a bare years-of-experience qualifier inline (e.g.
# "8+ years of overall IT experience", "5+ years of strong RPA experience") rather than as
# a genuinely separate skill. That's already captured, precisely, by
# experience_min_years/experience_max_years against the candidate's own
# total_experience_years (see compute_experience_score) -- token-matching it a second time
# here would only ever flag it as a missing "skill" (these phrases tokenize down to
# near-nothing after stopwording: mostly a bare number and a short qualifier word), doubly
# penalizing the exact same gap compute_experience_score already scores, or double-crediting
# it, neither of which reflects the job's own actual skill list. Detected generically by
# pattern -- digits immediately before year(s)/yrs, with "experience" nearby in the same
# bullet -- rather than hardcoded to either real string above, so it also excludes any other
# job's own equivalent phrasing.
_EXPERIENCE_YEARS_PHRASE_RE = re.compile(
    r"\d+\+?\s*(?:years?|yrs)\b[\s\w]{0,30}\bexperience\b"
    r"|\bexperience\b[\s\w]{0,30}\d+\+?\s*(?:years?|yrs)\b",
    re.IGNORECASE,
)


def _is_experience_years_requirement(requirement: str) -> bool:
    """True for a requirement bullet that's just years-of-experience phrasing (see
    _EXPERIENCE_YEARS_PHRASE_RE above) -- already covered by compute_experience_score, so
    _skill_coverage excludes it entirely rather than token-matching it a second time."""
    return bool(_EXPERIENCE_YEARS_PHRASE_RE.search(requirement))


# A requirement counts as "satisfied" (excluded from the missing-skills list) once at
# least half of its significant tokens turn up somewhere in the candidate's tokenized
# skills -- e.g. "SQL / database integration" against a candidate whose skills include
# "SQL Server" and "API Integration" (2 of 3 tokens: "sql", "integration") clears it, while
# "Bot Creator / Bot Runner" against a resume that never mentions bots (0 of 3) does not.
# Below the threshold the requirement still earns partial credit toward the category's
# coverage fraction (see _skill_coverage) -- only the missing-list categorization used by
# Remarks is all-or-nothing. 50% (a majority of a requirement's own significant words) is
# the threshold rather than "any single token" specifically so a 3-4 concept compound
# phrase can't be called satisfied off one incidental word alone.
SKILL_MATCH_SATISFIED_THRESHOLD = 0.5


def _skill_coverage(
    candidate_skill_tokens: set[str], required_skills: Optional[list[str]]
) -> tuple[float, list[str]]:
    """(coverage fraction 0-1, the subset of `required_skills` the candidate is missing)
    for one category. Coverage is token-overlap based, not exact-string or substring --
    job requirement lists are routinely written as full sentences and compound phrases
    ("Automation Anywhere Control Room", "Ability to interact with business and technical
    stakeholders") rather than short tags matching a parsed resume's skills entries
    verbatim, so comparing whole strings (however forgivingly) misses most real evidence.
    Each requirement earns partial credit for partial token overlap, summed into the
    returned coverage fraction, but only counts as matched (excluded from `missing`) at or
    above SKILL_MATCH_SATISFIED_THRESHOLD -- see that constant for the reasoning.

    An empty/absent category has nothing to cover -- full coverage (1.0) and no missing
    skills, same "absence of a requirement is not a penalty" convention as
    location_score/certificates_score/experience_score. A requirement whose text is
    entirely filler words once tokenized (no real content to check for) is likewise
    treated as satisfied on its own, rather than unmatchable by construction. A bare
    years-of-experience requirement (see _is_experience_years_requirement) is dropped
    before coverage is even computed -- not just excluded from `missing` -- since
    compute_experience_score already scores that exact gap elsewhere."""
    required = [
        skill for skill in (required_skills or [])
        if skill and skill.strip() and not _is_experience_years_requirement(skill)
    ]
    if not required:
        return 1.0, []

    missing = []
    total_overlap = 0.0
    for skill in required:
        requirement_tokens = _tokenize(skill)
        overlap = (
            1.0
            if not requirement_tokens
            else len(requirement_tokens & candidate_skill_tokens) / len(requirement_tokens)
        )
        total_overlap += overlap
        if overlap < SKILL_MATCH_SATISFIED_THRESHOLD:
            missing.append(skill)

    return total_overlap / len(required), missing


def compute_skills_score(
    candidate_skills: Optional[list[str]],
    technical_must_have: Optional[list[str]],
    technical_good_to_have: Optional[list[str]],
    soft_must_have: Optional[list[str]],
    soft_good_to_have: Optional[list[str]],
    candidate_certificates: Optional[list[str]] = None,
) -> dict:
    """Deterministic replacement for what used to be an AI-judged skill_match_pct -- a
    SKILLS_SCORE_WEIGHTS-weighted coverage across the job's 4 categorized skill lists
    (see app/models/job_role.py), rather than a holistic AI guess from JD prose. Matching
    is token-overlap based (see _skill_coverage/_tokenize) -- case/punctuation/word-order
    insensitive, and forgiving of a job requirement bundling several concepts into one
    phrase or a candidate's resume splitting them across several parsed skills.

    candidate_certificates (optional) is folded into the same token pool as
    candidate_skills, not compared separately -- a platform/technology requirement (e.g.
    "Azure") can be satisfied by a certification name that names it ("Microsoft Azure
    Fundamentals (AZ-900)") even though parsed_fields files it under certificates, not
    skills. Certificates get no separate weighting here; compute_certificates_score
    against the job's own preferred_certifications list is still the only place
    certificate coverage is scored in its own right.

    Returns {"score": int, "missing_required": [str], "missing_preferred": [str],
    "missing_required_technical": [str], "missing_preferred_technical": [str],
    "missing_soft": [str]} -- missing_required/missing_preferred are the flat,
    backward-compatible union across technical and soft (still what feeds
    Application.missing_skills and every score/threshold decision -- this categorization
    is purely a Remarks *display* concern, see describe_screening_audit_entry, and never
    changes skill_match_pct/composite_score). missing_required_technical/
    missing_preferred_technical are the technical-only subset of those same two lists, and
    missing_soft is every unmatched soft skill (must-have or good-to-have, not
    distinguished by severity) -- Remarks renders technical gaps as today's "missing
    required"/"missing preferred" lines and soft gaps as their own separate
    "Soft skills to verify in interview" line, since a soft skill's absence from a resume
    isn't the kind of hard gap those two lines were written to convey.
    """
    candidate_tokens = _tokenize_all(candidate_skills) | _tokenize_all(candidate_certificates)

    tech_must_coverage, tech_must_missing = _skill_coverage(candidate_tokens, technical_must_have)
    tech_good_coverage, tech_good_missing = _skill_coverage(candidate_tokens, technical_good_to_have)
    soft_must_coverage, soft_must_missing = _skill_coverage(candidate_tokens, soft_must_have)
    soft_good_coverage, soft_good_missing = _skill_coverage(candidate_tokens, soft_good_to_have)

    score = (
        tech_must_coverage * SKILLS_SCORE_WEIGHTS["technical_must_have"]
        + tech_good_coverage * SKILLS_SCORE_WEIGHTS["technical_good_to_have"]
        + soft_must_coverage * SKILLS_SCORE_WEIGHTS["soft_must_have"]
        + soft_good_coverage * SKILLS_SCORE_WEIGHTS["soft_good_to_have"]
    )

    return {
        "score": round(score),
        "missing_required": tech_must_missing + soft_must_missing,
        "missing_preferred": tech_good_missing + soft_good_missing,
        "missing_required_technical": tech_must_missing,
        "missing_preferred_technical": tech_good_missing,
        "missing_soft": soft_must_missing + soft_good_missing,
    }


def compute_certificates_score(
    candidate_certificates: Optional[list[str]], preferred_certifications: Optional[list[str]]
) -> dict:
    """Deterministic replacement for what used to be an AI-judged certificates_score --
    coverage of the job's preferred_certifications by the candidate's own parsed
    certificates (app/ai_services/resume_parser.py), reusing the exact same token-overlap
    matching as compute_skills_score's _skill_coverage -- e.g. a job wanting "Automation
    Anywhere Certified Advanced RPA Professional" is satisfied by a candidate's "Automation
    Anywhere Certified Advanced RPA Professional -- A360" without the trailing suffix
    breaking an exact-string comparison. preferred_certifications is a single flat list --
    every entry is already "preferred," not required, so unlike skills there's no
    must-have/good-to-have weighting here, just the plain coverage fraction scaled to
    0-100: full score when the job names no certifications at all (absence of a
    requirement is not a penalty, same convention as location_score/experience_score/
    skill_match_pct), otherwise however much of the list the candidate's own certificates
    cover.

    Returns {"score": int, "missing": [str]} -- missing is every preferred certification
    the candidate doesn't hold, logged on the audit_log entry for the same transparency
    compute_skills_score's missing_required/missing_preferred give, even though it isn't
    (yet) surfaced in Remarks text the way skill gaps are.
    """
    candidate_tokens = _tokenize_all(candidate_certificates)
    coverage, missing = _skill_coverage(candidate_tokens, preferred_certifications)
    return {"score": round(coverage * 100), "missing": missing}


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

    candidate_years = (candidate.parsed_fields or {}).get("total_experience_years")
    job_min_years = float(job.experience_min_years) if job.experience_min_years is not None else None
    job_max_years = float(job.experience_max_years) if job.experience_max_years is not None else None
    result["experience_score"] = compute_experience_score(candidate_years, job_min_years, job_max_years)

    candidate_skills = (candidate.parsed_fields or {}).get("skills")
    candidate_certificates = (candidate.parsed_fields or {}).get("certificates")
    skills_result = compute_skills_score(
        candidate_skills, job.technical_skills_must_have, job.technical_skills_good_to_have,
        job.soft_skills_must_have, job.soft_skills_good_to_have,
        candidate_certificates=candidate_certificates,
    )
    result["skill_match_pct"] = skills_result["score"]
    result["missing_skills"] = skills_result["missing_required"] + skills_result["missing_preferred"]

    certificates_result = compute_certificates_score(candidate_certificates, job.preferred_certifications)
    result["certificates_score"] = certificates_result["score"]

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
            "missing_required_skills": skills_result["missing_required_technical"],
            "missing_preferred_skills": skills_result["missing_preferred_technical"],
            "missing_soft_skills": skills_result["missing_soft"],
            "missing_preferred_certifications": certificates_result["missing"],
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
