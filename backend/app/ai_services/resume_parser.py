from typing import Optional

from anthropic import Anthropic
from pydantic import BaseModel

from app.core.config import settings

# Haiku per docs/PROMPTS.md's tiering: high-volume/low-complexity extraction.
MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = (
    "You extract structured fields from a raw resume. If a field is not present "
    "in the resume, use null. Do not fabricate values."
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
    total_experience_years: Optional[float] = None
    skills: list[str] = []
    education: list[EducationItem] = []
    work_history: list[WorkHistoryItem] = []


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
