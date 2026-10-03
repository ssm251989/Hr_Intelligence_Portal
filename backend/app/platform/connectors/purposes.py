"""Purpose registry (docs/HRMS_COMPLETE_SPEC.txt Part 3 section 4) -- extensible by
modules (each module registers the purposes it needs in its own settings.py once that
module exists); this file seeds the ones the spec names now plus a fallback chain for
"no route configured for the specific purpose, try the more general one first"."""

_PURPOSES: set[str] = set()
_FALLBACK_CHAIN: dict[str, str] = {}


def register_purpose(purpose: str, *, fallback: str | None = None) -> None:
    _PURPOSES.add(purpose)
    if fallback is not None:
        _FALLBACK_CHAIN[purpose] = fallback


def all_purposes() -> list[str]:
    return sorted(_PURPOSES)


def fallback_for(purpose: str) -> str | None:
    return _FALLBACK_CHAIN.get(purpose)


# Part 16.2: what a purpose means in plain words (purpose keys are never shown to people)
_PLAIN = (
    ("email.outbound.", "The company mailbox (sending email)"), ("email.inbound.", "The company mailbox (reading replies)"),
    ("calendar.", "A calendar (Google or Outlook)"), ("meeting.", "A video-meeting service (Google Meet, Teams or Zoom)"),
    ("llm.", "The AI service (Settings > Integrations > GenAI)"), ("esign.", "E-signing (DocuSign or Leegality)"),
    ("bgv.", "A background-check provider"), ("storage.", "File storage"), ("geo.", "Maps"), ("chat.", "Team chat"),
    ("analytics.", "The data warehouse"),
)


def plain_name(purpose: str) -> str:
    if purpose.startswith("jobboard."):
        return f"The {purpose.split('.', 1)[1].replace('_', ' ').title()} job board"
    return next((name for prefix, name in _PLAIN if purpose.startswith(prefix)), "A connected service")


def _register_all() -> None:
    if _PURPOSES:
        return
    register_purpose("email.outbound.default")
    register_purpose("email.outbound.recruitment", fallback="email.outbound.default")
    register_purpose("email.outbound.interview_negotiation", fallback="email.outbound.recruitment")
    register_purpose("email.outbound.onboarding", fallback="email.outbound.default")
    register_purpose("email.outbound.hr_letters", fallback="email.outbound.default")
    register_purpose("email.outbound.system", fallback="email.outbound.default")
    # Part 18.2: one company mailbox -- every inbound purpose falls back to the default one
    register_purpose("email.inbound.default")
    register_purpose("email.inbound.negotiation_replies", fallback="email.inbound.default")
    register_purpose("email.inbound.candidate_applications", fallback="email.inbound.default")
    register_purpose("calendar.interviews")
    register_purpose("meeting.interviews")
    register_purpose("chat.hr_alerts")
    register_purpose("storage.documents")
    register_purpose("geo.geocoding")  # Part 17.3: place name / PIN -> map coordinates
    register_purpose("storage.exports")
    register_purpose("llm.resume_extraction")
    register_purpose("llm.scoring")
    register_purpose("llm.judgment")
    register_purpose("llm.copilot")
    register_purpose("llm.embeddings")
    register_purpose("esign.offer_letters")
    register_purpose("bgv.default")
    register_purpose("jobboard.linkedin")
    register_purpose("jobboard.naukri")
    register_purpose("jobboard.indeed")
    register_purpose("meeting.google_meet")
    register_purpose("meeting.teams")
    register_purpose("meeting.zoom")
    # Parts 11-12
    register_purpose("email.inbound.helpdesk", fallback="email.inbound.default")
    register_purpose("email.outbound.helpdesk", fallback="email.outbound.default")
    register_purpose("email.outbound.reports", fallback="email.outbound.default")
    register_purpose("analytics.warehouse_push")


_register_all()
