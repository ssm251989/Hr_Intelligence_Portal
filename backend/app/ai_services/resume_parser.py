from typing import Optional

from anthropic import Anthropic
from pydantic import BaseModel

from app.core.config import settings
from app.platform.ai import model_catalog

# Haiku per docs/PROMPTS.md's tiering: high-volume/low-complexity extraction.
MODEL = model_catalog.RESUME_EXTRACTION

SYSTEM_PROMPT = (
    "You extract structured fields from a raw resume. If a field is not present "
    "in the resume, use null. Do not fabricate values. certificates is any named "
    "professional certification, license, or credential the candidate holds (e.g. "
    "'AWS Certified Solutions Architect', 'PMP', 'CPA') -- not degrees (those belong in "
    "education) and not just skills or tools listed without an actual certification name. "
    "location is the candidate's current city (plus state/country if the resume states "
    "them), e.g. 'Bangalore, India' -- not a past employer's office location, and not a "
    "remote-work preference."
)

_client: Anthropic | None = None


class ResumeParsingError(Exception):
    """Raised when the AI resume-parsing call fails or returns unusable output."""


class EducationItem(BaseModel):
    degree: Optional[str] = None
    institution: Optional[str] = None
    year: Optional[int] = None


class WorkHistoryItem(BaseModel):
    company: Optional[str] = None
    title: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None


class ResumeParserOutput(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    total_experience_years: Optional[float] = None
    skills: list[str] = []
    education: list[EducationItem] = []
    work_history: list[WorkHistoryItem] = []
    certificates: list[str] = []


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def parse_resume(raw_resume_text: str) -> dict:
    client = _get_client()
    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Resume text:\n{raw_resume_text}"}],
            output_format=ResumeParserOutput,
        )
    except Exception as exc:
        raise ResumeParsingError(f"Failed to parse resume: {exc}") from exc
    return response.parsed_output.model_dump()


# --- Part G: local-import batch parsing ---
#
# The single-resume path above uses `.messages.parse`'s native structured-output feature
# (`output_config`), which isn't accepted by the lower-level Message Batches API's request
# shape -- so batch requests instead force the same ResumeParserOutput shape via a tool call
# (a stable, fully public API surface, unlike reaching into the SDK's own private schema-
# transform helper). One tool schema derived from the exact same ResumeParserOutput model
# used above, so the two paths can never drift apart on what a "parsed resume" looks like.

BATCH_TOOL_NAME = "record_parsed_resume"

_BATCH_TOOL = {
    "name": BATCH_TOOL_NAME,
    "description": "Records the structured fields extracted from one resume.",
    "input_schema": ResumeParserOutput.model_json_schema(),
}


def build_batch_request(custom_id: str, raw_resume_text: str) -> dict:
    """One Message Batches API request (see anthropic.types.messages.batch_create_params.
    Request) for a single resume's text -- custom_id is how extract_parsed_output_from_message
    below matches a batch result back to the file it came from, since results can return in
    any order."""
    return {
        "custom_id": custom_id,
        "params": {
            "model": MODEL,
            "max_tokens": 2048,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": f"Resume text:\n{raw_resume_text}"}],
            "tools": [_BATCH_TOOL],
            "tool_choice": {"type": "tool", "name": BATCH_TOOL_NAME},
        },
    }


def extract_parsed_output_from_message(message) -> dict:
    """The batch counterpart to parse_resume's `response.parsed_output.model_dump()` --
    finds the forced tool_use block in one succeeded batch result's Message and validates
    its `.input` against the exact same ResumeParserOutput model."""
    for block in message.content:
        if block.type == "tool_use" and block.name == BATCH_TOOL_NAME:
            return ResumeParserOutput.model_validate(block.input).model_dump()
    raise ResumeParsingError("Batch result contained no record_parsed_resume tool call")
