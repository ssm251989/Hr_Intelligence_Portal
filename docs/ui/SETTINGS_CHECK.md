# Settings check (Part 17.11)

Every registered setting, saved through the real API (`PUT /api/v1/settings/{key}`) with a changed, valid value, read back (`GET /api/v1/settings`), and - where the value shows up somewhere - checked there. Everything ran inside a database transaction that was rolled back, so no real setting was changed. Re-run: `backend/.venv/Scripts/python.exe backend/scripts/settings_check.py`.

**Result: 119 of 119 settings OK, 0 failed, 0 secrets skipped.**

Settings kept on their own pages (not in this registry) were checked separately in FIXES_17.md 17.11: company logo, brand colours, mailboxes/connections, email templates, approval steps, custom fields, roles.

| Setting | Group | Type | Saved | Reloaded | Shows in app | Note |
|---|---|---|---|---|---|---|
| `ai.enabled` | AI Governance | bool | OK | OK | n/a (used by server logic) |  |
| `ai.features.disabled` | AI Governance | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `ai.models.candidate_ranking` | AI Models | str | OK | OK | n/a (used by server logic) |  |
| `ai.models.document_validation` | AI Models | str | OK | OK | n/a (used by server logic) |  |
| `ai.models.interview_questions` | AI Models | str | OK | OK | n/a (used by server logic) |  |
| `ai.models.jd_generation` | AI Models | str | OK | OK | n/a (used by server logic) |  |
| `ai.models.offer_letter_generation` | AI Models | str | OK | OK | n/a (used by server logic) |  |
| `ai.models.resume_extraction` | AI Models | str | OK | OK | n/a (used by server logic) |  |
| `ai.models.resume_matching` | AI Models | str | OK | OK | n/a (used by server logic) |  |
| `ai.models.shortlist_feedback` | AI Models | str | OK | OK | n/a (used by server logic) |  |
| `ai.pricing` | AI Governance | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `ai.redaction.enabled` | AI Governance | bool | OK | OK | n/a (used by server logic) |  |
| `ai.redaction.patterns` | AI Governance | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `analytics.diversity.enabled` | Analytics | bool | OK | OK | n/a (used by server logic) |  |
| `analytics.diversity.min_group_size` | Analytics | int | OK | OK | n/a (used by server logic) |  |
| `analytics.recruiting_spend_ytd` | Analytics | decimal | OK | OK | n/a (used by server logic) |  |
| `careers.site.benefits` | Careers site | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `careers.site.faq` | Careers site | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `careers.site.intro` | Careers site | str | OK | OK | n/a (used by server logic) |  |
| `copilot.handover_category` | HR Copilot | str | OK | OK | n/a (used by server logic) |  |
| `copilot.languages` | HR Copilot | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `copilot.min_confidence` | HR Copilot | decimal | OK | OK | n/a (used by server logic) |  |
| `geo.countries` | Maps | json | OK | OK | OK - Which countries maps accept | same-value round trip (list/object setting) |
| `geo.online_lookup` | Maps | bool | OK | OK | n/a (used by server logic) |  |
| `geo.tile_attribution` | Maps | str | OK | OK | OK - Map credit line |  |
| `geo.tile_url` | Maps | str | OK | OK | OK - Map tiles on every map |  |
| `helpdesk.email.default_category` | Helpdesk | str | OK | OK | n/a (used by server logic) |  |
| `iam.auth.access_token_expiry_minutes` | Authentication | int | OK | OK | n/a (used by server logic) |  |
| `iam.auth.ip_allowlist` | Authentication | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `iam.auth.lockout_duration_minutes` | Authentication | int | OK | OK | n/a (used by server logic) |  |
| `iam.auth.lockout_threshold` | Authentication | int | OK | OK | n/a (used by server logic) |  |
| `iam.auth.mfa_required` | Authentication | bool | OK | OK | n/a (used by server logic) |  |
| `iam.auth.password_expiry_days` | Authentication | int | OK | OK | n/a (used by server logic) |  |
| `iam.auth.password_history_count` | Authentication | int | OK | OK | n/a (used by server logic) |  |
| `iam.auth.password_min_length` | Authentication | int | OK | OK | n/a (used by server logic) |  |
| `iam.auth.password_require_complexity` | Authentication | bool | OK | OK | n/a (used by server logic) |  |
| `iam.auth.refresh_token_expiry_days` | Authentication | int | OK | OK | n/a (used by server logic) |  |
| `iam.auth.remember_device_days` | Authentication | int | OK | OK | n/a (used by server logic) |  |
| `iam.auth.two_step_available` | Advanced | bool | OK | OK | n/a (used by server logic) |  |
| `modules.lock.enabled` | Modules | bool | OK | OK | n/a (used by server logic) |  |
| `modules.lock.lockout_minutes` | Modules | int | OK | OK | n/a (used by server logic) |  |
| `modules.lock.max_attempts` | Modules | int | OK | OK | n/a (used by server logic) |  |
| `modules.lock.mode` | Modules | str | OK | OK | n/a (used by server logic) |  |
| `onboarding.bgv.block_conversion_until_clear` | Background Verification | bool | OK | OK | n/a (used by server logic) |  |
| `onboarding.bgv.default_package` | Background Verification | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `onboarding.conversion.default_plan_template` | Conversion | str | OK | OK | n/a (used by server logic) |  |
| `onboarding.documents.required_types` | Pre-boarding | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `onboarding.portal.link_ttl_days` | Pre-boarding | int | OK | OK | n/a (used by server logic) |  |
| `onboarding.portal.required_forms` | Pre-boarding | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `onboarding.portal.required_policies` | Pre-boarding | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `org.currency` | Organisation | str | OK | OK | n/a (used by server logic) |  |
| `org.date_format` | Organisation | str | OK | OK | n/a (used by server logic) |  |
| `org.display_name` | Organisation | str | OK | OK | OK - Company name in the menu, sign-in page and careers site |  |
| `org.fiscal_year_start` | Organisation | str | OK | OK | n/a (used by server logic) |  |
| `org.fiscal_year_start_month` | Company | int | OK | OK | n/a (used by server logic) |  |
| `org.legal_links` | Organisation | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `org.legal_name` | Organisation | str | OK | OK | n/a (used by server logic) |  |
| `org.locale` | Organisation | str | OK | OK | OK - Language of the app (company default): the signed-in admin chose 'en' for themselves, which wins over the company default (as designed) |  |
| `org.rtl_locales` | Organisation | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `org.support_email` | Organisation | email | OK | OK | OK - Support contact on public pages |  |
| `org.timezone` | Organisation | str | OK | OK | OK - Dates and times in the app |  |
| `org.week_start` | Organisation | str | OK | OK | n/a (used by server logic) |  |
| `performance.ai.bias_terms` | Reviews | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `performance.goals.weightage_rules` | Goals | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `platform.modules.enabled` | Modules | json | OK | OK | OK - Which modules are in the menu | same-value round trip (list/object setting) |
| `platform.modules.offered` | Modules | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `platform.setup.config_pack` | Setup | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `platform.setup.skipped` | Setup | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `privacy.dpr_sla_days` | Privacy | int | OK | OK | n/a (used by server logic) |  |
| `privacy.retention_days` | Privacy | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `recruitment.candidates.recycle_days` | Candidates | int | OK | OK | n/a (used by server logic) |  |
| `recruitment.careers.ask_salary` | Careers site | bool | OK | OK | n/a (used by server logic) |  |
| `recruitment.contacts` | Joining | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `recruitment.documents.auto_send` | Documents | bool | OK | OK | n/a (used by server logic) |  |
| `recruitment.documents.reminder_hours` | Documents | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `recruitment.documents.required` | Documents | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `recruitment.jobs.close_email_candidates` | Jobs | bool | OK | OK | n/a (used by server logic) |  |
| `recruitment.joining.reminder_hours` | Joining | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `recruitment.negotiation.busy_source` | Interview Negotiation | enum | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `recruitment.negotiation.max_retry_days` | Interview Negotiation | int | OK | OK | n/a (used by server logic) |  |
| `recruitment.negotiation.retry_day_offset` | Interview Negotiation | int | OK | OK | n/a (used by server logic) |  |
| `recruitment.negotiation.slots_offered` | Interview Negotiation | int | OK | OK | n/a (used by server logic) |  |
| `recruitment.negotiation.slots_to_pick` | Interview Negotiation | int | OK | OK | n/a (used by server logic) |  |
| `recruitment.reminders.approval_hours` | Reminders | int | OK | OK | n/a (used by server logic) |  |
| `recruitment.reminders.documents_days` | Reminders | int | OK | OK | n/a (used by server logic) |  |
| `recruitment.reminders.enabled` | Reminders | bool | OK | OK | n/a (used by server logic) |  |
| `recruitment.reminders.offer_expiry_days` | Reminders | int | OK | OK | n/a (used by server logic) |  |
| `recruitment.reminders.scorecard_hours` | Reminders | int | OK | OK | n/a (used by server logic) |  |
| `recruitment.salary.approval_margin_pct` | Salary | int | OK | OK | n/a (used by server logic) |  |
| `recruitment.salary.approvers` | Salary | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `recruitment.salary.ask_after_shortlist` | Salary | bool | OK | OK | n/a (used by server logic) |  |
| `recruitment.salary.ask_offers` | Salary | bool | OK | OK | n/a (used by server logic) |  |
| `recruitment.salary.ask_payslip` | Salary | bool | OK | OK | n/a (used by server logic) |  |
| `recruitment.salary.auto_approve_hike_pct` | Salary | int | OK | OK | n/a (used by server logic) |  |
| `recruitment.salary.form_after_round` | Salary | int | OK | OK | n/a (used by server logic) |  |
| `recruitment.salary.form_trigger` | Salary | str | OK | OK | n/a (used by server logic) |  |
| `recruitment.salary.reminder_hours` | Salary | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `recruitment.salary.target_hike_pct` | Salary | int | OK | OK | n/a (used by server logic) |  |
| `recruitment.scoring.shortlist_threshold` | Scoring | int | OK | OK | OK - Shortlist threshold on the Screening dashboard |  |
| `recruitment.shortlisting.auto_shortlist` | Shortlisting | bool | OK | OK | OK - Shortlisting rules form |  |
| `recruitment.shortlisting.max_size` | Shortlisting | int | OK | OK | OK - Shortlisting rules form |  |
| `recruitment.shortlisting.notify` | Shortlisting | json | OK | OK | OK - Shortlisting rules form | same-value round trip (list/object setting) |
| `recruitment.shortlisting.undo_hours` | Shortlisting | int | OK | OK | OK - Shortlisting rules form |  |
| `recruitment.tracker.excel.path` | Interview Tracker | str | OK | OK | n/a (used by server logic) |  |
| `recruitment.tracker.excel.sheet_names` | Interview Tracker | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `recruitment.tracker.save_retry.attempts` | Interview Tracker | int | OK | OK | n/a (used by server logic) |  |
| `recruitment.tracker.save_retry.backoff_seconds` | Interview Tracker | decimal | OK | OK | n/a (used by server logic) |  |
| `separation.clearance_checklist` | Separation | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `separation.default_notice_days` | Separation | int | OK | OK | n/a (used by server logic) |  |
| `separation.experience_letter_template` | Separation | str | OK | OK | n/a (used by server logic) |  |
| `separation.relieving_letter_template` | Separation | str | OK | OK | n/a (used by server logic) |  |
| `separation.require_shortfall_cover` | Separation | bool | OK | OK | n/a (used by server logic) |  |
| `separation.retention_step_enabled` | Separation | bool | OK | OK | n/a (used by server logic) |  |
| `ux.home_default_employee` | Home page | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `ux.home_default_hr` | Home page | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `ux.home_default_manager` | Home page | json | OK | OK | n/a (used by server logic) | same-value round trip (list/object setting) |
| `ux.home_layout` | Home page | json | n/a | n/a | n/a | per-person setting (scope user), saved from its own screen |
| `ux.page_size` | Lists | int | OK | OK | n/a (used by server logic) |  |
| `ux.reduce_motion` | Accessibility | bool | OK | OK | n/a (used by server logic) |  |

