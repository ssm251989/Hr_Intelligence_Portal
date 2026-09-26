"""Shortlisting module (redesign): the 4-state decision stage right after AI screening --
Under Review, Shortlisted, On Hold, or Not Shortlisted. Deliberately NOT a new status column
or enum value: all four map directly onto Application.status values that already exist
(screened/hr_selected/on_hold/hr_rejected), and On Hold reuses the exact same generic
previous_status-restore mechanism (app/candidates/hold.py) every other pipeline stage's hold/
resume already goes through. This module is just this stage's own named view onto that shared
state machine, scoped to the applications actually paused *from* 'screened' -- an application
on_hold from some other stage (interviews, salary, BGV) is out of its scope entirely.
"""

from typing import Optional

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.candidates.hold import put_application_on_hold, resume_application_from_hold
from app.models.application import Application

UNDER_REVIEW = "under_review"
SHORTLISTED = "shortlisted"
ON_HOLD = "on_hold"
NOT_SHORTLISTED = "not_shortlisted"
SHORTLIST_STATUSES = (UNDER_REVIEW, SHORTLISTED, ON_HOLD, NOT_SHORTLISTED)

# The real Application.status each *decided* shortlist state literally is. ON_HOLD is
# deliberately absent here -- it isn't a single fixed target status, it's "on_hold" plus the
# hold mechanism's own previous_status bookkeeping (see update_shortlist_status below).
_DECIDED_STATUS_MAP = {SHORTLISTED: "hr_selected", NOT_SHORTLISTED: "hr_rejected"}

# Terminal shortlist states -- no further shortlisting-status change once reached, same
# "terminal by omission" convention as TERMINAL_APPLICATION_STATUSES elsewhere in this app.
TERMINAL_SHORTLIST_STATUSES = (SHORTLISTED, NOT_SHORTLISTED)


def shortlisting_hold_condition():
    """The shared filter expression for "on_hold, and paused specifically from the
    shortlisting stage" -- every query that needs this scoping (the List endpoint, the
    dashboard's On Hold funnel stage) uses this one definition so they can never drift
    apart from each other."""
    return and_(Application.status == "on_hold", Application.previous_status == "screened")


def shortlisting_scope_condition():
    """Every application this module considers part of its own worklist: screened (Under
    Review), hr_selected (Shortlisted), hr_rejected (Not Shortlisted), or on_hold from
    'screened' (On Hold). Anything else -- received, interview_*, salary_*, bgv_*, offer_*,
    onboarding_*, or on_hold from one of those other stages -- is out of scope."""
    return or_(Application.status.in_(("screened", "hr_selected", "hr_rejected")), shortlisting_hold_condition())


def shortlist_status_of(application: Application) -> Optional[str]:
    """The current shortlist status of one application, or None if it isn't part of this
    module's scope at all (see shortlisting_scope_condition)."""
    if application.status == "screened":
        return UNDER_REVIEW
    if application.status == "hr_selected":
        return SHORTLISTED
    if application.status == "hr_rejected":
        return NOT_SHORTLISTED
    if application.status == "on_hold" and application.previous_status == "screened":
        return ON_HOLD
    return None


def _salary_after_shortlist(db, application, actor) -> None:
    """Part 17.8: once Shortlisted, check the salary band and ask the candidate for missing figures."""
    try:
        from app.platform.tenancy.context import require_current_tenant
        from app.recruitment.salary_auto import after_shortlist

        after_shortlist(db, require_current_tenant(), application, actor=actor or "system")
    except Exception:  # noqa: BLE001 -- never blocks the shortlisting decision
        pass


def update_shortlist_status(
    db: Session,
    application: Application,
    target: str,
    actor: str,
    reason: Optional[str] = None,
    feedback: Optional[str] = None,
) -> Application:
    """Enforces this stage's own valid-transition rules:
      Under Review -> Shortlisted, On Hold, or Not Shortlisted.
      On Hold -> Under Review (resume, restoring the pre-hold status), Shortlisted, or Not
        Shortlisted.
      Shortlisted / Not Shortlisted are terminal -- no further shortlisting-status change,
      consistent with every other pipeline stage's terminal-state handling in this app.

    On Hold is entered/left via the exact same put_application_on_hold/
    resume_application_from_hold app/candidates/hold.py already provides -- this function
    adds nothing new to *how* on_hold works, only *when* it's a valid target here.
    """
    if target not in SHORTLIST_STATUSES:
        raise HTTPException(status_code=400, detail=f"target_status must be one of {SHORTLIST_STATUSES}")

    current = shortlist_status_of(application)
    if current is None:
        raise HTTPException(
            status_code=400,
            detail=f"Application status '{application.status}' is not part of the shortlisting stage.",
        )
    if current in TERMINAL_SHORTLIST_STATUSES:
        raise HTTPException(
            status_code=400, detail=f"'{current}' is terminal -- no further shortlisting status change."
        )
    if current == target:
        raise HTTPException(status_code=400, detail=f"Application is already '{target}'.")

    previous_shortlist_status = current
    previous_application_status = application.status

    if current == UNDER_REVIEW and target == ON_HOLD:
        put_application_on_hold(db, application, actor)
    elif current == ON_HOLD and target == UNDER_REVIEW:
        resume_application_from_hold(db, application, actor)
    else:
        # Under Review -> Shortlisted/Not Shortlisted, or On Hold -> Shortlisted/Not
        # Shortlisted (a direct decision made while paused -- leaves the hold state
        # entirely, so previous_status is cleared rather than left stale).
        application.previous_status = None
        application.status = _DECIDED_STATUS_MAP[target]
        db.commit()
        db.refresh(application)

    log_action(
        db,
        "application",
        application.id,
        "shortlist_status_updated",
        actor,
        {
            "previous_shortlist_status": previous_shortlist_status,
            "new_shortlist_status": target,
            "previous_application_status": previous_application_status,
            "new_application_status": application.status,
            "reason": reason,
            "feedback": feedback,
        },
    )
    if application.status == "hr_selected":
        _salary_after_shortlist(db, application, actor)
    return application
