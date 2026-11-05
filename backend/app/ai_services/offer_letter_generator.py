from anthropic import Anthropic
from pydantic import BaseModel

from app.core.config import settings
from app.platform.ai import model_catalog

# Haiku per docs/PROMPTS.md's tiering: high-volume/low-complexity drafting.
MODEL = model_catalog.OFFER_LETTER_GENERATION

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


def _get_client():
    """Part 18.23-18.25: the tracked client -- model from Settings > GenAI, fallback model,
    usage counted (tokens, cost, user, module) and limits applied."""
    from app.platform.ai.tracked import tracked_client

    return tracked_client(feature="recruitment.offer_letter", model_key="offer_letter_generation")


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
