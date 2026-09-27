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
    # Part 17.3 maps: tile server (any OpenStreetMap-style {z}/{x}/{y} URL), whether unknown
    # places may be looked up online through the geocoding connection, and which countries
    # a point may fall in (ISO codes; India only by default).
    register(SettingDef("geo.tile_url", "str", "https://tile.openstreetmap.org/{z}/{x}/{y}.png", module="geo", group="Maps"))
    register(SettingDef("geo.tile_attribution", "str", "&copy; OpenStreetMap contributors", module="geo", group="Maps"))
    register(SettingDef("geo.online_lookup", "bool", True, module="geo", group="Maps"))
    register(SettingDef("geo.countries", "json", ["IN"], module="geo", group="Maps"))
    register(SettingDef("org.timezone", "str", "Asia/Kolkata", module="org", group="Organisation", scopes_allowed=("user", "tenant")))
    register(SettingDef("org.locale", "str", "en-IN", module="org", group="Organisation", scopes_allowed=("user", "tenant")))
    register(SettingDef("org.currency", "str", "INR", module="org", group="Organisation"))
    register(SettingDef("org.date_format", "str", "DD MMM YYYY", module="org", group="Organisation"))
    register(SettingDef("org.week_start", "str", "Monday", module="org", group="Organisation"))
    register(SettingDef("org.fiscal_year_start", "str", "04-01", module="org", group="Organisation"))
    # Part 6 section 5/7 -- bootstrap's own branding.support_contact/legal_links.
    register(SettingDef("org.support_email", "email", "", module="org", group="Organisation"))
    register(SettingDef("org.legal_links", "json", [], module="org", group="Organisation"))

    # Part 17.4: ONE threshold everywhere -- "Shortlist threshold" on the one "Match score
    # (0-100)" (per job in the job's shortlisting rules; this is the company default). It
    # replaces recruitment.screening.{dashboard,interview}_{min,max}_score,
    # auto_shortlist_threshold, weights and composite_formula (the weights now live in the
    # versioned scoring rules, app/recruitment/scoring/); the migration copied each
    # company's interview-ready mark into it. Old stored rows are left untouched.
    register(SettingDef("recruitment.scoring.shortlist_threshold", "int", 75, module="recruitment", group="Scoring",
                        json_schema={"type": "integer", "minimum": 0, "maximum": 100}))
    # Part 17.6: automated shortlisting -- company defaults, each job can override them
    # (job_roles.shortlisting_json). Off by default: a company switches it on deliberately.
    register(SettingDef("recruitment.shortlisting.auto_shortlist", "bool", False, module="recruitment", group="Shortlisting"))
    register(SettingDef("recruitment.shortlisting.undo_hours", "int", 4, module="recruitment", group="Shortlisting",
                        json_schema={"type": "integer", "minimum": 0, "maximum": 72}))
    register(SettingDef("recruitment.shortlisting.max_size", "int", 0, module="recruitment", group="Shortlisting",
                        json_schema={"type": "integer", "minimum": 0}))
    register(SettingDef("recruitment.shortlisting.notify", "json", ["job_owner"], module="recruitment", group="Shortlisting"))
    # Part 17.8: salary collection + band check. Above the band by at most approval_margin_pct
    # -> approval request (to `approvers`, else the job's hiring manager, else admins); more ->
    # flagged. The offer suggestion adds target_hike_pct to the current CTC, kept in the band.
    register(SettingDef("recruitment.careers.ask_salary", "bool", True, module="recruitment", group="Careers site"))
    register(SettingDef("recruitment.salary.ask_after_shortlist", "bool", True, module="recruitment", group="Salary"))
    register(SettingDef("recruitment.salary.approval_margin_pct", "int", 10, module="recruitment", group="Salary",
                        json_schema={"type": "integer", "minimum": 0, "maximum": 100}))
    register(SettingDef("recruitment.salary.target_hike_pct", "int", 20, module="recruitment", group="Salary",
                        json_schema={"type": "integer", "minimum": 0, "maximum": 200}))
    register(SettingDef("recruitment.salary.approvers", "json", [], module="recruitment", group="Salary"))
    # Part 17.15: removed candidates stay in the Recycle bin this many days, then are deleted permanently
    register(SettingDef("recruitment.candidates.recycle_days", "int", 30, module="recruitment", group="Candidates",
                        json_schema={"type": "integer", "minimum": 1, "maximum": 365}))
    # Part 17.13: automatic reminders (in-app, at most once a day each)
    register(SettingDef("recruitment.reminders.enabled", "bool", True, module="recruitment", group="Reminders"))
    register(SettingDef("recruitment.reminders.approval_hours", "int", 24, module="recruitment", group="Reminders",
                        json_schema={"type": "integer", "minimum": 1, "maximum": 720}))
    register(SettingDef("recruitment.reminders.scorecard_hours", "int", 24, module="recruitment", group="Reminders",
                        json_schema={"type": "integer", "minimum": 1, "maximum": 720}))
    register(SettingDef("recruitment.reminders.offer_expiry_days", "int", 2, module="recruitment", group="Reminders",
                        json_schema={"type": "integer", "minimum": 0, "maximum": 30}))
    register(SettingDef("recruitment.reminders.documents_days", "int", 3, module="recruitment", group="Reminders",
                        json_schema={"type": "integer", "minimum": 0, "maximum": 30}))

    # recruitment.negotiation.* -- current defaults from
    # app/interview_scheduling/negotiation.py's own module constants.
    register(SettingDef("recruitment.negotiation.slots_offered", "int", 3, module="recruitment", group="Interview Negotiation"))
    register(SettingDef("recruitment.negotiation.slots_to_pick", "int", 2, module="recruitment", group="Interview Negotiation"))
    register(SettingDef("recruitment.negotiation.retry_day_offset", "int", 1, module="recruitment", group="Interview Negotiation"))
    register(SettingDef("recruitment.negotiation.max_retry_days", "int", 1, module="recruitment", group="Interview Negotiation"))
    register(SettingDef(
        "recruitment.negotiation.busy_source", "enum", "internal", module="recruitment",
        group="Interview Negotiation", json_schema={"enum": ["internal", "calendar"]},  # Part 17.12: no Excel
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

    # onboarding.* -- Part 9: pre-boarding portal + BGV + conversion policy.
    register(SettingDef("onboarding.portal.link_ttl_days", "int", 45, module="onboarding", group="Pre-boarding"))
    register(SettingDef("onboarding.portal.required_forms", "json", [], module="onboarding", group="Pre-boarding"))  # [form key]
    register(SettingDef("onboarding.portal.required_policies", "json", [], module="onboarding", group="Pre-boarding"))  # [policy code]
    register(SettingDef("onboarding.documents.required_types", "json", [], module="onboarding", group="Pre-boarding"))  # [document_type master code]
    register(SettingDef("onboarding.bgv.default_package", "json", ["identity", "education", "employment"], module="onboarding", group="Background Verification"))
    register(SettingDef("onboarding.bgv.block_conversion_until_clear", "bool", False, module="onboarding", group="Background Verification"))
    register(SettingDef("onboarding.conversion.default_plan_template", "str", "", module="onboarding", group="Conversion"))

    # performance.* -- Part 10.
    register(SettingDef("performance.goals.weightage_rules", "json", {"total": 100, "min_goals": None, "max_goals": None, "min_per_goal": None}, module="performance", group="Goals"))
    # Generic, non-client-specific starter list for the review bias-language check; each
    # tenant edits its own.
    register(SettingDef(
        "performance.ai.bias_terms", "json",
        ["abrasive", "aggressive", "bossy", "emotional", "hysterical", "shrill", "young", "old", "energetic", "mature", "maternal", "pushy", "cultural fit"],
        module="performance", group="Reviews",
    ))

    # helpdesk.* / separation.* -- Part 11.
    register(SettingDef("helpdesk.email.default_category", "str", "", module="helpdesk", group="Helpdesk"))  # a ticket_category code
    register(SettingDef("separation.default_notice_days", "int", 30, module="separation", group="Separation"))
    register(SettingDef("separation.retention_step_enabled", "bool", False, module="separation", group="Separation"))
    register(SettingDef("separation.require_shortfall_cover", "bool", True, module="separation", group="Separation"))
    register(SettingDef("separation.relieving_letter_template", "str", "", module="separation", group="Separation"))  # a letter template key
    register(SettingDef("separation.experience_letter_template", "str", "", module="separation", group="Separation"))
    # Generic starter checklist; every tenant edits its own departments/items.
    register(SettingDef("separation.clearance_checklist", "json", [
        {"department": "it", "title": "Revoke system and email access", "kind": "access_revocation"},
        {"department": "admin", "title": "Return ID / access card"},
        {"department": "finance", "title": "Settle advances and reimbursements"},
        {"department": "manager", "title": "Handover sign-off"},
        {"department": "hr", "title": "Exit interview and documents", "blocks_relieving": False},
    ], module="separation", group="Separation"))

    # ai.* governance -- Part 12 section D.
    register(SettingDef("ai.enabled", "bool", True, module="ai", group="AI Governance"))
    register(SettingDef("ai.features.disabled", "json", [], module="ai", group="AI Governance"))  # feature codes or "<module>.*"
    register(SettingDef("ai.redaction.enabled", "bool", True, module="ai", group="AI Governance"))
    register(SettingDef("ai.redaction.patterns", "json", {
        "email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        "phone": r"(?<!\d)(?:\+?\d{1,3}[\s-]?)?\d{10}(?!\d)",
        "pan": r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",
        "aadhaar": r"\b\d{4}\s?\d{4}\s?\d{4}\b",
    }, module="ai", group="AI Governance"))
    register(SettingDef("ai.pricing", "json", {}, module="ai", group="AI Governance"))  # {model: {input_per_mtok, output_per_mtok}}
    # privacy.* -- Part 13 section E (DPDP). Defaults are conservative starting points each
    # tenant's DPO confirms; ex_employee ~8 years covers common Indian statutory retention.
    register(SettingDef("privacy.dpr_sla_days", "int", 30, module="privacy", group="Privacy"))
    register(SettingDef("privacy.retention_days", "json", {"candidate_unhired": 730, "ex_employee": 2920, "copilot_conversations": 365},
                        module="privacy", group="Privacy"))
    register(SettingDef("analytics.diversity.enabled", "bool", False, module="analytics", group="Analytics"))  # opt-in (spec A.4)
    register(SettingDef("analytics.diversity.min_group_size", "int", 5, module="analytics", group="Analytics"))
    register(SettingDef("analytics.recruiting_spend_ytd", "decimal", 0, module="analytics", group="Analytics"))
    register(SettingDef("copilot.languages", "json", ["en", "hi", "ta"], module="copilot", group="HR Copilot"))
    register(SettingDef("copilot.min_confidence", "decimal", 0.35, module="copilot", group="HR Copilot"))
    register(SettingDef("copilot.handover_category", "str", "", module="copilot", group="HR Copilot"))  # a ticket_category code

    # Part 14: module enablement (within the licence), setup wizard, per-user UX prefs.
    register(SettingDef("platform.modules.enabled", "json",
                        ["recruitment", "onboarding", "core_hr", "performance", "helpdesk", "assets", "separation", "analytics", "copilot"],
                        module="platform", group="Modules"))
    register(SettingDef("platform.setup.skipped", "json", [], module="platform", group="Setup"))
    register(SettingDef("platform.setup.config_pack", "json", {}, module="platform", group="Setup"))  # which pack was applied (Setup Wizard)
    register(SettingDef("ux.reduce_motion", "bool", False, module="ux", group="Accessibility", scopes_allowed=("user", "tenant")))
    register(SettingDef("ux.page_size", "int", 25, module="ux", group="Lists", scopes_allowed=("user", "tenant")))
    # Part 15.5: home widget layouts -- the user's own ({kind: [{i,x,y,w,h}]}) and the company
    # default per home (hr / manager / employee), set by an admin.
    register(SettingDef("ux.home_layout", "json", {}, module="ux", group="Home page", scopes_allowed=("user",)))
    for _kind in ("hr", "manager", "employee"):
        register(SettingDef(f"ux.home_default_{_kind}", "json", [], module="ux", group="Home page"))

    # Part 15.4: careers site sections the company writes itself (A6) -- empty = section hidden.
    register(SettingDef("careers.site.intro", "str", "", module="careers", group="Careers site"))
    register(SettingDef("careers.site.benefits", "json", [], module="careers", group="Careers site"))
    register(SettingDef("careers.site.faq", "json", [], module="careers", group="Careers site"))
    register(SettingDef("org.rtl_locales", "json", ["ar", "he", "fa", "ur"], module="org", group="Organisation"))

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
