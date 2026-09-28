"""Part 16.2: friendly names for message templates and their placeholders.

People never see a template key ("recruitment.application.received") or Jinja braces
("{{ job_title }}"). Screens show the name + one line saying who gets it and when; the editor
inserts placeholders from a picker of friendly names with a sample value, and previews render
with those samples. Keys stay the storage identity (shown only under "Advanced").
"""

from typing import Optional

# key -> (name, who gets it and when)
TEMPLATES: dict[str, tuple[str, str]] = {
    "recruitment.application.received": ("Application received", "Sent to the candidate right after they apply."),
    "recruitment.application.rejected": ("Application not taken forward", "Sent to the candidate when they are not selected."),
    "recruitment.application.shortlisted": ("Shortlisted", "Sent to the candidate when they are shortlisted."),
    "recruitment.interview.confirmation": ("Interview confirmed", "Sent to the candidate and interviewer once an interview time is fixed."),
    "recruitment.negotiation.candidate_offer": ("Pick an interview time", "Sent to the candidate with interview times to choose from."),
    "recruitment.negotiation.candidate_reprompt": ("Pick an interview time (reminder)", "Sent to the candidate when their reply didn't pick a time."),
    "recruitment.negotiation.interviewer_offer": ("Interview time for the interviewer", "Sent to the interviewer to confirm a time."),
    "recruitment.offer.released": ("Offer letter", "Sent to the candidate with their offer."),
    "recruitment.salary_details_request": ("Salary & joining details", "Sent to a shortlisted candidate to fill in salary, notice period and joining details."),
    "recruitment.salary_counter_offer": ("Salary counter-offer", "Sent when HR counter-offers a salary to a candidate who asked above the rules."),
    "recruitment.job_closed_candidate": ("Job closed - application on hold", "Sent to candidates (if switched on) when a job is closed; their application is kept on hold."),
    "recruitment.agency_invite": ("Agency portal invitation", "Sent to a recruitment agency's user to set their password."),
    "recruitment.job_requisition_approval": ("Job needs approval", "Sent to approvers when a new job is waiting for them."),
    "system.otp": ("Sign-in code", "Sent when someone signs in with a one-time code."),
    "system.password_reset": ("Reset password", "Sent when someone asks to reset their password."),
    "system.welcome": ("Welcome to the portal", "Sent to a new user with their sign-in link."),
    "platform.admin_invite": ("Admin invitation", "Sent to a new admin to set their password."),
    "onboarding.documents_reminder": ("Documents reminder", "Sent to a new joiner who still has documents to upload."),
    "onboarding.welcome": ("Welcome, new joiner", "Sent to a new joiner with their welcome portal link."),
    "helpdesk.ticket_created": ("Ticket received", "Sent to the employee when their helpdesk ticket is created."),
    "helpdesk.ticket_reply": ("Reply on your ticket", "Sent to the employee when the helpdesk replies."),
    "helpdesk.ticket_escalated": ("Ticket escalated", "Sent to the team lead when a ticket misses its response time."),
    "performance.review_due": ("Review due", "Sent to employees and managers when a review is waiting."),
    "privacy.request_received": ("Privacy request received", "Sent when someone asks to see or delete their data."),
    "privacy.request_overdue": ("Privacy request overdue", "Sent to the privacy team when a request is late."),
    "privacy.breach_reported": ("Data breach reported", "Sent to the privacy team when a breach is reported."),
}

