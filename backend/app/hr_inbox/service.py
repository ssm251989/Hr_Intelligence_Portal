from typing import Optional

from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.candidate import Candidate
from app.models.hr_inbound_email import HrInboundEmail
from app.models.job_role import JobRole
from app.schemas.hr_integration import HrInboundEmailRead


def filtered_hr_inbox_query(
    db: Session,
    *,
    search: Optional[str] = None,
    matched: Optional[bool] = None,
):
    """Every HrInboundEmail row, joined out to the matched candidate's name and matched
    application's job title (outer joins -- an unmatched row still comes back with both
    null, never dropped). Shared by the List and Export endpoints so they can never define
    "which rows" differently."""
    query = (
        db.query(HrInboundEmail, Candidate.full_name, JobRole.title)
        .outerjoin(Candidate, Candidate.id == HrInboundEmail.matched_candidate_id)
        .outerjoin(Application, Application.id == HrInboundEmail.matched_application_id)
        .outerjoin(JobRole, JobRole.id == Application.job_role_id)
    )
    if search:
        pattern = f"%{search.strip()}%"
        query = query.filter(
            (HrInboundEmail.from_address.ilike(pattern)) | (HrInboundEmail.subject.ilike(pattern))
        )
    if matched is not None:
        if matched:
            query = query.filter(HrInboundEmail.matched_candidate_id.isnot(None))
        else:
            query = query.filter(HrInboundEmail.matched_candidate_id.is_(None))
    return query


def row_to_item(email: HrInboundEmail, candidate_name: Optional[str], job_title: Optional[str]) -> HrInboundEmailRead:
    return HrInboundEmailRead(
        id=email.id,
        from_address=email.from_address,
        to_address=email.to_address,
        subject=email.subject,
        body=email.body,
        received_at=email.received_at,
        message_id=email.message_id,
        matched_candidate_id=email.matched_candidate_id,
        matched_candidate_name=candidate_name,
        matched_application_id=email.matched_application_id,
        matched_job_title=job_title,
        created_at=email.created_at,
    )
