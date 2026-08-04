from typing import Literal, Optional

from anthropic import Anthropic
from pydantic import BaseModel

from app.core.config import settings

# Sonnet per docs/PROMPTS.md's tiering: judgment-heavy shortlist scoring.
MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = (
    "You produce an explainable ranking for a shortlisted candidate against a "
    "job description, combining skills fit and any available interview signal. "
    "The rationale must reference specific evidence from the inputs, not "
    "generic praise. This output is advisory only — HR makes the final "
    "selection."
)

_client: Anthropic | None = None


class CandidateRankingOutput(BaseModel):
    composite_score: int
    rank_rationale: str
    strengths: list[str]
    concerns: list[str]
    recommendation: Literal["recommend", "consider", "not_recommended"]


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def rank_candidate(jd_text: str, match_data: dict, interview_feedback: Optional[list]) -> dict:
    client = _get_client()
    user_prompt = (
        f"JD: {jd_text}\n"
        f"Resume match data: {match_data}\n"
        f"Interview feedback (if any): {interview_feedback or 'none'}"
    )
    response = client.messages.parse(
        model=MODEL,
        max_tokens=1536,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        output_format=CandidateRankingOutput,
    )
    return response.parsed_output.model_dump()