# placeholder -> (friendly name, sample value)
VARIABLES: dict[str, tuple[str, str]] = {
    "candidate_name": ("Candidate name", "Ananya Rao"),
    "candidate_first_name": ("Candidate first name", "Ananya"),
    "job_title": ("Job title", "Automation Architect"),
    "job_location": ("Job location", "Hyderabad"),
    "interview_time": ("Interview date & time", "Mon 14 Oct, 11:00 am"),
    "interview_link": ("Interview link", "https://meet.example.com/abc-defg-hij"),
    "interviewer_name": ("Interviewer name", "Suresh A"),
    "slots": ("Interview times to choose from", "Mon 11:00 am · Tue 3:00 pm · Wed 10:30 am"),
    "offer_link": ("Offer link", "https://portal.example.com/offer/…"),
    "joining_date": ("Joining date", "4 Nov 2026"),
    "portal_link": ("Welcome portal link", "https://portal.example.com/welcome/…"),
    "reset_link": ("Reset link", "https://portal.example.com/set-password/…"),
    "code": ("One-time code", "482 913"),
    "form_link": ("Form link", "https://portal.example.com/salary-details/…"),
    "link": ("Sign-in link", "https://portal.example.com/set-password/…"),
    "agency_name": ("Agency name", "Bright Talent Partners"),
    "invited_by": ("Invited by", "Priya S"),
    "employee_name": ("Employee name", "Ravi Kumar"),
    "ticket_number": ("Ticket number", "HD-1042"),
    "ticket_subject": ("Ticket subject", "Laptop not charging"),
    "review_name": ("Review name", "2026 mid-year review"),
    "due_date": ("Due date", "31 Oct 2026"),
    "org.display_name": ("Company name", "Your Company"),
    "org.support_email": ("Support email", "hr@yourcompany.com"),
}


def _humanise(key: str) -> str:
    last = key.split(".")[-1].replace("_", " ").strip()
    return last[:1].upper() + last[1:] if last else key


def describe_template(key: str) -> dict:
    name, description = TEMPLATES.get(key, (_humanise(key), ""))
    return {"name": name, "description": description}


def variable_catalog(company_name: Optional[str] = None) -> list[dict]:
    out = []
    for key, (name, sample) in VARIABLES.items():
        if key == "org.display_name" and company_name:
            sample = company_name
        out.append({"key": key, "name": name, "sample": sample})
    return out


def sample_context(company_name: Optional[str] = None) -> dict:
    """Nested dict usable as a render context, e.g. {"job_title": ..., "org": {"display_name": ...}}."""
    ctx: dict = {}
    for item in variable_catalog(company_name):
        parts = item["key"].split(".")
        node = ctx
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = item["sample"]
    return ctx


# Plain-language "what's missing" for each connection purpose (config health + settings).
PURPOSE_HEALTH: dict[str, tuple[str, str, str]] = {
    # purpose: (what's wrong + why, button label, settings page)
    "email.outbound.default": ("Emails can't be sent yet - connect a mailbox so the system can email candidates and staff.", "Connect mailbox", "/settings/communication/mailboxes"),
    "email.outbound.system": ("Sign-in and password emails can't be sent yet - connect a mailbox for system emails.", "Connect mailbox", "/settings/communication/mailboxes"),
    "email.inbound.negotiation_replies": ("Candidate replies about interview times aren't being read - connect the hiring mailbox.", "Connect mailbox", "/settings/communication/mailboxes"),
    "email.outbound.recruitment": ("Hiring emails can't be sent yet - connect the hiring mailbox.", "Connect mailbox", "/settings/communication/mailboxes"),
    "email.outbound.onboarding": ("Onboarding emails can't be sent yet - connect a mailbox for new joiners.", "Connect mailbox", "/settings/communication/mailboxes"),
    "email.inbound.helpdesk": ("Helpdesk emails aren't connected yet - connect a mailbox so employees can email the helpdesk.", "Connect mailbox", "/settings/communication/mailboxes"),
    "llm.resume_extraction": ("Resumes can't be read by AI yet - connect an AI provider.", "Connect AI", "/settings/integrations/ai"),
    "llm.judgment": ("AI help for reviews isn't set up - connect an AI provider.", "Connect AI", "/settings/integrations/ai"),
    "llm.copilot": ("The HR assistant can't answer yet - connect an AI provider.", "Connect AI", "/settings/integrations/ai"),
    "esign.offer_letters": ("Offer letters can't be e-signed yet - connect DocuSign or Leegality.", "Connect e-sign", "/settings/integrations/esign"),
}


def purpose_health(purpose: str) -> tuple[str, str, str]:
    return PURPOSE_HEALTH.get(purpose, ("A service this feature needs isn't connected yet.", "Open connections", "/settings/integrations"))
