from anthropic import Anthropic
from pydantic import BaseModel

from app.core.config import settings

# Sonnet is the deliberate model choice for this service per docs/PROMPTS.md's
# tiering (Haiku for high-volume/low-complexity, Sonnet for judgment-heavy JD drafting).
MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = (
    "You are an HR job-description writer. Given structured role inputs, "
    "produce a complete, professional job description."
)

_client: Anthropic | None = None


class JDOutput(BaseModel):
    title: str
    summary: str
    responsibilities: list[str]
    required_skills: list[str]
    nice_to_have: list[str]
    experience_required: str


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
        f"Salary band: {inputs.get('salary_band_min')}-{inputs.get('salary_band_max')}"
    )


def generate_jd(inputs: dict) -> dict:
    client = _get_client()
    response = client.messages.parse(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_prompt(inputs)}],
        output_format=JDOutput,
    )
    return response.parsed_output.model_dump()
