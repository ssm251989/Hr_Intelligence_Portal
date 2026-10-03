"""Part 19.1: the ONE list of modules a company chooses ("Choose what you use").

Everything that depends on which modules a company has is driven from here:
- the cards in Setup and Settings > Company > Modules (emoji, name, one line, what you get),
- dependencies ("Needs: Screening") -- kept minimal, a module should work alone,
- the app pages and APIs of each module (ModuleActivationMiddleware answers 403
  "This module is not active for your company" for a module that is not active),
- the hiring stage order, so a stage of a switched-off module is skipped
  (no Salary -> straight from interview to offer),
- the email templates and background jobs that belong to a module.

Settings is always on. GenAI usage is included automatically with any AI module.
Status per company lives in `company_modules` (app/models/company_module.py), switched on
with an activation code from CTD Techs (app/platform/activation.py).
"""

import re
from dataclasses import dataclass, field
from typing import Optional

APP = r"/applications/[^/]+/"


@dataclass(frozen=True)
class Module:
    key: str
    emoji: str  # Fluent emoji name (frontend ui-kit Emoji)
    name: str
    line: str
    gets: tuple[str, ...]
    needs: tuple[str, ...] = ()
    pages: tuple[str, ...] = ()  # app pages (menu paths) of this module
    # API rules: a regex on the path; a leading "W:" limits it to write methods (shared reads stay open)
    apis: tuple[str, ...] = ()
    ai: bool = False  # uses GenAI -> GenAI usage is included
    included: bool = False  # not chosen on its own (GenAI usage)
    settings: tuple[str, ...] = field(default_factory=tuple)  # settings categories that belong to it


