"""Which HR-assistant questions go to the agent team.

An HR TASK anywhere from hiring to exit ("create a job for a Python developer and screen the
applicants", "shortlist the top 3 for the Java role", "check Priya's salary and send her the
documents form", "propose joining dates for Arun", "who joins this week", "what blocks
Ravi's relieving letter") goes to the agent team. Questions about the asker's own data
("my offer", "my leave") never do, and copilot/service.py only sends people with an HR
permission (HR_PERMISSIONS) to the team. Policy questions, personal data and small talk keep
the existing path (handbook answers with sources, my-data tools, drafts) -- that path is
already tested and the team would only add cost there.

A cheap word check, no model call: a task needs an action word AND a hiring object.
English only for now; Hindi/Tamil questions keep the existing path.
"""

import re

_ACTION = re.compile(
    r"\b(create|open|post|add|set up|setup|draft|write|prepare|screen|rank|score|shortlist|short-list|find|search|compare|evaluate|"
    r"review|schedule|start|arrange|book|check|list|show|move|send|resend|re-send|remind|chase|follow up|propose|approve|assign|verify|"
    r"track|issue|prepare|record|mark|confirm|what is pending|what's pending|who joins|who is joining|where is|status of|blocks?)\b", re.I)
_OBJECT = re.compile(
    r"\b(job|jobs|jd|job description|role|roles|position|positions|opening|openings|vacanc(y|ies)|requisition|candidate|candidates|"
    r"applicant|applicants|application|applications|resume|resumes|cv|cvs|shortlist|interview|interviews|salary|salaries|ctc|"
    r"offer|offers|joining|joiner|joiners|joining date|documents|docs|bgv|background verification|background check|vendor|"
    r"onboarding|pre-boarding|preboarding|new hire|new hires|exit|exits|resignation|resignations|relieving|clearance|"
    r"experience letter|exit interview|leaver|leavers)\b", re.I)
# the asker's own data stays on the self-service path ("show my offer letter", "check my leave")
_PERSONAL = re.compile(r"\b(my|mine)\b", re.I)
# questions the existing my-data tools already answer quickly
_EXISTING_TOOL = re.compile(r"^\s*(how many open jobs|which candidates are waiting for an interview)\b", re.I)


def looks_like_task(question: str) -> bool:
    q = question or ""
    if len(q.split()) < 3 or _EXISTING_TOOL.search(q) or _PERSONAL.search(q):
        return False
    return bool(_ACTION.search(q) and _OBJECT.search(q))


# Any one of these lets a person use the agent team (each tool still checks its own permission).
HR_PERMISSIONS = ("recruitment.job.view", "recruitment.application.view", "recruitment.bgv.view", "recruitment.offer.view",
                  "onboarding.preboarding.view", "separation.case.view")
