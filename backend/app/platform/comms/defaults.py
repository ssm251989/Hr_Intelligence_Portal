"""Part 18: ready-to-use wording for every automatic candidate email.

The first time a message is needed and the company has no template with that key yet, a
PUBLISHED template is created from the wording below; from then on it is an ordinary
template the company edits in Settings > Communication > Templates (their edits win -- this
never overwrites an existing template). Placeholders use the same {{ name }} syntax as
every other template; the company logo/colours wrapper is added at send time (17.11).
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

# key -> (subject, plain-text body, required variables)
DEFAULTS: dict[str, tuple[str, str, list[str]]] = {
    "recruitment.salary_details_request": (
        "{{ job_title }}: your salary and joining details",
        "Hi {{ candidate_first_name }},\n\nThank you for your time in the interview for {{ job_title }}. To move to the next step, "
        "please share your salary and joining details (it takes about 2 minutes):\n\n{{ form_link }}\n\n"
        "Your answers are only seen by the hiring team.\n\nBest regards,\n{{ company_name }} HR",
        ["candidate_first_name", "job_title", "form_link"],
    ),
    "recruitment.salary_counter_offer": (
        "{{ job_title }}: our salary offer",
        "Hi {{ candidate_first_name }},\n\nThank you for sharing your salary details for {{ job_title }}. After reviewing them, we would "
        "like to offer {{ amount }} per year.\n\n{{ note }}\n\nPlease reply to this email to let us know if this works for you, or if "
        "you would like to talk it through.\n\nBest regards,\n{{ company_name }} HR",
        ["candidate_first_name", "job_title", "amount"],
    ),
    "recruitment.documents_request": (
        "{{ job_title }}: please upload your joining documents",
        "Hi {{ candidate_first_name }},\n\nGood news - your salary for {{ job_title }} is approved. The next step is your joining "
        "documents. Please upload them here:\n\n{{ form_link }}\n\nWhat we need:\n{{ documents }}\n\nClear photos or PDFs are fine. "
        "Only the HR team sees them.\n\nBest regards,\n{{ company_name }} HR",
        ["candidate_first_name", "job_title", "form_link", "documents"],
    ),
    "recruitment.documents_reupload": (
        "{{ job_title }}: please upload a few documents again",
        "Hi {{ candidate_first_name }},\n\nThank you for your documents. We need these again:\n{{ documents }}\n\n{{ note }}\n\n"
        "Please use the same link:\n\n{{ form_link }}\n\nBest regards,\n{{ company_name }} HR",
        ["candidate_first_name", "job_title", "form_link", "documents"],
    ),
    "recruitment.bgv_unsuccessful": (
        "{{ job_title }}: background verification update",
        "{{ message }}\n\nBest regards,\n{{ company_name }} HR",
        ["message"],
    ),
    "recruitment.joining_dates": (
        "{{ job_title }}: background verification successful - choose your joining date",
        "Hi {{ candidate_first_name }},\n\nGreat news - your background verification is complete and successful.\n\n"
        "Please choose the joining date that suits you best:\n{{ dates }}\n\nChoose with one click here:\n{{ choose_link }}\n\n{{ note }}\n\n"
        "Best regards,\n{{ company_name }} HR",
        ["candidate_first_name", "job_title", "dates", "choose_link"],
    ),
    "recruitment.offer_letter_auto": (
        "{{ job_title }}: your offer letter - please review and sign",
        "Hi {{ candidate_first_name }},\n\nCongratulations! Your offer letter for {{ job_title }} at {{ company_name }} is ready.\n\n"
        "Review & sign it here: {{ sign_link }}\n\nThe page shows your letter (you can download it as a PDF). To sign, type your full "
        "name and tick \"I accept\". Please sign by {{ expiry_date }}.\n\nYour letter:\n\n{{ letter }}\n\nBest regards,\n{{ company_name }} HR",
        ["candidate_first_name", "job_title", "letter", "sign_link"],
    ),
    # fix 2026-10-05: joiner exits (app/onboarding/joiner_actions.py)
    "onboarding.offer_withdrawn": (
        "About your offer for {{ job_title }} at {{ company_name }}",
        "Hi {{ candidate_first_name }},\n\nThank you for your time and interest in {{ company_name }}. We are sorry to let you know that "
        "we are withdrawing our offer for {{ job_title }}. Your earlier offer and welcome links no longer work.\n\n"
        "If you have any questions, please reply to this email and our HR team will get back to you.\n\nBest regards,\n{{ company_name }} HR",
        ["candidate_first_name", "job_title"],
    ),
    "onboarding.not_reporting_reminder": (
        "We missed you at work - please get in touch",
        "Hi {{ candidate_first_name }},\n\nWe have not seen you at work since {{ last_seen }}, and we could not reach you. We hope you are "
        "well.\n\nPlease contact {{ hr_contact }} by {{ respond_by }} to let us know when you will be back.\n\nBest regards,\n{{ company_name }} HR",
        ["candidate_first_name", "last_seen"],
    ),
    "onboarding.not_reporting_show_cause": (
        "Absence from work since {{ last_seen }} - please explain and return to work",
        "Hi {{ candidate_first_name }},\n\nYou have been absent from work as {{ job_title }} since {{ last_seen }} ({{ days_absent }} days) "
        "without telling us, and our earlier message got no reply.\n\nPlease report back to work, or tell {{ hr_contact }} in writing why "
        "you have been away, by {{ respond_by }}. If we do not hear from you, we will have to treat this as leaving your job without "
        "notice.\n\nBest regards,\n{{ company_name }} HR",
        ["candidate_first_name", "last_seen", "respond_by"],
    ),
    "onboarding.not_reporting_final": (
        "Final notice: absence from work since {{ last_seen }}",
        "Hi {{ candidate_first_name }},\n\nThis is our final notice. You have been absent since {{ last_seen }} ({{ days_absent }} days) and "
        "have not replied to our earlier messages.\n\nIf we do not hear from you by {{ respond_by }}, your employment as {{ job_title }} "
        "will be ended as absconding (leaving without notice), and you will need to return any company property you have.\n\n"
        "Please contact {{ hr_contact }}.\n\n{{ company_name }} HR",
        ["candidate_first_name", "last_seen", "respond_by"],
    ),
    # Part 20: employees (app/employees/*)
    "letters.test_copy": (  # Part 22.6c: Settings > Letters > Send test to me
        "Sample {{ letter }} letter from {{ company_name }} (test)",
        "This is a test copy of the {{ letter }} letter design with sample details. It is attached as a PDF.\n\n{{ company_name }} HR app",
        ["letter"],
    ),
    "access.updated": (  # Part 22.4: Employees > Assign roles
        "Your access in {{ company_name }} HR was updated",
        "Hello {{ name }},\n\nHR updated what you can see and do in the {{ company_name }} HR app.\n\nYour roles now: {{ roles }}\nAdded: {{ added }}\nRemoved: {{ removed }}\n\n"
        "The change shows the next time you open or refresh the app: {{ link }}\n\nIf this looks wrong, reply to HR.\n\n{{ company_name }} HR",
        ["name", "roles"],
    ),
    "copilot.hr_handover": (  # Part 22.1: the HR assistant hands a question to HR (Helpdesk off)
        "HR assistant: a question from {{ user_name }}",
        "Hello HR team,\n\n{{ user_name }} ({{ user_email }}) asked the HR assistant a question it could not answer from the company policies:\n\n"
        "\"{{ question }}\"\n\nPlease reply to them. It is also on your to-do list in My approvals: {{ link }}\n\n{{ company_name }} HR assistant",
        ["user_name", "question"],
    ),
    "bgv.vendor_assigned": (  # Part 21.4: BGV vendor
        "Background check request: {{ candidate }} ({{ job_title }}) - {{ company_name }}",
        "Hello {{ vendor }},\n\n{{ company_name }} requests a background check for {{ candidate }} ({{ job_title }}).\n\nChecks: {{ checks }}\nDue by: {{ due }}\n\n"
        "Open the secure page to download this candidate's documents and upload your report: {{ link }}\n"
        "The link works until {{ expires }} and shows only this candidate.\n\n{{ company_name }} HR",
        ["candidate", "link"],
    ),
    "bgv.vendor_reminder": (
        "Reminder: background check for {{ candidate }} {{ when }}",
        "Hello,\n\nThe background check for {{ candidate }} ({{ job_title }}) {{ when }} (due {{ due }}).\nChecks: {{ checks }}\n\n"
        "Upload the report here: {{ link }}\n\n{{ company_name }} HR",
        ["candidate", "link"],
    ),
    "bgv.vendor_cancelled": (
        "Background check for {{ candidate }} is cancelled",
        "Hello,\n\nPlease stop the background check for {{ candidate }} ({{ job_title }}). The earlier link no longer works.\n\n{{ company_name }} HR",
        ["candidate"],
    ),
    "employee.profile_change_result": (  # Part 20.3: employee self-service
        "Your profile change was {{ result }}",
        "Hi {{ first_name }},\n\nYour request to change your profile details was {{ result }}.\nHR's note: {{ note }}\n\nSee your profile: {{ link }}\n\n{{ company_name }} HR",
        ["first_name", "result", "link"],
    ),
    "employee.absconding_notice": (
        "Absence from work since {{ last_seen }}",
        "Hi {{ first_name }},\n\nYou have not come to work since {{ last_seen }} and we have not been able to reach you. Your employment is being "
        "closed as absconding (leaving without notice).\n\nPlease contact HR as soon as possible, and return any company property you have "
        "(laptop, ID card, access card).\n\n{{ company_name }} HR",
        ["first_name", "last_seen"],
    ),
    "employee.resignation_to_manager": (
        "{{ name }} has resigned - your approval is needed",
        "Hi,\n\n{{ name }} has sent their resignation.\nRequested last working day: {{ requested }}\nAsked for early release: {{ early }}\n\n"
        "Please talk to them, add a note if you discussed staying, and approve so HR can confirm the last working day: {{ link }}\n\n{{ company_name }} HR",
        ["name", "link"],
    ),
    "employee.exit_task_assigned": (  # feat 2026-10-06: actionable exit checklist
        "Exit checklist: {{ item }} for {{ name }}",
        "Hi,\n\n{{ name }} is leaving {{ company_name }}; their last working day is {{ last_day }}.\n\nYou own this exit checklist item: "
        "{{ item }}\nPlease finish it by {{ due }}.\n\nOpen it: {{ link }}\n\n{{ company_name }} HR",
        ["item", "name", "link"],
    ),
    "employee.exit_task_returned": (
        "{{ name }} says they have returned: {{ item }}",
        "Hi,\n\n{{ name }} has marked \"{{ item }}\" as returned. Please check it and click Received (Good / Damaged / Missing parts), "
        "or Lost / not returned.\n\nOpen it: {{ link }}\n\n{{ company_name }} HR",
        ["item", "name", "link"],
    ),
    "employee.exit_task_reminder": (
        "Reminder: {{ item }} for {{ name }} is due {{ due }}",
        "Hi,\n\nThis exit checklist item is still open: {{ item }} ({{ name }}, last working day {{ last_day }}).\nIt is due {{ due }}.\n\n"
        "Open it: {{ link }}\n\n{{ company_name }} HR",
        ["item", "name", "link"],
    ),
    "employee.asset_return_request": (
        "Please return: {{ what }}",
        "Hi {{ first_name }},\n\nBefore you leave, please return {{ what }} by {{ by }}.\n\nWhen you have handed it over, open your exit page "
        "and click \"I have returned it\" (you can add a note or a photo): {{ link }}\n\nThank you.\n\n{{ company_name }} HR",
        ["first_name", "what", "link"],
    ),
    "employee.exit_letters": (
        "Your relieving and experience letters from {{ company_name }}",
        "Hi {{ first_name }},\n\nYour exit is complete; your last working day was {{ last_working_day }}. Your relieving letter and "
        "experience letter are attached as PDFs.\n\nThank you for your time with us, and all the best.\n\n{{ company_name }} HR",
        ["first_name", "last_working_day"],
    ),
    "employee.exit_interview_reminder": (  # fix 2026-10-06: the employee answers their own exit interview
        "A few questions before you go",
        "Hi {{ first_name }},\n\n{{ before }}, please take a few minutes to answer some questions about your time at "
        "{{ company_name }}. Your answers go only to HR - your manager will not see them.\n\nOpen your exit page: {{ link }}\n\n"
        "Thank you, and all the best.\n\n{{ company_name }} HR",
        ["first_name", "link"],
    ),
    "employee.app_invite": (
        "Welcome to {{ company_name }} - set your password for the HR app",
        "Hi {{ first_name }},\n\nYour account for the {{ company_name }} HR app is ready.\n\nSign-in: {{ login }}\n"
        "Set your password here (the link works for {{ hours }} hours, once): {{ link }}\n\n"
        "In the app you can see your profile, documents and assets, and raise requests.\n\n"
        "If the link has expired, ask HR to send a new one.\n\nBest regards,\n{{ company_name }} HR",
        ["first_name", "link", "login"],
    ),
    # change 2026-10-05: HR's "Remind candidate" on missing joining details (ui_onboarding_router)
    "onboarding.details_reminder": (
        "A few joining details are still missing",
        "Hi {{ candidate_first_name }},\n\nThank you for filling in your joining details for {{ company_name }}. A few are still empty:\n\n"
        "{{ missing }}\n\nYou can add them here whenever you are ready: {{ portal_link }}\n\nIf you have any questions, just reply to this email.\n\n"
        "Best regards,\n{{ company_name }} HR",
        ["candidate_first_name", "missing", "portal_link"],
    ),
    "onboarding.joiner_exit_internal": (
        "{{ summary }}",
        "{{ summary }}\n\nOpen the record: {{ link }}\n\nThe exit case has the clearance checklist (incl. any assets to collect).\n\n{{ company_name }} HR system",
        ["summary"],
    ),
    # fix 2026-10-05: resend for signature / revised offer (app/offers/revisions.py)
    "recruitment.offer_resend": (
        "Reminder: your offer for {{ job_title }} is waiting for your signature",
        "Hi {{ candidate_first_name }},\n\nJust a reminder - your offer letter for {{ job_title }} at {{ company_name }}{{ version_note }} "
        "is ready for you to sign.\n\nReview & sign it here: {{ sign_link }}\n\nPlease sign by {{ expiry_date }}. If you have any "
        "questions, just reply to this email.\n\nBest regards,\n{{ company_name }} HR",
        ["candidate_first_name", "job_title", "sign_link"],
    ),
    "recruitment.offer_revised": (
        "Revised offer from {{ company_name }}",
        "Hi {{ candidate_first_name }},\n\nWe have revised your offer for {{ job_title }} at {{ company_name }} (version {{ version_no }}).\n\n"
        "What changed:\n{{ what_changed }}\n\nReview & sign it here: {{ sign_link }}{{ docusign_note }}\n\nYour earlier offer link no longer "
        "works - please sign this new version by {{ expiry_date }}.\n\nYour revised letter:\n\n{{ letter }}\n\nBest regards,\n{{ company_name }} HR",
        ["candidate_first_name", "job_title", "what_changed", "sign_link"],
    ),
    "recruitment.offer_revised_signed": (
        "Thank you for signing your revised offer, {{ candidate_first_name }}",
        "Hi {{ candidate_first_name }},\n\nThank you for signing your revised offer (version {{ version_no }}) for {{ job_title }} at "
        "{{ company_name }}.\n\nYour joining date is {{ joining_date }}. Your welcome portal shows the same date and your next steps.\n\n"
        "See you soon!\n{{ company_name }} HR",
        ["candidate_first_name", "job_title", "joining_date"],
    ),
    "recruitment.welcome_selected": (
        "Welcome to {{ company_name }}, {{ candidate_first_name }}!",
        "Hi {{ candidate_first_name }},\n\nThank you for signing your offer - welcome to the team! You join {{ company_name }} as "
        "{{ job_title }} on {{ joining_date }}.\n\nYour next steps:\n{{ steps }}\n\n{{ contacts }}\n\n"
        "We can't wait to work with you.\n\n{{ company_name }} HR",
        ["candidate_first_name", "job_title", "joining_date", "steps"],
    ),
    "platform.user_invite": (
        "You're invited to {{ company_name }} hiring",
        "Hi {{ name }},\n\n{{ invited_by }} has invited you to {{ company_name }}'s hiring app as {{ role }}.\n\n"
        "Set your password here (the link works for 7 days):\n{{ link }}\n\nWelcome aboard!\n{{ company_name }}",
        ["link"],
    ),
    "platform.password_reset_link": (
        "Reset your password for {{ company_name }}",
        "Hi {{ name }},\n\nYour admin sent you a link to set a new password (it works for 2 days):\n{{ link }}\n\n"
        "If you didn't ask for this, you can ignore this email.\n{{ company_name }}",
        ["link"],
    ),
    "recruitment.job_closed_candidate": (
        "Update on your application for {{ job_title }}",
        "Hi {{ candidate_first_name }},\n\nThank you for applying for {{ job_title }}. This position has been closed for now, so "
        "your application is on hold. If the role opens again, we will pick up your application from where it was - "
        "you don't need to apply again.\n\nThank you for your interest in {{ company_name }}.\n\nBest regards,\n{{ company_name }} HR",
        ["candidate_first_name", "job_title"],
    ),
}


def _html(text: str) -> str:
    paras = [p.replace("\n", "<br>") for p in text.split("\n\n")]
    return "".join(f"<p>{p}</p>" for p in paras)


# fix 2026-10-04: wording that was replaced -- a company template still word-for-word this old default
# (never edited) is moved to the new default; an edited template is never touched.
RETIRED: dict[str, tuple[str, ...]] = {
    "recruitment.offer_revised": (  # fix 2026-10-05: first wording ("&" / "->" came out escaped in the text part)
        "Hi {{ candidate_first_name }},\n\nWe have revised your offer for {{ job_title }} at {{ company_name }} (version {{ version_no }}).\n\n"
        "What changed:\n{{ what_changed }}\n\n{{ sign_line }}\n\nYour earlier offer link no longer works - please sign this new "
        "version by {{ expiry_date }}.\n\nYour revised letter:\n\n{{ letter }}\n\nBest regards,\n{{ company_name }} HR",),
    "recruitment.offer_letter_auto": (
        "Hi {{ candidate_first_name }},\n\nHere is your offer letter:\n\n{{ letter }}\n\nPlease reply to this email to accept by "
        "{{ expiry_date }}.\n\nBest regards,\n{{ company_name }} HR",),
    "recruitment.welcome_selected": (
        "Hi {{ candidate_first_name }},\n\nCongratulations - you have been selected for {{ job_title }}! We are delighted to have you "
        "join {{ company_name }} on {{ joining_date }}.\n\nYour next steps:\n{{ steps }}\n\nPeople you can reach out to:\n{{ contacts }}\n\n"
        "Welcome aboard - we can't wait to work with you.\n\n{{ company_name }} HR",),
}


def ensure_template(db: Session, tenant, key: str, *, locale: str = "en") -> bool:
    """Creates the default published template for `key` if the company has none. True if it exists afterwards."""
    from app.models.comms import MessageTemplate

    existing = db.query(MessageTemplate).filter(MessageTemplate.tenant_id == tenant.tenant_id, MessageTemplate.key == key).all()
    if existing:
        for t in existing:
            if key in RETIRED and (t.text_tpl or "") in RETIRED[key]:
                subject, body, required = DEFAULTS[key]
                t.subject_tpl, t.text_tpl, t.html_tpl = subject, body, _html(body)
                t.variables_schema_json = {"required": required}
                t.published_by, t.published_at = "system (updated default wording)", datetime.now(timezone.utc)
        db.commit()
        return True
    if key not in DEFAULTS:
        return False
    subject, body, required = DEFAULTS[key]
    db.add(MessageTemplate(tenant_id=tenant.tenant_id, key=key, channel="email", locale=locale, version=1, status="published",
                           subject_tpl=subject, text_tpl=body, html_tpl=_html(body), variables_schema_json={"required": required},
                           published_by="system (default wording)", published_at=datetime.now(timezone.utc)))
    db.commit()
    return True


def send_default(db: Session, tenant, key: str, *, to: list[str], ctx: dict, purpose: str = "email.outbound.recruitment",
                 related_entity_type: Optional[str] = None, related_entity_id: Optional[UUID] = None):
    """ensure_template + comms.send, with the company name filled in. Returns the OutboundMessage."""
    from app.platform.comms.service import send
    from app.platform.settings.resolver import SettingContext, SettingsService

    ensure_template(db, tenant, key)
    company = SettingsService(db).get("org.display_name", SettingContext(tenant=tenant)) or ""
    return send(db, tenant, template_key=key, to=to, ctx={"company_name": company, **ctx}, purpose=purpose,
                related_entity_type=related_entity_type, related_entity_id=related_entity_id)