MODULES: tuple[Module, ...] = (
    Module("jobs", "briefcase", "Jobs", "Create jobs and post them everywhere.",
           ("Create jobs and job requests", "AI job description", "Post to your careers site", "LinkedIn, Naukri and other job boards"),
           pages=("/jobs",),
           apis=(r"^/api/v1/ui/jobs", r"^/api/v1/recruitment/(requisitions|jobs|pipeline-templates|knockout)", r"^/reports/(jobs|job-status)",
                 r"^/api/v1/ui/job-boards", r"W:^/jobs"),
           ai=True, settings=("hiring",)),
    Module("candidates", "technologist", "Candidates", "Bring every resume into one talent pool.",
           ("Fetch resumes from job boards, email or bulk upload", "AI resume parsing", "Candidate profiles", "Duplicates check"),
           pages=("/candidates", "/agencies"),
           apis=(r"^/candidates", r"^/local-import", r"^/api/v1/ui/candidates", r"^/reports/candidates-", r"^/api/v1/agencies", r"^/api/v1/agency-portal",
                 r"^/applications/?$", r"^/applications/[^/]+/?$"),
           ai=True),
    Module("screening", "magnifier", "Screening", "Score every candidate against the job.",
           ("AI match score", "Scoring rules", "Knock-out rules", "Score against a pasted job description"),
           needs=("candidates",), pages=("/screening",),
           apis=(r"^/screening", APP + r"(screen|rank)", r"^/api/v1/ui/screening", r"^/reports/screening-", r"^/api/v1/scoring"),
           ai=True),
    Module("shortlisting", "star", "Shortlisting", "Shortlist the best automatically.",
           ("Automatic shortlisting", "Undo window before anyone is told"),
           needs=("screening",), pages=("/shortlisting",),
           apis=(r"^/shortlisting", APP + r"shortlist-", r"^/reports/shortlisting-")),
    Module("interviews", "calendar", "Interviews", "Arrange interviews without the back-and-forth.",
           ("Scheduling", "Interviewer availability", "Scorecards"),
           needs=("candidates",), pages=("/interviews",),
           apis=(r"^/interviews", APP + r"(interviews|interview-questions)", r"^/interview-scheduling", r"^/api/v1/ui/interviews",
                 r"^/api/v1/ui/interviewers", r"^/api/v1/recruitment/interviewer-availability", r"^/reports/interviews-"),
           ai=True),
    Module("candidate_emails", "inbox", "Candidate emails", "Every candidate reply in one place.",
           ("Replies from candidates linked automatically",),
           needs=("candidates",), pages=("/hr-inbox", "/candidate-emails"),
           apis=(r"^/hr-inbox", r"^/api/v1/ui/hr-inbox", r"^/api/v1/ui/candidate-emails")),
    Module("salary", "money", "Salary", "Check salary before the offer.",
           ("Salary form", "Auto-approval within the band", "Department budgets"),
           needs=("candidates",), pages=("/salary",),
           apis=(APP + r"(validate-salary|salary|approve-salary)", r"^/api/v1/ui/salary", r"^/api/v1/ui/stage-table/salary", r"^/api/v1/ui/budgets")),
    Module("bgv", "shield", "Documents & BGV", "Collect documents and verify backgrounds.",
           ("Document collection", "AI document review", "Background verification decision"),
           needs=("candidates",), pages=("/bgv",),
           apis=(APP + r"bgv", r"^/api/v1/ui/stage-table/bgv", r"^/api/v1/ui/documents", r"^/api/v1/ui/bgv/"),
           ai=True),
    Module("offers", "envelope", "Offers", "Send the offer and welcome them.",
           ("Joining dates", "Offer letter", "E-sign", "Welcome email"),
           needs=("candidates",), pages=("/offers",),
           apis=(APP + r"offer", r"^/api/v1/ui/offers", r"^/api/v1/recruitment/(offers|offer-components)", r"^/api/v1/ui/stage-table/offers",
                 r"^/api/v1/ui/joining")),
    Module("onboarding", "waving_hand", "Onboarding", "Get new joiners ready before day one.",
           ("Pre-joining portal", "Joining checklist"),
           pages=("/onboarding",),
           apis=(r"^/api/v1/onboarding", r"^/api/v1/ui/onboarding", r"^/api/v1/public/onboarding", r"^/api/v1/public/ui/onboarding"),
           settings=("onboarding",)),
    Module("reports", "bar_chart", "Reports", "See how hiring is going.",
           ("Dashboards", "Exports"),
           pages=("/reports",),
           apis=(r"^/reports/(pipeline|audit)",)),
    Module("genai_usage", "robot", "GenAI usage", "See and limit AI use.",
           ("AI usage", "Limits"),
           pages=("/genai-usage",),
           apis=(r"^/api/v1/ui/genai/usage",),
           included=True),
)
BY_KEY: dict[str, Module] = {m.key: m for m in MODULES}
CHOOSABLE: tuple[str, ...] = tuple(m.key for m in MODULES if not m.included)
AI_MODULES: frozenset[str] = frozenset(m.key for m in MODULES if m.ai)

MODULE_NOT_ACTIVE = "This module is not active for your company"

# Hiring stages in order: (module, the application status that module's step ends with).
# A stage whose module is off is skipped: the next stage accepts the status of the nearest
# earlier stage that is on (see ready_statuses).
FLOW: tuple[tuple[str, str], ...] = (
    ("interviews", "interview_selected"),
    ("salary", "salary_approved"),
    ("bgv", "bgv_cleared"),
    ("offers", "offer_sent"),
)

# email templates (comms template_key) that belong to a module; not listed = always sent
TEMPLATE_MODULE: dict[str, str] = {
    "recruitment.job_closed_candidate": "jobs", "recruitment.job_requisition_approval": "jobs",
    "recruitment.agency_invite": "candidates", "recruitment.application": "candidates",
    "recruitment.shortlist_feedback": "shortlisting",
    "recruitment.interview_kit": "interviews", "recruitment.negotiation_reply": "interviews",
    "recruitment.salary_counter_offer": "salary", "recruitment.salary_details_request": "salary",
    "recruitment.bgv_unsuccessful": "bgv", "recruitment.document_check": "bgv", "recruitment.documents": "bgv",
    "recruitment.documents_request": "bgv", "recruitment.documents_reupload": "bgv",
    "recruitment.joining": "offers", "recruitment.joining_dates": "offers", "recruitment.offer_letter": "offers",
    "recruitment.offer_letter_auto": "offers", "recruitment.welcome_selected": "offers",
}
TEMPLATE_PREFIX_MODULE: dict[str, str] = {"onboarding.": "onboarding"}

