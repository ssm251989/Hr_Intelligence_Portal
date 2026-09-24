"""Shortlisting's "AI Suggestion" button (see app/shortlisting/router.py suggest_shortlist_
feedback) -- drafts one evaluator-feedback paragraph from the candidate's real screening
data. Haiku per docs/PROMPTS.md's tiering (high-volume/low-complexity, same tier as the
Resume Matcher): this is a single-paragraph draft over already-computed inputs, not the kind
of open-ended judgment call Sonnet is reserved for elsewhere (see app/ai_services/
candidate_ranker.py).

Advisory only -- the returned text is never saved anywhere by this call itself. The
evaluator reviews/edits it in the feedback box before an explicit Save actually persists
anything (see ShortlistStatusPanel.tsx), same "AI proposes, human decides" framing as every
other AI feature in this app.
"""

from typing import Optional

from anthropic import Anthropic
from pydantic import BaseModel

from app.core.config import settings
from app.platform.ai import model_catalog

MODEL = model_catalog.SHORTLIST_FEEDBACK

SYSTEM_PROMPT = (
    "You draft evaluator feedback for a candidate at the shortlisting stage of a hiring "
    "pipeline. Base this strictly on the real screening data given -- the composite score, "
    "matched skills, and missing skills. Write one concise, specific paragraph an HR "
    "evaluator can edit before saving. Never invent skills, experience, or scores not "
    "present in the input. This is a draft only -- the evaluator makes the final call."
)

_client: Optional[Anthropic] = None


class ShortlistFeedbackGenerationError(Exception):
    """Raised when the AI feedback-suggestion call fails or returns unusable output."""


class ShortlistFeedbackSuggestion(BaseModel):
    feedback: str


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def generate_shortlist_feedback(
    candidate_name: str,
    job_title: str,
    composite_score: Optional[float],
    matched_skills: list[str],
    missing_skills: list[str],
) -> str:
    client = _get_client()
    user_prompt = (
        f"Candidate: {candidate_name}\n"
        f"Job: {job_title}\n"
        f"Composite screening score (0-100): {composite_score}\n"
        f"Matched skills: {matched_skills}\n"
        f"Missing skills: {missing_skills}"
    )
    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            output_format=ShortlistFeedbackSuggestion,
        )
    except Exception as exc:
        raise ShortlistFeedbackGenerationError(f"Failed to generate shortlist feedback suggestion: {exc}") from exc
    return response.parsed_output.feedback
