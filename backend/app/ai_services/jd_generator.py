from anthropic import Anthropic
from pydantic import BaseModel

from app.core.config import settings

# Sonnet is the deliberate model choice for this service per docs/PROMPTS.md's
# tiering (Haiku for high-volume/low-complexity, Sonnet for judgment-heavy JD drafting).
MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = (
    "You are an HR job-description writer. Given structured role inputs, "
    "produce a complete, professional job description. You must actively use "
    "every input provided, not just title/department/location/skills: if a "
    "salary band and/or benefits are given, write a 'compensation_and_benefits' "
    "section that states the salary range and lists the benefits; if "
    "additional notes are given, fold them into an 'additional_notes_section' "
    "so the information is not lost. Never invent a salary band, benefits, or "
    "notes that were not provided in the input -- leave the corresponding "
    "output field null instead of fabricating one."
)

_client: Anthropic | None = None


class JDGenerationError(Exception):
    """Raised when the AI job-description generation call fails or returns unusable output."""


class JDOutput(BaseModel):
    title: str
    summary: str
    responsibilities: list[str]
    required_skills: list[str]
    nice_to_have: list[str]
    experience_required: str
    compensation_and_benefits: str | None = None
    additional_notes_section: str | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def _build_user_prompt(inputs: dict) -> str:
    return (
        "Role inputs:\n"
        f"Title: {inputs.get('title')}\n"
        f"Department: {inputs.get('department')}\n"
        f"Location: {inputs.get('location')}\n"
        f"Experience level: {inputs.get('experience_level')}\n"
        f"Skills: {inputs.get('skills')}\n"
        f"Salary band: {inputs.get('salary_band_min')}-{inputs.get('salary_band_max')}\n"
        f"Benefits: {inputs.get('benefits')}\n"
        f"Additional notes: {inputs.get('additional_notes')}"
    )


def generate_jd(inputs: dict) -> dict:
    client = _get_client()
    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_user_prompt(inputs)}],
            output_format=JDOutput,
        )
    except Exception as exc:
        raise JDGenerationError(f"Failed to generate job description: {exc}") from exc
    return response.parsed_output.model_dump()
