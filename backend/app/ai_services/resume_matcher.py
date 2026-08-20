from typing import Literal, Optional

from anthropic import Anthropic
from pydantic import BaseModel

from app.core.config import settings

# Haiku per docs/PROMPTS.md's tiering: high-volume/low-complexity first-pass matching.
MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = (
    "You compare a candidate resume against a job description. Base this "
    "strictly on evidence in the resume text. Do not infer skills that are not "
    "stated or clearly implied by the candidate's actual experience. Score every "
    "*_score field on a 0-100 scale.\n\n"
    "You score three independent dimensions -- experience fit and skills fit are "
    "deliberately not among them, since app/screening/service.py computes both itself: "
    "experience_score from the job's real experience_min_years/experience_max_years "
    "against the candidate's parsed total_experience_years, and skill_match_pct from the "
    "job's 4 categorized skill lists against the candidate's parsed skills -- rather than "
    "asking you to guess at either from prose. Your three scores are used later as "
    "equally-weighted inputs (alongside those two computed scores) to a composite "
    "screening score:\n"
    "- location_score: how well the candidate's location fits the job's location. Score 100 "
    "if either location is unspecified, they match, or the role reads as remote-friendly; "
    "score lower for a real geographic mismatch with no indication of relocation/remote work.\n"
    "- certificates_score: how well the candidate's certifications support this role. Score "
    "100 if the job doesn't call for any particular certification and the candidate has none "
    "to weigh against it (absence of a requirement is not a penalty) -- score lower only when "
    "the JD implies certifications matter and the candidate's don't support that.\n"
    "- match_score: your overall holistic fit assessment.\n"
)

_client: Anthropic | None = None


class ResumeMatchError(Exception):
    """Raised when the AI resume-matching call fails or returns unusable output."""


class ResumeMatchOutput(BaseModel):
    match_score: int
    location_score: int
    certificates_score: int
    recommendation: Literal["strong_fit", "possible_fit", "weak_fit"]


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def match_resume(
    jd_text: str,
    parsed_fields: dict,
    candidate_location: Optional[str] = None,
    job_location: Optional[str] = None,
) -> dict:
    """One Haiku call producing three of the five factors app/screening/service.py needs
    for its equal-weighted composite score (location_score, certificates_score,
    match_score) -- never a separate call per factor. The other two, experience_score
    and skill_match_pct, are computed deterministically by app/screening/service.py's
    compute_experience_score/compute_skills_score from real structured data instead of
    being asked of the AI.

    The JD text is its own cache_control-marked content block: when the same job is
    screened against many candidates in one run (a bulk "re-evaluate all", or Part G's
    batch import), every one of those calls repeats this exact block, so marking it
    cacheable lets Anthropic's prompt cache pick up the discount instead of re-billing the
    full JD as fresh input tokens on every candidate. A single ad-hoc call (the manual
    "Screen Candidate" button) still works identically -- cache_control just goes unused.
    """
    client = _get_client()
    candidate_prompt = (
        f"Parsed resume: {parsed_fields}\n"
        f"Candidate location: {candidate_location or 'not specified'}\n"
        f"Job location: {job_location or 'not specified'}"
    )
    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Job description:\n{jd_text}",
                            "cache_control": {"type": "ephemeral"},
                        },
                        {"type": "text", "text": candidate_prompt},
                    ],
                }
            ],
            output_format=ResumeMatchOutput,
        )
    except Exception as exc:
        raise ResumeMatchError(f"Failed to match resume against job description: {exc}") from exc
    return response.parsed_output.model_dump()
