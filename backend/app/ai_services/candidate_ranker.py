"""Candidate ranking (docs/HRMS_COMPLETE_SPEC.txt Part 8 section 4: "Model per purpose via
LLM gateway... Prompt texts in a prompt registry"). The one ai_services/*.py call site
migrated onto `ai.gateway.complete(purpose=...)` + `platform.recruitment.prompt_registry`
in this pass -- see docs/build_log.md's own Part 8 note for why the other 7 (resume_
matcher, resume_parser, document_validator, interview_question_generator, jd_generator,
offer_letter_generator, shortlist_feedback_generator) still call the Anthropic SDK
directly with a hardcoded prompt, unmigrated.

`AnthropicAdapter.complete()` (app/platform/connectors/providers/anthropic_provider.py)
wraps `messages.create()`, not the SDK's own `.messages.parse()` structured-output helper
-- so structured output here goes through Anthropic's own tool-use mechanism (a single
forced tool call) instead, parsed back into the same `CandidateRankingOutput` shape every
existing caller already expects. Nothing about `rank_candidate`'s own public signature or
return shape changed -- only where the model id, system prompt, and API client come from.
"""

from typing import Literal, Optional

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.platform.ai import gateway
from app.platform.tenancy.context import require_current_tenant
from app.recruitment.prompt_registry import get_or_seed_published_prompt

PROMPT_KEY = "recruitment.candidate_ranking"
PROMPT_PURPOSE = "llm.judgment"

_DEFAULT_SYSTEM_PROMPT = (
    "You produce an explainable ranking for a shortlisted candidate against a "
    "job description, combining skills fit and any available interview signal. "
    "The rationale must reference specific evidence from the inputs, not "
    "generic praise. This output is advisory only — HR makes the final "
    "selection."
)

_RANKING_TOOL = {
    "name": "submit_candidate_ranking",
    "description": "Submit the candidate ranking result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "composite_score": {"type": "integer"},
            "rank_rationale": {"type": "string"},
            "strengths": {"type": "array", "items": {"type": "string"}},
            "concerns": {"type": "array", "items": {"type": "string"}},
            "recommendation": {"type": "string", "enum": ["recommend", "consider", "not_recommended"]},
        },
        "required": ["composite_score", "rank_rationale", "strengths", "concerns", "recommendation"],
    },
}


class CandidateRankingError(Exception):
    """Raised when the AI candidate-ranking call fails or returns unusable output."""


class CandidateRankingOutput(BaseModel):
    composite_score: int
    rank_rationale: str
    strengths: list[str]
    concerns: list[str]
    recommendation: Literal["recommend", "consider", "not_recommended"]


def rank_candidate(db: Session, jd_text: str, match_data: dict, interview_feedback: Optional[list]) -> dict:
    tenant = require_current_tenant()
    prompt = get_or_seed_published_prompt(
        db, tenant, key=PROMPT_KEY, name="Candidate ranking", default_system_prompt=_DEFAULT_SYSTEM_PROMPT, purpose=PROMPT_PURPOSE,
    )
    user_prompt = (
        f"JD: {jd_text}\n"
        f"Resume match data: {match_data}\n"
        f"Interview feedback (if any): {interview_feedback or 'none'}"
    )
    try:
        response = gateway.complete(
            db, tenant, purpose=PROMPT_PURPOSE, system=prompt.system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=1536, tools=[_RANKING_TOOL], tool_choice={"type": "tool", "name": "submit_candidate_ranking"},
        )
        tool_use = next(block for block in response["content"] if block.get("type") == "tool_use")
        parsed = CandidateRankingOutput(**tool_use["input"])
    except Exception as exc:
        raise CandidateRankingError(f"Failed to rank candidate: {exc}") from exc
    return parsed.model_dump()