## Settings screens (Part 18.22)

| Screen | Saved | Reloads | Used in app | How checked |
|---|---|---|---|---|
| Company > Branding (logo + colours) | OK | OK | OK: sidebar, login, careers, emails and letters use `logo_url` | bootstrap + public branding return the logo; the file serves 200. The page used to show the Templates tab (panel `only` bug, fixed) |
| Company > Offices & locations | OK | OK | OK: office map (now every office, not only offices with people) | rolled back: add (with map position) → edit → shown on the map → delete |
| People & access > Users | OK | OK | OK | invite (email) · change role (RBAC follows) · switch off (sign-in refused, token 401) · switch on (sign-in 200) · password reset link · last-admin / self guards · recruiter 403 |
| People & access > Roles (permissions matrix) | OK | OK | OK | PATCH role permissions → saved. The Users/Roles pages used to show the same tab (fixed) |
| Hiring > Hiring stages & job requests | OK | OK | OK | merged into one page with two tabs (they showed the same thing) |
| Hiring > Scoring rules | OK | OK | OK | weights editable as numbers or sliders; total red "Total must be 100 (now 115)" and Save disabled unless exactly 100 |
| Hiring > Salary rules / Department budgets / Required documents / Contacts | OK | OK | OK | FIXES_18 18.12-18.20 |
| Integrations > Connections | OK | OK | OK | status chip, last test, Test, Edit (masked secrets, empty = keep, merged), Disconnect with confirm (routes + secret removed, history kept), Connect again |
| Integrations > Job boards | OK | OK | n/a until a board API exists | FIXES_18 18.9 |
| Advanced > Modules | OK | OK | OK | FIXES_18 18.4 / 18.5 |