# background jobs (platform/jobs/scheduled.py JOBS) that belong to a module
JOB_MODULE: dict[str, str] = {
    "onboarding_chase": "onboarding", "auto_shortlist_release": "shortlisting", "salary_form_reminders": "salary",
    "documents_reminders": "bgv", "joining_reminders": "offers",
}

WRITE = {"POST", "PUT", "PATCH", "DELETE"}
# never gated: signing in, the menu, module activation itself, health, candidate-facing public pages
# (except the onboarding portal, which belongs to Onboarding)
EXEMPT = re.compile(r"^/(auth|health|healthz|readyz|metrics|docs|redoc|openapi\.json)|^/api/me/|^/api/v1/modules|^/api/v1/superadmin"
                    r"|^/api/v1/public/(?!(ui/)?onboarding)|^/public/|^/interview-(confirm|negotiation)/")
_COMPILED = [(m.key, [(r.startswith("W:"), re.compile(r[2:] if r.startswith("W:") else r)) for r in m.apis]) for m in MODULES]


def module_for_api(path: str, method: str) -> Optional[str]:
    if EXEMPT.search(path):
        return None
    for key, rules in _COMPILED:
        for write_only, rx in rules:
            if rx.search(path) and (not write_only or method in WRITE):
                return key
    return None


def module_for_page(path: str) -> Optional[str]:
    for m in MODULES:
        if any(path == p or path.startswith(p + "/") for p in m.pages):
            return m.key
    return None


def module_for_template(template_key: str) -> Optional[str]:
    if template_key in TEMPLATE_MODULE:
        return TEMPLATE_MODULE[template_key]
    return next((mod for prefix, mod in TEMPLATE_PREFIX_MODULE.items() if template_key.startswith(prefix)), None)


def with_included(active: set[str]) -> set[str]:
    """Adds GenAI usage when any AI module is active."""
    return active | {"genai_usage"} if active & AI_MODULES else set(active)


def missing_needs(keys: set[str]) -> dict[str, list[str]]:
    """{module: [needed modules not in keys]} for every module in keys."""
    return {k: [n for n in BY_KEY[k].needs if n not in keys] for k in keys if k in BY_KEY and any(n not in keys for n in BY_KEY[k].needs)}


def with_needs(keys: set[str]) -> set[str]:
    """keys plus everything they need, transitively."""
    out, todo = set(), list(keys)
    while todo:
        k = todo.pop()
        if k in out or k not in BY_KEY:
            continue
        out.add(k)
        todo.extend(BY_KEY[k].needs)
    return out


def needed_by(key: str, keys: set[str]) -> list[str]:
    """Modules in keys that need `key` (switching it off would break them)."""
    return sorted(k for k in keys if k in BY_KEY and key in BY_KEY[k].needs)


def ready_statuses(active: set[str], stage: str) -> set[str]:
    """The application statuses from which `stage` (a FLOW module) may start, skipping
    stages whose module is off. E.g. offers with Salary and BGV off -> {"bgv_cleared",
    "salary_approved", "interview_selected"}."""
    order = [m for m, _s in FLOW]
    out: set[str] = set()
    for module, status in reversed(FLOW[: order.index(stage)]):
        out.add(status)
        if module in active:
            break
    return out


def catalog() -> list[dict]:
    return [{"key": m.key, "emoji": m.emoji, "name": m.name, "line": m.line, "gets": list(m.gets), "needs": list(m.needs),
             "ai": m.ai, "included": m.included, "pages": list(m.pages)} for m in MODULES]
