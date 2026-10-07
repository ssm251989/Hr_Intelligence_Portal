"""Part 17.7: "Candidate emails" (was HR Inbox) -- replies from candidates to the company's
emails, each linked to the right candidate automatically where possible.

- GET  /api/v1/ui/candidate-emails?tab=needs_action|linked|closed&search=&page=&page_size=
       (Part 22.2: "Not matched" is gone -- unlinked mail is in Needs action with a "Not linked yet" chip
       and suggested candidates; Closed = what HR marked done, or automatic / no-action mail)
- POST /api/v1/ui/candidate-emails/rematch     run the matching rules over every unlinked email
       rows with candidate, job, what it's about (topic + one-line summary), status; tab counts;
       whether a mailbox is connected (for the empty state)
- POST /api/v1/ui/candidate-emails/{id}/done   {"done": true|false}
Linking an unmatched email stays on POST /api/v1/ui/hr-inbox/{id}/assign; the thread pane on
GET /api/v1/ui/hr-inbox/{id}/thread.
"""

from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.auth.dependencies import require_roles
from app.core.database import get_db
from app.hr_inbox import matching
from app.hr_inbox.triage import triage
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.hr_inbound_email import HrInboundEmail
from app.models.job_role import JobRole
from app.models.user import User
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/ui/candidate-emails", tags=["ui-candidate-emails"])
_ROLES = ("recruiter", "hiring_manager", "admin")
AI_SUMMARIES_PER_PAGE = 5  # keeps the page quick; the rest get the text summary now, AI later


def _mailbox_connected(db: Session) -> bool:
    try:
        from app.integrations.hr_email import get_hr_integration
        from app.integrations.imap_poll import is_imap_configured

        if is_imap_configured(get_hr_integration(db)):
            return True
    except Exception:  # noqa: BLE001
        pass
    from app.models.connection import ConnectionRoute

    return db.query(ConnectionRoute.id).filter(ConnectionRoute.purpose.like("email.inbound.%"), ConnectionRoute.enabled.is_(True)).first() is not None


def _base(db: Session, tenant, search: Optional[str]):
    q = db.query(HrInboundEmail).filter(HrInboundEmail.tenant_id == tenant.tenant_id)
    if search:
        pattern = f"%{search.strip()}%"
        q = q.filter(or_(HrInboundEmail.from_address.ilike(pattern), HrInboundEmail.subject.ilike(pattern), HrInboundEmail.summary.ilike(pattern)))
    return q


TABS = ("needs_action", "linked", "closed")


def _tab(q, tab: str):
    if tab == "needs_action":
        return q.filter(HrInboundEmail.status != "done")
    if tab == "linked":
        return q.filter(HrInboundEmail.matched_candidate_id.isnot(None))
    return q.filter(HrInboundEmail.status == "done")


@router.get("")
def list_candidate_emails(tab: Literal["needs_action", "linked", "closed", "not_matched"] = "needs_action", search: Optional[str] = None,
                          page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), db: Session = Depends(get_db),
                          current_user: User = Depends(require_roles(*_ROLES))):
    tenant = require_current_tenant()
    tab = "needs_action" if tab == "not_matched" else tab  # old links
    base = _base(db, tenant, search)
    rows = _tab(base, tab).order_by(func.coalesce(HrInboundEmail.received_at, HrInboundEmail.created_at).desc()) \
        .offset((page - 1) * page_size).limit(page_size).all()
    ai_left = AI_SUMMARIES_PER_PAGE
    cand_ids = {r.matched_candidate_id for r in rows if r.matched_candidate_id}
    app_ids = {r.matched_application_id for r in rows if r.matched_application_id}
    names = {c.id: c.full_name for c in db.query(Candidate).filter(Candidate.id.in_(cand_ids))} if cand_ids else {}
    jobs = dict(db.query(Application.id, JobRole.title).join(JobRole, JobRole.id == Application.job_role_id)
                .filter(Application.id.in_(app_ids)).all()) if app_ids else {}
    items = []
    for r in rows:
        use_ai = ai_left > 0 and not r.summary
        triage(db, tenant, r, use_ai=use_ai)
        if use_ai:
            ai_left -= 1
        items.append({
            "id": str(r.id), "from_address": r.from_address, "subject": r.subject,
            "received_at": (r.received_at or r.created_at).isoformat() if (r.received_at or r.created_at) else None,
            "candidate_id": str(r.matched_candidate_id) if r.matched_candidate_id else None,
            "candidate_name": names.get(r.matched_candidate_id), "application_id": str(r.matched_application_id) if r.matched_application_id else None,
            "job_title": jobs.get(r.matched_application_id), "topic": r.topic, "summary": r.summary, "summary_source": r.summary_source,
            "status": r.status, "done_at": r.done_at.isoformat() if r.done_at else None, "done_by": r.done_by,
            "from_name": r.from_name, "match_rule": r.match_rule,
            "suggestions": matching.suggestion_rows(db, r.match_suggestions_json) if not r.matched_candidate_id else [],
        })
    counts = {t: _tab(base, t).count() for t in TABS}  # after triage (automatic mail -> done)
    return {"tab": tab, "items": items, "counts": counts, "page": page, "page_size": page_size,
            "total": counts[tab], "mailbox_connected": _mailbox_connected(db)}


class DoneIn(BaseModel):
    done: bool = True


@router.post("/{email_id}/done")
def mark_done(email_id: UUID, payload: DoneIn, db: Session = Depends(get_db), current_user: User = Depends(require_roles(*_ROLES))):
    tenant = require_current_tenant()
    row = db.query(HrInboundEmail).filter(HrInboundEmail.tenant_id == tenant.tenant_id, HrInboundEmail.id == email_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Email not found")
    row.status = "done" if payload.done else "needs_action"
    row.done_at = datetime.now(timezone.utc) if payload.done else None
    row.done_by = current_user.email if payload.done else None
    db.commit()
    if row.matched_candidate_id:
        log_action(db, "candidate", row.matched_candidate_id, "candidate_email_done" if payload.done else "candidate_email_reopened",
                   current_user.email[:50], {"hr_inbound_email_id": str(row.id), "subject": row.subject})
    return {"id": str(row.id), "status": row.status}


@router.post("/rematch")
def rematch(db: Session = Depends(get_db), current_user: User = Depends(require_roles(*_ROLES))):
    """Part 22.2: run the matching rules over every email that isn't linked yet."""
    return matching.rematch_unmatched(db, require_current_tenant(), actor=current_user.email)
