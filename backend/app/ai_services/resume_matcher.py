from typing import Literal

from anthropic import Anthropic
from pydantic import BaseModel

from app.core.config import settings

# Haiku per docs/PROMPTS.md's tiering: high-volume/low-complexity first-pass matching.
MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = (
    "You compare a candidate resume against a job description. Base this "
    "strictly on evidence in the resume text. Do not infer skills that are not "
    "stated or clearly implied by the candidate's actual experience. Score "
    "match_score and skill_match_pct on a 0-100 scale."
)

_client: Anthropic | None = None


class ResumeMatchError(Exception):
    """Raised when the AI resume-matching call fails or returns unusable output."""


class ResumeMatchOutput(BaseModel):
    match_score: int
    skill_match_pct: int
    missing_skills: list[str]
    recommendation: Literal["strong_fit", "possible_fit", "weak_fit"]


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def match_resume(jd_text: str, parsed_fields: dict) -> dict:
    client = _get_client()
    user_prompt = f"JD: {jd_text}\nParsed resume: {parsed_fields}"
    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            output_format=ResumeMatchOutput,
        )
    except Exception as exc:
        raise ResumeMatchError(f"Failed to match resume against job description: {exc}") from exc
    return response.parsed_output.model_dump()
