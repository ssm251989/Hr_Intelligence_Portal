"""Fix 2026-10-05: ONE place that decides where a joiner is and which actions are valid.

Stages (from the real records, never from which button the page happened to show):
  before_joining  offer signed / onboarding open, joining date in the future
  joining_due     joining date today or past, not marked joined yet
  joined          converted to an employee (case "joined" / employee active)
  closed          withdrawn, declined, did not join, or left after joining

Actions per stage:
  before_joining  withdraw_offer (company decision), candidate_declined
  joining_due     mark_joined, no_show          (withdraw / decline still allowed -- they haven't joined)
  joined          not_reporting (starts the absconding flow), absconded, resigned, terminated
  closed          none
Withdrawing an offer is NEVER allowed once someone has joined: use absconded / resigned / terminated.
The board shows exactly `allowed_actions()`, and every endpoint calls `require()` first, so a stale
page or a direct API call gets a plain "not allowed" message too.
"""

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.onboarding import PreboardingCase

PRE_JOIN = ("withdraw_offer", "candidate_declined")
DUE = ("mark_joined", "no_show")
POST_JOIN = ("not_reporting", "absconded", "resigned", "terminated")

MESSAGES = {
    "joined": "{name} has already joined, so the offer can't be withdrawn or declined. Use Absconded, Resigned or Terminated instead.",
    "not_due": "{name}'s joining date is {date}. You can mark them joined, or as didn't join, from that day.",
    "not_joined": "{name} hasn't joined yet, so this is not an exit. Withdraw the offer, mark as declined, or mark as didn't join instead.",
    "closed": "{name}'s record is already closed ({how}). Nothing more can be done here.",
}
CLOSED_LABEL = {"revoked": "offer withdrawn", "declined": "offer declined", "no_show": "did not join", "exited": "left the company"}


class ActionNotAllowed(Exception):
    def __init__(self, message: str, code: str = "ACTION_NOT_ALLOWED"):
        super().__init__(message)
        self.code = code


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _employee(db: Session, case: PreboardingCase):
    from app.models.core_hr import Employee

    return db.get(Employee, case.employee_id) if case.employee_id else None


def stage(db: Session, case: PreboardingCase, today: Optional[date] = None) -> str:
    today = today or _today()
    if case.status in ("revoked", "declined", "no_show", "exited"):
        return "closed"
    emp = _employee(db, case)
    if case.status == "joined" or (emp is not None and emp.status not in ("pre_hire", "inactive")):
        exit_ = (case.attributes_json or {}).get("exit") or {}
        return "closed" if exit_.get("status") == "done" else "joined"
    return "joining_due" if case.joining_date <= today else "before_joining"


def allowed_actions(db: Session, case: PreboardingCase, today: Optional[date] = None) -> list[str]:
    st = stage(db, case, today)
    if st == "before_joining":
        return list(PRE_JOIN)
    if st == "joining_due":
        return list(DUE) + list(PRE_JOIN)
    if st == "joined":
        flow = ((case.attributes_json or {}).get("not_reporting") or {}).get("status") == "active"
        return [a for a in POST_JOIN if not (a == "not_reporting" and flow)] + (["stop_not_reporting"] if flow else [])
    return []


def require(db: Session, case: PreboardingCase, action: str, name: str = "This person", today: Optional[date] = None) -> None:
    if action in allowed_actions(db, case, today):
        return
    st = stage(db, case, today)
    if st == "closed":
        how = CLOSED_LABEL.get(case.status) or CLOSED_LABEL["exited"]
        raise ActionNotAllowed(MESSAGES["closed"].format(name=name, how=how))
    if st == "joined":
        raise ActionNotAllowed(MESSAGES["joined"].format(name=name))
    if action in DUE:
        raise ActionNotAllowed(MESSAGES["not_due"].format(name=name, date=case.joining_date.strftime("%d %b %Y")))
    raise ActionNotAllowed(MESSAGES["not_joined"].format(name=name))
