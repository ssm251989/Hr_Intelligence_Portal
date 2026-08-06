from typing import Literal, Optional

from anthropic import Anthropic
from pydantic import BaseModel

from app.core.config import settings

# Haiku per docs/PROMPTS.md's tiering: high-volume/low-complexity classification.
MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = (
    "You classify and validate an extracted BGV document's OCR text. Flag as "
    "'needs_review' (not 'invalid') whenever the OCR text is ambiguous or "
    "low-confidence — a human should never see a false 'invalid' reject."
)

_client: Anthropic | None = None


class DocumentValidationError(Exception):
    """Raised when the AI document-validation call fails or returns unusable output."""


class ExtractedFields(BaseModel):
    name: Optional[str] = None
    id_number: Optional[str] = None
    date: Optional[str] = None


class DocumentValidatorOutput(BaseModel):
    doc_type_detected: Literal["aadhaar", "pan", "degree", "experience_letter", "unknown"]
    matches_expected_type: bool
    extracted_fields: ExtractedFields
    validation_status: Literal["valid", "invalid", "needs_review"]
    issues: list[str]


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def validate_document(expected_doc_type: str, ocr_text: str) -> dict:
    client = _get_client()
    user_prompt = f"Expected document type: {expected_doc_type}\nOCR extracted text: {ocr_text}"
    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            output_format=DocumentValidatorOutput,
        )
    except Exception as exc:
        raise DocumentValidationError(f"Failed to validate document: {exc}") from exc
    return response.parsed_output.model_dump()
