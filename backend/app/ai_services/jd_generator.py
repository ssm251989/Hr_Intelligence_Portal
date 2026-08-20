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
    "output field null instead of fabricating one.\n\n"
    "The role's skills are given as 4 separate categories -- technical/soft, each "
    "must-have/good-to-have. 'required_skills' must be built from the must-have "
    "technical and must-have soft skills given (soft skills phrased as skills, e.g. "
    "'Clear written communication', not restated as personality traits); "
    "'nice_to_have' must be built the same way from the good-to-have technical and "
    "good-to-have soft skills. Never move a skill from one bucket to the other, and "
    "never invent a skill that wasn't given in either bucket.\n\n"
    "If key_responsibilities is given, treat it as a strong starting point and anchor "
    "for the 'responsibilities' output: expand/rephrase/reformat it into clear list "
    "items rather than inventing a different set of responsibilities from scratch, and "
    "never drop or contradict anything it says. If it is not given, generate typical "
    "responsibilities for the role yourself, as before. If an education requirement "
    "(degree level and/or field) is given, write an 'education_requirement' section "
    "stating it plainly (e.g. \"Bachelor's degree in Computer Science or related "
    "field\"); if preferred_certifications is given, write a "
    "'preferred_certifications_section' listing them. Leave either field null, exactly "
    "like compensation_and_benefits/additional_notes_section, if the corresponding "
    "input was not provided -- never invent an education requirement or a "
    "certification that wasn't given."
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
    education_requirement: str | None = None
    preferred_certifications_section: str | None = None
    compensation_and_benefits: str | None = None
    additional_notes_section: str | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def _format_experience_range(min_years, max_years) -> str:
    """Renders the job's numeric experience_min_years/experience_max_years for the JD
    prompt -- same "X-Y years"/"X+ years" convention used everywhere else this range is
    displayed (see frontend/src/utils/experience.ts formatExperienceRange)."""
    if min_years is None and max_years is None:
        return "Not specified"
    if max_years is None:
        return f"{min_years:g}+ years"
    if min_years is None:
        return f"Up to {max_years:g} years"
    if min_years == max_years:
        return f"{min_years:g} years"
    return f"{min_years:g}-{max_years:g} years"


def _build_user_prompt(inputs: dict) -> str:
    return (
        "Role inputs:\n"
        f"Title: {inputs.get('title')}\n"
        f"Department: {inputs.get('department')}\n"
        f"Location: {inputs.get('location')}\n"
        f"Experience level: {_format_experience_range(inputs.get('experience_min_years'), inputs.get('experience_max_years'))}\n"
        f"Technical skills (must-have): {inputs.get('technical_skills_must_have')}\n"
        f"Technical skills (good-to-have): {inputs.get('technical_skills_good_to_have')}\n"
        f"Soft skills (must-have): {inputs.get('soft_skills_must_have')}\n"
        f"Soft skills (good-to-have): {inputs.get('soft_skills_good_to_have')}\n"
        f"Key responsibilities (use as a strong starting point, not a suggestion to "
        f"ignore): {inputs.get('key_responsibilities')}\n"
        f"Education requirement: {inputs.get('education_degree_level')} "
        f"{inputs.get('education_field') or ''}\n"
        f"Preferred certifications: {inputs.get('preferred_certifications')}\n"
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
