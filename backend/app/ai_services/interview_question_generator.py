from anthropic import Anthropic
from pydantic import BaseModel

from app.core.config import settings
from app.platform.ai import model_catalog

# Haiku per docs/PROMPTS.md's tiering: high-volume/low-complexity generation.
MODEL = model_catalog.INTERVIEW_QUESTIONS

SYSTEM_PROMPT = (
    "You generate role-specific interview questions from a job description. "
    "Tailor questions_to_probe_gaps specifically to the candidate's missing "
    "skills list, not generically to the role."
)

_client: Anthropic | None = None


class InterviewQuestionGenerationError(Exception):
    """Raised when the AI interview-question generation call fails or returns unusable output."""


class InterviewQuestionsOutput(BaseModel):
    technical_questions: list[str]
    behavioral_questions: list[str]
    questions_to_probe_gaps: list[str]


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def generate_interview_questions(jd_text: str, missing_skills: list[str]) -> dict:
    client = _get_client()
    user_prompt = f"JD: {jd_text}\nCandidate missing skills: {missing_skills}"
    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=1536,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            output_format=InterviewQuestionsOutput,
        )
    except Exception as exc:
        raise InterviewQuestionGenerationError(f"Failed to generate interview questions: {exc}") from exc
    return response.parsed_output.model_dump()
