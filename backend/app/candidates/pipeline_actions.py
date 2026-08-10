"""Computes the valid next pipeline action(s) for an application's current status.

This is deliberately a read-only *lookup*, not a new transition mechanism: every action
it returns points at an endpoint that already exists in screening/shortlisting/scheduling/
salary/bgv/offers. "Move Stage" on the Candidate Detail page is a shortcut menu into this
table, not a free-form status dropdown -- there is no way to jump a candidate past a real
precondition (e.g. straight to offer_sent skipping salary approval) through this module.

Two kinds of action:
  - "one_click": the transition takes no input beyond an optional fixed decision body, so
    the frontend can call the existing endpoint directly with a confirm step.
  - "navigate": the transition needs real input the existing dedicated page already
    collects (an interview slot + interviewer, a salary override amount, BGV documents, an
    offer start date) -- rather than rebuilding those forms a second time, the action sends
    the recruiter to that existing page with the relevant job preselected.
"""

import uuid

from sqlalchemy.orm import Session

from app.models.application import TERMINAL_APPLICATION_STATUSES, Application
from app.models.bgv_document import BgvDocument
from app.models.interview import Interview
from app.schemas.candidates_dashboard import NextAction

_TERMINAL_STATUSES = set(TERMINAL_APPLICATION_STATUSES)


def _job_route(path: str, job_role_id: uuid.UUID) -> str:
    return f"{path}?jobId={job_role_id}"


def compute_next_actions(db: Session, application: Application) -> list[NextAction]:
    status = application.status
    app_id = application.id
    job_id = application.job_role_id

    if status in _TERMINAL_STATUSES:
        return []

    if status == "received":
        return [
            NextAction(
                key="screen",
                label="Screen Candidate",
                kind="one_click",
                method="POST",
                endpoint=f"/applications/{app_id}/screen",
                description="Runs the AI resume-match screen. Requires the job's JD to be generated and the candidate's resume to be parsed.",
            )
        ]

    if status == "screened":
        return [
            NextAction(
                key="shortlist_select",
                label="Shortlist: Select",
                kind="one_click",
                method="POST",
                endpoint=f"/applications/{app_id}/shortlist-decision",
                body={"decision": "select"},
            ),
            NextAction(
                key="shortlist_reject",
                label="Shortlist: Reject",
                kind="one_click",
                method="POST",
                endpoint=f"/applications/{app_id}/shortlist-decision",
                body={"decision": "reject"},
                confirm=True,
            ),
        ]

    if status in ("hr_selected", "interview_selected"):
        actions = [
            NextAction(
                key="validate_salary",
                label="Validate Salary",
                kind="one_click",
                method="POST",
                endpoint=f"/applications/{app_id}/validate-salary",
                description="Requires an expected salary on the application and the job's salary band to be set.",
            )
        ]
        if status == "hr_selected":
            actions.insert(
                0,
                NextAction(
                    key="schedule_interview",
                    label="Schedule Interview",
                    kind="navigate",
                    route=_job_route("/interviews", job_id),
                    description="Needs a date/time and interviewer -- opens the Interviews page.",
                ),
            )
        return actions

    if status == "interview_scheduled":
        interview = (
            db.query(Interview)
            .filter(Interview.application_id == app_id)
            .order_by(Interview.created_at.desc())
            .first()
        )
        if not interview:
            return [
                NextAction(
                    key="manage_interview",
                    label="Manage Interview",
                    kind="navigate",
                    route=_job_route("/interviews", job_id),
                )
            ]
        return [
            NextAction(
                key="interview_selected",
                label="Interview Feedback: Selected",
                kind="one_click",
                method="PATCH",
                endpoint=f"/interviews/{interview.id}/feedback",
                body={"decision": "selected"},
            ),
            NextAction(
                key="interview_rejected",
                label="Interview Feedback: Rejected",
                kind="one_click",
                method="PATCH",
                endpoint=f"/interviews/{interview.id}/feedback",
                body={"decision": "rejected"},
                confirm=True,
            ),
        ]

    if status == "salary_ok":
        return [
            NextAction(
                key="confirm_salary",
                label="Confirm Salary",
                kind="one_click",
                method="POST",
                endpoint=f"/applications/{app_id}/salary/confirm",
            )
        ]

    if status == "salary_above_band":
        return [
            NextAction(
                key="approve_salary",
                label="Approve/Reject Salary",
                kind="navigate",
                route=_job_route("/salary", job_id),
                description="Expected salary is above the job's band -- needs an approval decision and optional override amount.",
            )
        ]

    if status in ("bgv_requested", "bgv_pending"):
        documents = db.query(BgvDocument).filter(BgvDocument.application_id == app_id).all()
        ready_to_clear = bool(documents) and all(doc.validation_status == "valid" for doc in documents)
        actions = [
            NextAction(
                key="manage_bgv_documents",
                label="Manage BGV Documents",
                kind="navigate",
                route=_job_route("/bgv", job_id),
            ),
            NextAction(
                key="bgv_reject",
                label="Reject BGV",
                kind="one_click",
                method="POST",
                endpoint=f"/applications/{app_id}/bgv/clear",
                body={"decision": "reject"},
                confirm=True,
            ),
        ]
        if ready_to_clear:
            actions.insert(
                1,
                NextAction(
                    key="bgv_clear",
                    label="Clear BGV",
                    kind="one_click",
                    method="POST",
                    endpoint=f"/applications/{app_id}/bgv/clear",
                    body={"decision": "clear"},
                    confirm=True,
                ),
            )
        return actions

    if status == "bgv_cleared":
        return [
            NextAction(
                key="generate_offer",
                label="Generate Offer",
                kind="navigate",
                route=_job_route("/offers", job_id),
                description="Needs a start date -- opens the Offers page.",
            )
        ]

    if status == "offer_sent":
        return [
            NextAction(
                key="mark_signed",
                label="Mark Offer Signed",
                kind="one_click",
                method="POST",
                endpoint=f"/applications/{app_id}/offer/mark-signed",
                body={},
                confirm=True,
                description="If a real DocuSign envelope was sent, this verifies its live signing status instead of accepting a manual claim.",
            )
        ]

    if status == "onboarding_started":
        return [
            NextAction(
                key="complete_onboarding",
                label="Complete Onboarding",
                kind="one_click",
                method="POST",
                endpoint=f"/applications/{app_id}/offer/complete-onboarding",
                body={},
            )
        ]

    return []
