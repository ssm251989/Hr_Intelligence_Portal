"""Part 15 step 15.4 (docs/HRMS_COMPLETE_SPEC.txt section L, INTERVIEWS + HR INBOX): small
read/assign helpers the restyled Interviews and HR Inbox screens need and the existing
routers don't expose. No new tables -- everything reads the existing interviews,
hr_inbound_emails and message_templates rows (tenant-filtered by the TenantOwned ORM hook,
and the explicit tenant filter where the neighbours use one).

  GET  /api/v1/ui/interviews/mine               I2 "My interviews" (interviewer's own rows)
  GET  /api/v1/ui/interviews/{id}/panel         I6 other panel members' feedback -- hidden
                                                until the caller has submitted their own
  GET  /api/v1/ui/hr-inbox/{id}/thread          H1 thread pane (every mail from that sender)
  POST /api/v1/ui/hr-inbox/{id}/assign          H3 link unmatched mail to a candidate
  GET  /api/v1/ui/hr-inbox/snippets             H4 reply snippets from published templates
"""

import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.auth.dependencies import get_current_user, require_roles
from app.core.database import get_db
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.hr_inbound_email import HrInboundEmail
from app.models.interview import Interview
from app.models.job_role import JobRole
from app.models.user import User
from app.reports import stats
from app.scheduling.router import interview_row_to_item

router = APIRouter(prefix="/api/v1/ui", tags=["ui-interviews-inbox"])

_INTERVIEW_ROLES = ("recruiter", "interviewer", "hiring_manager", "admin")
_INBOX_ROLES = ("recruiter", "hiring_manager", "admin")


def _feedback_submitted(interview: Interview) -> bool:
    return any(
        v is not None and v != ""
        for v in (interview.technical_rating, interview.communication_rating, interview.overall_rating, interview.comments, interview.decision)
    )


def _is_mine(interview: Interview, user: User) -> bool:
    if interview.interviewer_id is not None and interview.interviewer_id == user.id:
        return True
    return bool(interview.interviewer_email and user.email and interview.interviewer_email.strip().lower() == user.email.strip().lower())


# ---------------------------------------------------------------- interviews


class MyInterviewRow(BaseModel):
    interview: dict
    candidate_location: Optional[str] = None
    candidate_phone: Optional[str] = None
    total_experience_years: Optional[float] = None
    top_skills: list[str] = []
    missing_skills: list[str] = []
    match_score: Optional[float] = None
    composite_score: Optional[float] = None  # Part 17.4: the one Match score
    feedback_submitted: bool = False


