from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_roles
from app.core.database import get_db
from app.hr_inbox.service import filtered_hr_inbox_query, row_to_item
from app.integrations.hr_email import encrypted_smtp_password, get_hr_integration, is_smtp_configured, send_hr_email, SmtpError
from app.integrations.imap_poll import ImapError, is_imap_configured, test_imap_connection
from app.models.hr_inbound_email import HrInboundEmail
from app.models.user import User
from app.schemas.hr_integration import (
    HrIntegrationRead,
    HrIntegrationUpdate,
    HrInboundEmailRead,
    HrInboxListPage,
    SendTestEmailRequest,
    SendTestEmailResult,
    TestImapConnectionResult,
)

router = APIRouter(tags=["hr-inbox"])


def _to_read(hr_integration) -> HrIntegrationRead:
    return HrIntegrationRead(
        smtp_host=hr_integration.smtp_host,
        smtp_port=hr_integration.smtp_port,
        use_tls=hr_integration.use_tls,
        smtp_username=hr_integration.smtp_username,
        from_address=hr_integration.from_address,
        hr_module_email=hr_integration.hr_module_email,
        smtp_configured=is_smtp_configured(hr_integration),
        imap_host=hr_integration.imap_host,
        imap_port=hr_integration.imap_port,
        use_ssl=hr_integration.use_ssl,
        imap_configured=is_imap_configured(hr_integration),
    )


@router.get("/hr-inbox/settings", response_model=HrIntegrationRead)
def get_hr_inbox_settings(
    db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin")),
):
    return _to_read(get_hr_integration(db))


@router.put("/hr-inbox/settings", response_model=HrIntegrationRead)
def update_hr_inbox_settings(
    payload: HrIntegrationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
):
    hr_integration = get_hr_integration(db)
    updates = payload.model_dump(exclude_unset=True, exclude={"smtp_password"})
    for field, value in updates.items():
        setattr(hr_integration, field, value)
    if "smtp_password" in payload.model_fields_set:
        hr_integration.smtp_password = encrypted_smtp_password(payload.smtp_password, hr_integration.smtp_password)
    db.commit()
    db.refresh(hr_integration)
    return _to_read(hr_integration)


@router.post("/hr-inbox/settings/send-test-email", response_model=SendTestEmailResult)
def send_test_email(
    payload: SendTestEmailRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
):
    hr_integration = get_hr_integration(db)
    if not is_smtp_configured(hr_integration):
        raise HTTPException(status_code=400, detail="Configure the SMTP host, username, and password first")
    try:
        send_hr_email(
            hr_integration, to=payload.to, subject="HR mailbox test email",
            body="This is a test email confirming the shared HR mailbox's SMTP settings work.",
        )
    except SmtpError as exc:
        return SendTestEmailResult(sent=False, detail=str(exc))
    return SendTestEmailResult(sent=True, detail=f"Test email sent to {payload.to}")


@router.post("/hr-inbox/settings/test-imap-connection", response_model=TestImapConnectionResult)
def test_imap_connection_endpoint(
    db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin")),
):
    hr_integration = get_hr_integration(db)
    if not is_imap_configured(hr_integration):
        raise HTTPException(status_code=400, detail="Configure the IMAP host, username, and password first")
    try:
        test_imap_connection(hr_integration)
    except ImapError as exc:
        return TestImapConnectionResult(connected=False, detail=str(exc))
    return TestImapConnectionResult(connected=True, detail="Connected to the IMAP server and selected INBOX successfully")


# --- HR Inbox List -- same role gating as POST /applications/{id}/message (the closest
# existing "send/see HR-mailbox-related candidate email" feature): recruiter/hiring_manager/
# admin, not admin-only -- only *configuring* the mailbox above is admin-only. ---


@router.get("/hr-inbox/list", response_model=HrInboxListPage)
def list_hr_inbox(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=200),
    search: Optional[str] = Query(None, description="Matches sender address or subject"),
    matched: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin")),
):
    query = filtered_hr_inbox_query(db, search=search, matched=matched)
    total = query.count()
    rows = (
        query.order_by(HrInboundEmail.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [row_to_item(email, candidate_name, job_title) for email, candidate_name, job_title in rows]
    return HrInboxListPage(total=total, page=page, page_size=page_size, items=items)


@router.get("/hr-inbox/export", response_model=list[HrInboundEmailRead])
def export_hr_inbox(
    search: Optional[str] = Query(None),
    matched: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "hiring_manager", "admin")),
):
    query = filtered_hr_inbox_query(db, search=search, matched=matched)
    rows = query.order_by(HrInboundEmail.created_at.desc()).all()
    return [row_to_item(email, candidate_name, job_title) for email, candidate_name, job_title in rows]
