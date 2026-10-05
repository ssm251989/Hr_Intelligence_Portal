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
    "remote-work preference. current_ctc / expected_ctc are ANNUAL amounts in rupees only if "
    "the resume states them (e.g. '12 LPA' -> 1200000); notice_period_days only if a notice "
    "period is stated (e.g. '2 months' -> 60, 'immediate joiner' -> 0); languages are spoken "
    "languages the resume lists, not programming languages. given_name / family_name split full_name "
    "into the person's given (first) name and family name (surname), using naming customs: many Indian "
    "names put the family name first (e.g. 'Gunda Kishore' -> given 'Kishore', family 'Gunda'); a leading "
    "initial is usually the family name ('G. Kishore' -> given 'Kishore'). Use null if you are not sure."
)

_client: Anthropic | None = None


GENAI_SETTINGS_URL = "/settings/integrations/ai"


class ResumeParsingError(Exception):
    """Raised when the AI resume-parsing call fails or returns unusable output.

    `code` + `message` say in plain words what went wrong and where to fix it (shown in the
    upload dialog and on the candidate page instead of a generic "couldn't parse")."""

    def __init__(self, message: str, code: str = "AI_ERROR", fix_url: Optional[str] = None):
        super().__init__(message)
        self.code, self.message, self.fix_url = code, message, fix_url

    def as_detail(self) -> dict:
        return {"code": self.code, "message": self.message, "fix_url": self.fix_url}


def explain_ai_error(exc: Exception) -> ResumeParsingError:
    """Turns an SDK / limit exception into a reason a recruiter can act on."""
    import anthropic

    from app.platform.ai.tracked import AIUsageBlocked

    if isinstance(exc, ResumeParsingError):
        return exc
    if isinstance(exc, AIUsageBlocked):
        return ResumeParsingError(f"{exc} (Settings > Integrations > GenAI)", "AI_LIMIT", GENAI_SETTINGS_URL)
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return ResumeParsingError("AI key not working - fix it in Settings > Integrations > GenAI.", "AI_KEY", GENAI_SETTINGS_URL)
    if isinstance(exc, anthropic.NotFoundError):
        return ResumeParsingError("The AI model chosen for resume parsing is not available - pick another in Settings > Integrations > GenAI.", "AI_MODEL", GENAI_SETTINGS_URL)
    if isinstance(exc, (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError)):
        return ResumeParsingError("The AI service is busy or unreachable - try again in a minute.", "AI_BUSY")
    if isinstance(exc, anthropic.BadRequestError):
        body = getattr(exc, "body", None) or {}
        msg = (body.get("error") or {}).get("message") if isinstance(body, dict) else None
        msg = msg or str(exc)
        if "credit" in msg.lower() or "billing" in msg.lower():
            return ResumeParsingError("The AI account has no credit left - top it up or change the key in Settings > Integrations > GenAI.", "AI_BILLING", GENAI_SETTINGS_URL)
        return ResumeParsingError(f"The AI service refused the request: {msg}", "AI_REQUEST")
    return ResumeParsingError(f"Failed to parse resume: {exc}", "AI_ERROR")


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
    given_name: Optional[str] = None  # fix 2026-10-05: the first name to greet them by (app/candidates/names.py)
    family_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    total_experience_years: Optional[float] = None
    skills: list[str] = []
    education: list[EducationItem] = []
    work_history: list[WorkHistoryItem] = []
    certificates: list[str] = []
    # Part 17.5/17.8: only when the resume states them (annual amounts in rupees; notice in days)
    current_ctc: Optional[float] = None
    expected_ctc: Optional[float] = None
    notice_period_days: Optional[int] = None
    languages: list[str] = []


def _get_client():
    """Part 18.23-18.25: the tracked client -- model from Settings > GenAI, fallback model,
    usage counted (tokens, cost, user, module) and limits applied."""
    from app.platform.ai.tracked import tracked_client

    return tracked_client(feature="recruitment.resume_parsing", model_key="resume_extraction")


def _resume_content(raw_resume_text: str, file_bytes: Optional[bytes], filename: Optional[str]):
    """The user message content: the text, or (scan / image with no usable text) the file itself."""
    from app.candidates.resume_extraction import needs_vision, vision_media_type

    media_type = vision_media_type(filename or "") if file_bytes else None
    if not needs_vision(raw_resume_text):
        return f"Resume text:\n{raw_resume_text}", False
    if media_type is None:
        raise ResumeParsingError("No readable text found in this file - upload a PDF or a clearer copy.", "EMPTY_FILE")
    import base64

    data = base64.standard_b64encode(file_bytes).decode()
    kind = "document" if media_type == "application/pdf" else "image"
    block = {"type": kind, "source": {"type": "base64", "media_type": media_type, "data": data}}
    return [block, {"type": "text", "text": "This resume is a scanned file / image. Read it and record its fields."}], True


def parse_resume(raw_resume_text: str, file_bytes: Optional[bytes] = None, filename: Optional[str] = None) -> dict:
    """Structured fields from one resume.

    Uses a forced tool call (the same shape as the batch path below): the strict structured-output
    mode rejected this schema with 400 "Schema is too complex." once 17.5/17.8 added the CTC /
    notice / language fields, which is why every upload said "Couldn't automatically parse".

    When the text layer is empty or too thin (a scanned / photographed resume) and the file is a
    PDF or an image, Claude reads the file itself (vision = the OCR step); the result then carries
    read_with="ocr" so the UI can say so."""
    content, use_vision = _resume_content(raw_resume_text, file_bytes, filename)
    try:
        response = _get_client().messages.create(
            model=MODEL,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
            tools=[_BATCH_TOOL],
            tool_choice={"type": "tool", "name": BATCH_TOOL_NAME},
        )
        result = extract_parsed_output_from_message(response)
    except Exception as exc:
        raise explain_ai_error(exc) from exc
    result["read_with"] = "ocr" if use_vision else "text"
    return result


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


def build_batch_request(custom_id: str, raw_resume_text: str, file_bytes: Optional[bytes] = None, filename: Optional[str] = None) -> dict:
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
    raise ResumeParsingError("The AI answer had no resume fields in it - try again.", "AI_EMPTY")
