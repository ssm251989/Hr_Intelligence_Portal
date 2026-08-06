from anthropic import Anthropic
from pydantic import BaseModel

from app.core.config import settings

# Haiku per docs/PROMPTS.md's tiering: high-volume/low-complexity drafting.
MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = (
    "You draft an offer letter (LOI) from confirmed hiring details. Use the "
    "exact salary and role details provided — never estimate or round these."
)

_client: Anthropic | None = None


class OfferLetterGenerationError(Exception):
    """Raised when the AI offer-letter generation call fails or returns unusable output."""


class KeyTermsSummary(BaseModel):
    role: str
    salary: str
    start_date: str
    reporting_manager: str


class OfferLetterOutput(BaseModel):
    offer_letter_text: str
    key_terms_summary: KeyTermsSummary


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def generate_offer_letter(
    candidate_name: str, job_title: str, approved_salary: str, start_date: str, reporting_manager_name: str
) -> dict:
    client = _get_client()
    user_prompt = (
        f"Candidate name: {candidate_name}\n"
        f"Role: {job_title}\n"
        f"Approved salary: {approved_salary}\n"
        f"Start date: {start_date}\n"
        f"Reporting manager: {reporting_manager_name}"
    )
    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            output_format=OfferLetterOutput,
        )
    except Exception as exc:
        raise OfferLetterGenerationError(f"Failed to generate offer letter: {exc}") from exc
    return response.parsed_output.model_dump()
