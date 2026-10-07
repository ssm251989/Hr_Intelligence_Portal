"""Contextual help for every setting (docs/HRMS_COMPLETE_SPEC.txt Part 14 section 11: "every
setting has help text (i18n) + 'what this affects' preview").

English text lives here as the base catalogue; `settings.help.<key>` / `settings.affects.<key>`
i18n keys override it per locale (tenant overrides via Part 6 i18n_overrides too), so the
Settings UI always has something to show and translations can be added without code.
`test_every_setting_has_help` keeps this complete as settings are added.
"""

from typing import Optional

# key -> (help, affects)
HELP: dict[str, tuple[str, str]] = {
    # ---- organisation ----
    "org.display_name": ("The name people see in the app, emails and the career site.", "Page titles, email headers/footers, career site, letters"),
    "org.legal_name": ("The registered legal name used on letters and legal notices.", "Offer/relieving letters, privacy notice, invoices exported to finance"),
    "org.timezone": ("Default timezone for dates, reminders and schedules. Users can pick their own.", "Interview times, reminders, report delivery hour, SLA calendars without a location calendar"),
    "org.locale": ("Default language and number/date formatting.", "UI language, email language when a person has no preference"),
    "org.currency": ("Default currency for salaries, offers and budgets.", "Offer CTC, salary bands, compensation planning"),
    "org.date_format": ("How dates are displayed.", "Every date shown in the app and in emails"),
    "org.week_start": ("First day of the week in calendars.", "Interview calendar, weekly report schedules"),
    "org.fiscal_year_start": ("Month-day your financial year starts (MM-DD).", "Budget periods, year-to-date analytics"),
    "org.support_email": ("Where people are told to write for help.", "Email footers, error pages, the career site"),
    "org.legal_links": ("Links to your privacy policy, terms and similar pages.", "Career site footer, login page, email footers"),
    "org.rtl_locales": ("Languages that read right-to-left.", "Page direction for users in those languages"),
    # ---- AI ----
    "ai.enabled": ("Master switch for every AI feature in your organisation.", "Screening, JD drafts, HR Copilot, agents, review drafts, predictive estimates"),
    "ai.features.disabled": ("Turn off individual AI features (or a whole module with 'module.*').", "Which AI buttons and assistants people see"),
    "ai.models.candidate_ranking": ("Model used to rank candidates for a job.", "Shortlisting suggestions"),
    "ai.models.document_validation": ("Model used to check uploaded documents.", "BGV document checks"),
    "ai.models.interview_questions": ("Model used to suggest interview questions.", "Interview prep and scorecards"),
    "ai.models.jd_generation": ("Model used to draft job descriptions.", "Job wizard AI draft, recruiter agent"),
    "ai.models.offer_letter_generation": ("Model used to draft offer letters.", "Offer drafting"),
    "ai.models.resume_extraction": ("Model used to read resumes and documents.", "Resume parsing, pre-boarding document prefill"),
    "ai.models.resume_matching": ("Model used to score resumes against jobs.", "Screening scores"),
    "ai.models.shortlist_feedback": ("Model used to explain shortlist decisions.", "Shortlist feedback text"),
    "ai.pricing": ("Price per million tokens for each model, for usage cost reports.", "AI usage costs and budget cut-offs"),
    "ai.redaction.enabled": ("Remove personal identifiers before text is sent to an AI model.", "Every AI request except document extraction"),
    "ai.redaction.patterns": ("Patterns that are redacted (emails, phone numbers, PAN, Aadhaar...).", "What personal data AI providers can see"),
    # ---- analytics ----
    "analytics.diversity.enabled": ("Allow aggregate diversity reporting. Off by default.", "Diversity metric on dashboards"),
    "analytics.diversity.min_group_size": ("Groups smaller than this are merged into 'other' so no one is identifiable.", "Diversity metric"),
    "analytics.recruiting_spend_ytd": ("Your recruiting spend this year, used to compute cost-per-hire.", "Cost-per-hire metric"),
    # ---- copilot ----
    "copilot.handover_category": ("Helpdesk category used when HR Copilot hands a question to a person.", "Tickets created from Copilot"),
    "copilot.languages": ("Languages HR Copilot may answer in.", "Copilot language picker and answers"),
    "copilot.min_confidence": ("Below this match confidence Copilot hands over instead of answering (0-1).", "How often Copilot answers vs raises a ticket"),
    # ---- helpdesk ----
    "helpdesk.email.default_category": ("Category given to tickets created from emails.", "Email-to-ticket"),
    # ---- IAM ----
    "iam.auth.access_token_expiry_minutes": ("How long a sign-in lasts before it must be refreshed.", "Every user session"),
    "iam.auth.ip_allowlist": ("If set, sign-in is only allowed from these IP ranges.", "Who can sign in, from where"),
    "iam.auth.lockout_duration_minutes": ("How long an account stays locked after too many failed sign-ins.", "Sign-in"),
    "iam.auth.lockout_threshold": ("Failed sign-ins allowed before the account locks.", "Sign-in"),
    "iam.auth.mfa_required": ("Require 2-step verification for every user.", "Sign-in for all users; users without it are asked to enrol"),
    "iam.auth.password_expiry_days": ("Force a password change after this many days (0 = never).", "Sign-in"),
    "iam.auth.password_history_count": ("How many previous passwords cannot be reused.", "Password changes"),
    "iam.auth.password_min_length": ("Minimum password length.", "New passwords and invitations"),
    "iam.auth.password_require_complexity": ("Require letters, numbers and symbols in passwords.", "New passwords"),
    "iam.auth.refresh_token_expiry_days": ("How long 'stay signed in' lasts.", "Every user session"),
    "iam.auth.remember_device_days": ("How long a trusted device skips the 2-step code.", "Sign-in"),
    # ---- onboarding ----
    "onboarding.bgv.block_conversion_until_clear": ("Don't let a new hire become an employee until background checks are cleared.", "Mark-as-joined"),
    "onboarding.bgv.default_package": ("Checks run by default in background verification.", "New BGV cases"),
    "onboarding.conversion.default_plan_template": ("Onboarding plan used when no assignment rule matches.", "New joiners' task lists"),
    "onboarding.documents.required_types": ("Documents every new hire must upload.", "Pre-joining portal checklist and readiness %"),
    "onboarding.portal.link_ttl_days": ("How long a pre-joining portal link works.", "Pre-joining portal access"),
    "onboarding.portal.required_forms": ("Forms every new hire must fill in.", "Pre-joining portal checklist and readiness %"),
    "onboarding.portal.required_policies": ("Policies every new hire must acknowledge.", "Pre-joining portal checklist and readiness %"),
    # ---- performance ----
    "performance.ai.bias_terms": ("Words flagged in AI review drafts as possibly biased.", "Review draft warnings"),
    "performance.goals.weightage_rules": ("Rules goal weightages must follow (total, min/max goals).", "Goal setting and validation"),
    # ---- privacy ----
    "privacy.dpr_sla_days": ("Days you have to complete a data principal request.", "Due dates and overdue alerts for privacy requests"),
    "privacy.retention_days": ("How long each kind of personal data is kept before purge is proposed.", "Retention dry-runs (purges always need approval)"),
    # ---- recruitment ----
    "recruitment.scoring.shortlist_threshold": ("Match score (0-100) at or above which a candidate is suggested for the shortlist (never auto-rejected). Each job can set its own.", "Shortlisting"),
    "recruitment.negotiation.busy_source": ("Where interviewer availability is read from.", "Automatic interview slot negotiation"),
    "recruitment.negotiation.max_retry_days": ("How many extra days to try when no slot works.", "Interview negotiation"),
    "recruitment.negotiation.retry_day_offset": ("How many days later the next attempt starts.", "Interview negotiation"),
    "recruitment.negotiation.slots_offered": ("How many slots a candidate is offered.", "Interview negotiation emails"),
    "recruitment.negotiation.slots_to_pick": ("How many slots a candidate must pick.", "Interview negotiation form"),
    "recruitment.tracker.excel.path": ("Location of the interview tracker workbook (if you use one).", "Excel interviewer availability"),
    "recruitment.tracker.excel.sheet_names": ("Sheet names inside the tracker workbook.", "Excel interviewer availability"),
    "recruitment.tracker.save_retry.attempts": ("Retries when the tracker is open in Excel.", "Saving interview results to the tracker"),
    "recruitment.tracker.save_retry.backoff_seconds": ("Wait between those retries.", "Saving interview results to the tracker"),
    # ---- separation ----
    "separation.clearance_checklist": ("Clearance items created for every leaver.", "Exit clearance board"),
    "separation.default_notice_days": ("Notice period when the employee record and masters don't specify one.", "Last working day calculation"),
    "separation.experience_letter_template": ("Letter template used for experience letters.", "Exit letters"),
    "separation.relieving_letter_template": ("Letter template used for relieving letters.", "Exit letters"),
    "separation.require_shortfall_cover": ("Require notice shortfall to be waived or bought out before approving an early last day.", "LWD approval"),
    "separation.retention_step_enabled": ("Add a retention discussion step to every resignation.", "Resignation workflow"),
    # ---- platform / UX (Part 14) ----
    "platform.modules.enabled": ("Modules switched on for your organisation (within your licence).", "Menus, pages and APIs people can reach"),
    "platform.setup.skipped": ("Setup Wizard steps an admin chose to skip.", "Setup checklist on the admin home"),
    "recruitment.bgv.vendor_link_days": ("Days a BGV vendor's secure link works (it shows only that candidate's documents and takes their report).", "Background checks"),
    "recruitment.jobs.recycle_enabled": ("Move closed jobs to the Recycle bin automatically (job + its applications, interviews, forms). Hired people are never touched.", "Jobs, Recycle bin"),
    "recruitment.jobs.recycle_after_days": ("Days after a job is closed before it moves to the Recycle bin (0 = at the next daily run).", "Jobs, Recycle bin"),
    "recruitment.jobs.keep_candidates_in_pool": ("When a closed job goes to the bin, keep its candidates' profiles and resumes in the talent pool (only the job's own data moves).", "Candidates, Recycle bin"),
    "org.address": ("Registered office address, printed in the footer of every letter.", "Letters"),
    "org.cin": ("Corporate Identity Number (CIN), printed in the footer of every letter.", "Letters"),
    "letters.signatory_name": ("Who signs letters (name under the signature).", "Letters"),
    "letters.signatory_designation": ("The signatory's designation, e.g. Head of HR.", "Letters"),
    "letters.watermark": ("A faint watermark of the company logo behind the letter text.", "Letters"),
    "letters.celebration": ("Confetti and a Congratulations ribbon on offer and joining letters (never on relieving / experience letters).", "Letters"),
    "letters.brand_colour": ("Colour of the letter header band (empty = the company brand colour).", "Letters"),
    "employees.roles.notify_on_change": ("When HR changes someone's app roles (Employees > Assign roles), email them \"Your access was updated\" with their roles now.", "Employees, Assign roles"),
    "employees.after_exit.move_hiring_data": ("When an exit is completed, move the person's hiring data (candidate record, applications, interviews, links, inbox emails, portal) to the Recycle bin. Employee record, signed offer, joining documents, BGV, letters and the exit record are kept.", "Exits, Recycle bin"),
    "employees.after_exit.days": ("Days after the exit is completed before the hiring data moves (0 = straight away).", "Exits, Recycle bin"),
    "employees.after_exit.categories": ("Which hiring data moves to the Recycle bin on exit.", "Exits, Recycle bin"),
    "employees.on_onboarding_complete": ("When onboarding completes: 'approve' = the agent prepares the employee and HR approves with one click; 'automatic' = created straight away.", "Onboarding > Mark as joined, Employees"),
    "employees.email.domain": ("The domain of company email addresses (e.g. ctdtechs.com). Empty = the domain your admins sign in with.", "New employees' company email"),
    "employees.email.pattern": ("How a company email address is made, e.g. {first}.{last} -> kishore.gunda.", "New employees' company email"),
    "employees.email.fallbacks": ("Patterns tried when the first address is taken, e.g. {first}.{l}, {first}.{last}{n}.", "New employees' company email"),
    "employees.default_roles": ("App roles every new employee gets.", "New employees' app account"),
    "employees.role_rules": ("Extra roles by designation or department, e.g. designation contains 'Interviewer' -> Interviewer.", "New employees' app account"),
    "employees.notice_days": ("Notice period in days by employment type (used for the proposed last working day when someone resigns).", "Resignation form"),
    "employees.exit.approval_steps": ("Who approves a resignation, in order: manager, hr.", "Employee exits"),
    "employees.exit.clearance_items": ("The clearance checklist for every exit, with owners.", "Employee exits"),
    "employees.interviewer.auto_rules": ("Make people interviewers automatically by designation or department.", "Employees > Make interviewer"),
    "employees.interviewer.scorecard_reminder_hours": ("Remind an interviewer this many hours after the interview if the scorecard isn't in.", "Interviewer reminders"),
    "employees.exit_interview": ("The exit interview questions the leaving employee answers (text, stars, Yes/Maybe/No, choice), which are required, AI summary on/off and reminder days before the last working day.",
                                 "Employee's exit page; HR's exit page (read-only)"),
    "employees.letters.relieving_template": ("Letter template used for the relieving letter.", "Employee exits"),
    "employees.letters.experience_template": ("Letter template used for the experience letter.", "Employee exits"),
    "onboarding.joining_form": ("Which joining-details fields and documents are required, optional or hidden, with help text and format checks. Every field is optional unless set here.",
                                "The joiner's welcome portal and HR's onboarding view"),
    "platform.health.ignored": ("Configuration health checks an admin chose to ignore because the company doesn't need them.", "Configuration health on the admin home"),
    "platform.setup.config_pack": ("Which configuration pack was applied during setup.", "Setup checklist"),
    "ux.reduce_motion": ("Turn off animations and celebrations.", "All motion in the app for this user"),
    "ux.page_size": ("Rows per page in lists.", "Every list"),
    "ux.home_layout": ("How this person arranged the boxes on their home page.", "Their own home page"),
    "ux.home_default_hr": ("The starting layout of the HR home page for your company.", "HR home page for anyone who hasn't arranged their own"),
    "ux.home_default_manager": ("The starting layout of the manager home page for your company.", "Manager home page for anyone who hasn't arranged their own"),
    "careers.site.intro": ("A short welcome at the top of your careers site.", "Careers site home"),
    "careers.site.benefits": ("Benefits shown on your careers site: a list of {title, body, emoji}.", "Careers site benefits section"),
    "careers.site.faq": ("Questions and answers for applicants: a list of {question, answer}.", "Careers site FAQ"),
    "ux.home_default_employee": ("The starting layout of the employee home page for your company.", "Employee home page for anyone who hasn't arranged their own"),
}


def help_for(key: str) -> Optional[dict]:
    entry = HELP.get(key)
    if entry is None:
        return None
    return {"help": entry[0], "affects": entry[1], "help_i18n_key": f"settings.help.{key}", "affects_i18n_key": f"settings.affects.{key}"}


def missing_help(keys) -> list[str]:
    return sorted(k for k in keys if k not in HELP)
