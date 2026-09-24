"""Registers every setting key docs/HRMS_COMPLETE_SPEC.txt Part 2 section 6 calls out --
"move current literals here". Registering a key here is NOT the same as wiring its actual
consumption site to read from SettingsService instead of its current hardcoded constant or
own local settings row -- that migration belongs to whichever part actually owns that
consumer (Part 3 for connections/model routing, Part 4 for comms/branding, Part 8 for
recruitment negotiation/screening). This file's job is only to make every one of docs/
hardcode_inventory.md's business-rule/model-id entries a real, manageable SettingDef with
the SAME default the current hardcoded/DB-stored value already has, so nothing's runtime
behavior changes yet.

Once real per-module settings.py files exist (section E's package layout, as those modules
get built), each group below moves into the module that actually owns it; kept as one file
here since Part 2 predates all of them.
"""

from app.platform.ai import model_catalog
from app.platform.settings.registry import SettingDef, register

_registered = False


def register_all() -> None:
    """Idempotent -- safe to call from app startup and from test conftest without
    duplicate-registration errors."""
    global _registered
    if _registered:
        return

    # org.* -- section 6; org.display_name is THE hardcode_inventory.md's original
    # client-name offender's eventual home (Part 4/6 branding + i18n wire it up for real).
    # The PLATFORM default here is deliberately generic, never any specific tenant's own
    # legal/display name -- that's tenant #1's own DATA, seeded as a real tenant-scoped
    # setting_values row by hrctl.tenant bootstrap-existing (from its own --name argument,
    # never a literal), not baked into this schema-level default every future tenant would
    # otherwise inherit.
    register(SettingDef("org.display_name", "str", "", module="org", group="Organisation"))
    register(SettingDef("org.legal_name", "str", "", module="org", group="Organisation"))
    # Part 6 section 6 -- scopes_allowed widened to ("user","tenant") on these two
    # (originally tenant-only, Part 2): a user's own locale/timezone preference is now a
    # real per-user override layered above the tenant-wide default -- SCOPE_ORDER already
    # walks "user" before "tenant" for every setting, so this is the ONLY change needed to
    # make "locale/tz from layered settings (user > location > tenant)" (section 6's own
    # wording) real for its two implemented layers; "location" needs Part 7's org model.
    register(SettingDef("org.timezone", "str", "Asia/Kolkata", module="org", group="Organisation", scopes_allowed=("user", "tenant")))
    register(SettingDef("org.locale", "str", "en-IN", module="org", group="Organisation", scopes_allowed=("user", "tenant")))
    register(SettingDef("org.currency", "str", "INR", module="org", group="Organisation"))
    register(SettingDef("org.date_format", "str", "DD MMM YYYY", module="org", group="Organisation"))
    register(SettingDef("org.week_start", "str", "Monday", module="org", group="Organisation"))
    register(SettingDef("org.fiscal_year_start", "str", "04-01", module="org", group="Organisation"))
    # Part 6 section 5/7 -- bootstrap's own branding.support_contact/legal_links.
    register(SettingDef("org.support_email", "email", "", module="org", group="Organisation"))
    register(SettingDef("org.legal_links", "json", [], module="org", group="Organisation"))

    # recruitment.screening.* -- current defaults from app/screening/service.py's
    # ScreeningSettings singleton row (see docs/hardcode_inventory.md).
    register(SettingDef(
        "recruitment.screening.weights", "json",
        {"skills": 0.5, "experience": 0.3, "education": 0.2},
        module="recruitment", group="Screening",
    ))
    register(SettingDef(
        "recruitment.screening.composite_formula", "json",
        {"expression": "skills*weights.skills + experience*weights.experience + education*weights.education"},
        module="recruitment", group="Screening",
    ))
    register(SettingDef("recruitment.screening.dashboard_min_score", "int", 60, module="recruitment", group="Screening"))
    register(SettingDef("recruitment.screening.dashboard_max_score", "int", 100, module="recruitment", group="Screening"))
    register(SettingDef("recruitment.screening.interview_min_score", "int", 75, module="recruitment", group="Screening"))
    register(SettingDef("recruitment.screening.interview_max_score", "int", 100, module="recruitment", group="Screening"))
    register(SettingDef("recruitment.screening.auto_shortlist_threshold", "int", 75, module="recruitment", group="Screening"))

    # recruitment.negotiation.* -- current defaults from
    # app/interview_scheduling/negotiation.py's own module constants.
    register(SettingDef("recruitment.negotiation.slots_offered", "int", 3, module="recruitment", group="Interview Negotiation"))
    register(SettingDef("recruitment.negotiation.slots_to_pick", "int", 2, module="recruitment", group="Interview Negotiation"))
    register(SettingDef("recruitment.negotiation.retry_day_offset", "int", 1, module="recruitment", group="Interview Negotiation"))
    register(SettingDef("recruitment.negotiation.max_retry_days", "int", 1, module="recruitment", group="Interview Negotiation"))
    register(SettingDef(
        "recruitment.negotiation.busy_source", "enum", "internal", module="recruitment",
        group="Interview Negotiation", json_schema={"enum": ["internal", "excel", "calendar"]},
    ))

    # recruitment.tracker.* -- current defaults from
    # app/interview_scheduling/tracker.py's own module constants + InterviewSchedulingSettings.
    register(SettingDef("recruitment.tracker.excel.path", "str", "", module="recruitment", group="Interview Tracker", sensitive=False))
    register(SettingDef(
        "recruitment.tracker.excel.sheet_names", "json",
        {"interviewer_pool": "Interviewer Pool", "interview_log": "Interview Log", "mails": "Mails"},
        module="recruitment", group="Interview Tracker",
    ))
    register(SettingDef("recruitment.tracker.save_retry.attempts", "int", 5, module="recruitment", group="Interview Tracker"))
    register(SettingDef("recruitment.tracker.save_retry.backoff_seconds", "decimal", 0.5, module="recruitment", group="Interview Tracker"))

    # ai.models.* -- current defaults from each backend/app/ai_services/*.py MODEL
    # constant (see docs/hardcode_inventory.md's model-id offender group). Type "str" for
    # now (just the model id) -- becomes "connection_ref" once Part 3's LLM gateway and
    # purpose-based routing exist and these move to ai.gateway.complete(purpose=...) calls.
    register(SettingDef("ai.models.resume_extraction", "str", model_catalog.RESUME_EXTRACTION, module="ai", group="AI Models"))
    register(SettingDef("ai.models.resume_matching", "str", model_catalog.RESUME_MATCHING, module="ai", group="AI Models"))
    register(SettingDef("ai.models.candidate_ranking", "str", model_catalog.CANDIDATE_RANKING, module="ai", group="AI Models"))
    register(SettingDef("ai.models.shortlist_feedback", "str", model_catalog.SHORTLIST_FEEDBACK, module="ai", group="AI Models"))
    register(SettingDef("ai.models.interview_questions", "str", model_catalog.INTERVIEW_QUESTIONS, module="ai", group="AI Models"))
    register(SettingDef("ai.models.document_validation", "str", model_catalog.DOCUMENT_VALIDATION, module="ai", group="AI Models"))
    register(SettingDef("ai.models.offer_letter_generation", "str", model_catalog.OFFER_LETTER_GENERATION, module="ai", group="AI Models"))
    register(SettingDef("ai.models.jd_generation", "str", model_catalog.JD_GENERATION, module="ai", group="AI Models"))

    # iam.auth.* -- Part 5A section 1's own per-tenant-configurable auth policy. Platform
    # defaults are conservative but NOT locked-on (mfa_required defaults false) --
    # flipping mfa_required on for a real, already-logged-in tenant is this tenant's own
    # decision to make once its users have actually enrolled, not something this build
    # should force silently (see docs/build_log.md's own Part 5 note: forcing this on
    # would lock the real tenant #1 out of its own live app without warning).
    register(SettingDef("iam.auth.password_min_length", "int", 8, module="iam", group="Authentication"))
    register(SettingDef("iam.auth.password_require_complexity", "bool", False, module="iam", group="Authentication"))
    register(SettingDef("iam.auth.password_expiry_days", "int", 0, module="iam", group="Authentication"))  # 0 = never expires
    register(SettingDef("iam.auth.password_history_count", "int", 3, module="iam", group="Authentication"))
    register(SettingDef("iam.auth.lockout_threshold", "int", 5, module="iam", group="Authentication"))
    register(SettingDef("iam.auth.lockout_duration_minutes", "int", 15, module="iam", group="Authentication"))
    register(SettingDef("iam.auth.mfa_required", "bool", False, module="iam", group="Authentication"))
    register(SettingDef("iam.auth.remember_device_days", "int", 30, module="iam", group="Authentication"))
    register(SettingDef("iam.auth.access_token_expiry_minutes", "int", 480, module="iam", group="Authentication"))
    register(SettingDef("iam.auth.refresh_token_expiry_days", "int", 30, module="iam", group="Authentication"))
    register(SettingDef("iam.auth.ip_allowlist", "json", [], module="iam", group="Authentication"))  # [] = unrestricted

    _registered = True