@router.get("/interviews/mine", response_model=list[MyInterviewRow])
def my_interviews(
    include_done: bool = Query(True, description="Also return interviews that already have a decision"),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Interviews where the caller is the interviewer -- by user id, or by the plain-text
    interviewer email the negotiation flow records when no user id was attached."""
    now = datetime.now(timezone.utc)
    status_expr = stats.interview_status_case(now)
    mine = Interview.interviewer_id == current_user.id
    if current_user.email:
        mine = or_(mine, func.lower(Interview.interviewer_email) == current_user.email.strip().lower())
    query = (
        db.query(Interview, Application, Candidate, JobRole.title, User, status_expr.label("computed_status"))
        .join(Application, Application.id == Interview.application_id)
        .join(Candidate, Candidate.id == Application.candidate_id)
        .join(JobRole, JobRole.id == Application.job_role_id)
        .outerjoin(User, User.id == Interview.interviewer_id)
        .filter(mine)
    )
    if not include_done:
        query = query.filter(Interview.decision.is_(None))
    rows = query.order_by(Interview.scheduled_at.asc().nullslast()).limit(limit).all()
    out: list[MyInterviewRow] = []
    for interview, application, candidate, job_title, interviewer, computed_status in rows:
        parsed = candidate.parsed_fields or {}
        skills = parsed.get("skills") or []
        out.append(
            MyInterviewRow(
                interview=interview_row_to_item(interview, application, candidate, job_title, interviewer, computed_status).model_dump(mode="json"),
                candidate_location=candidate.location,
                candidate_phone=candidate.phone,
                total_experience_years=parsed.get("total_experience_years"),
                top_skills=[str(s) for s in skills[:8]],
                missing_skills=[str(s) for s in (application.missing_skills or [])[:8]],
                match_score=float(application.match_score) if application.match_score is not None else None,
                composite_score=float(application.composite_score) if application.composite_score is not None else None,
                feedback_submitted=_feedback_submitted(interview),
            )
        )
    return out


class PanelEntry(BaseModel):
    interview_id: uuid.UUID
    interviewer_name: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    technical_rating: Optional[int] = None
    communication_rating: Optional[int] = None
    overall_rating: Optional[int] = None
    comments: Optional[str] = None
    decision: Optional[str] = None
    submitted: bool = False


class PanelFeedback(BaseModel):
    hidden: bool
    my_feedback_submitted: bool
    is_panel_member: bool
    others: list[PanelEntry] = []


@router.get("/interviews/{interview_id}/panel", response_model=PanelFeedback)
def panel_feedback(
    interview_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*_INTERVIEW_ROLES)),
):
    """Everyone else's feedback on the same application. If the caller interviewed this
    candidate themselves and has not submitted their own feedback yet, the others are
    withheld (spec I6) -- enforced here, not just hidden in the browser."""
    interview = db.get(Interview, interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    siblings = db.query(Interview).filter(Interview.application_id == interview.application_id).all()
    my_rows = [i for i in siblings if _is_mine(i, current_user)]
    is_member = bool(my_rows)
    mine_done = is_member and all(_feedback_submitted(i) for i in my_rows)
    hidden = is_member and not mine_done
    if hidden:
        return PanelFeedback(hidden=True, my_feedback_submitted=False, is_panel_member=True, others=[])

    user_ids = {i.interviewer_id for i in siblings if i.interviewer_id}
    names = {u.id: (u.full_name or u.email) for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
    others = [
        PanelEntry(
            interview_id=i.id,
            interviewer_name=names.get(i.interviewer_id) or i.interviewer_name,
            scheduled_at=i.scheduled_at,
            technical_rating=i.technical_rating,
            communication_rating=i.communication_rating,
            overall_rating=i.overall_rating,
            comments=i.comments,
            decision=i.decision,
            submitted=_feedback_submitted(i),
        )
        for i in sorted(siblings, key=lambda x: x.scheduled_at or datetime.min.replace(tzinfo=timezone.utc))
        if i.id != interview.id and not _is_mine(i, current_user)
    ]
    return PanelFeedback(hidden=False, my_feedback_submitted=mine_done, is_panel_member=is_member, others=others)


# ---------------------------------------------------------------- HR inbox


class ThreadMessage(BaseModel):
    id: uuid.UUID
    from_address: str
    to_address: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    received_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    matched_candidate_id: Optional[uuid.UUID] = None
    matched_application_id: Optional[uuid.UUID] = None


class InboxThread(BaseModel):
    messages: list[ThreadMessage]


def _thread_message(e: HrInboundEmail) -> ThreadMessage:
    return ThreadMessage(
        id=e.id, from_address=e.from_address, to_address=e.to_address, subject=e.subject, body=e.body,
        received_at=e.received_at, created_at=e.created_at,
        matched_candidate_id=e.matched_candidate_id, matched_application_id=e.matched_application_id,
    )


@router.get("/hr-inbox/{email_id}/thread", response_model=InboxThread)
def inbox_thread(
    email_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*_INBOX_ROLES)),
):
    """The selected message plus every other message from the same sender, oldest first."""
    email = db.get(HrInboundEmail, email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Message not found")
    rows = (
        db.query(HrInboundEmail)
        .filter(func.lower(HrInboundEmail.from_address) == email.from_address.strip().lower())
        .order_by(func.coalesce(HrInboundEmail.received_at, HrInboundEmail.created_at).desc())
        .limit(limit)
        .all()
    )
    if email.id not in {r.id for r in rows}:
        rows.append(email)
    rows.sort(key=lambda r: r.received_at or r.created_at or datetime.min.replace(tzinfo=timezone.utc))
    return InboxThread(messages=[_thread_message(r) for r in rows])


class AssignRequest(BaseModel):
    application_id: uuid.UUID
    include_same_sender: bool = True


class AssignResult(BaseModel):
    assigned: int
    candidate_id: uuid.UUID
    application_id: uuid.UUID


@router.post("/hr-inbox/{email_id}/assign", response_model=AssignResult)
def assign_inbox_email(
    email_id: uuid.UUID,
    payload: AssignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*_INBOX_ROLES)),
):
    """Links an unmatched message (and, optionally, the sender's other unmatched messages)
    to a candidate's application. Already-matched mail is never re-pointed here."""
    email = db.get(HrInboundEmail, email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Message not found")
    if email.matched_candidate_id is not None:
        raise HTTPException(status_code=409, detail="This message is already linked to a candidate")
    application = db.get(Application, payload.application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    targets = [email]
    if payload.include_same_sender:
        targets = (
            db.query(HrInboundEmail)
            .filter(
                func.lower(HrInboundEmail.from_address) == email.from_address.strip().lower(),
                HrInboundEmail.matched_candidate_id.is_(None),
            )
            .all()
        )
        if email not in targets:
            targets.append(email)
    for row in targets:
        row.matched_candidate_id = application.candidate_id
        row.matched_application_id = application.id
    db.commit()
    log_action(
        db,
        "application",
        application.id,
        "hr_inbox_email_assigned",
        current_user.email,
        {"email_ids": [str(r.id) for r in targets], "from": email.from_address, "subject": email.subject},
    )
    return AssignResult(assigned=len(targets), candidate_id=application.candidate_id, application_id=application.id)


class Snippet(BaseModel):
    key: str
    locale: str
    subject: Optional[str] = None
    text: str


_TAG = re.compile(r"<[^>]+>")


def _plain(html: Optional[str]) -> str:
    if not html:
        return ""
    text = re.sub(r"<\s*br\s*/?>|</p\s*>|</div\s*>", "\n", html, flags=re.I)
    text = _TAG.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


@router.get("/hr-inbox/snippets", response_model=list[Snippet])
def reply_snippets(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*_INBOX_ROLES)),
):
    """The latest PUBLISHED version of every email template, as plain text a recruiter can
    drop into a reply. Read-only; editing templates stays admin-only in Settings."""
    from app.models.comms import MessageTemplate
    from app.platform.tenancy.context import require_current_tenant

    tenant = require_current_tenant()
    latest = (
        db.query(MessageTemplate.key, MessageTemplate.locale, func.max(MessageTemplate.version).label("v"))
        .filter(MessageTemplate.tenant_id == tenant.tenant_id, MessageTemplate.channel == "email", MessageTemplate.status == "published")
        .group_by(MessageTemplate.key, MessageTemplate.locale)
        .subquery()
    )
    rows = (
        db.query(MessageTemplate)
        .join(
            latest,
            (MessageTemplate.key == latest.c.key) & (MessageTemplate.locale == latest.c.locale) & (MessageTemplate.version == latest.c.v),
        )
        .filter(MessageTemplate.tenant_id == tenant.tenant_id, MessageTemplate.channel == "email", MessageTemplate.status == "published")
        .order_by(MessageTemplate.key, MessageTemplate.locale)
        .all()
    )
    out = []
    for t in rows:
        text = (t.text_tpl or "").strip() or _plain(t.html_tpl)
        if text:
            out.append(Snippet(key=t.key, locale=t.locale, subject=t.subject_tpl, text=text))
    return out
