from types import SimpleNamespace
from typing import Optional

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_roles
from app.core.crypto import decrypt, encrypt
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
    HrMailboxValidateRequest,
    HrMailboxValidateResult,
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


@router.post("/hr-inbox/settings/validate", response_model=HrMailboxValidateResult)
def validate_hr_mailbox_settings(
    payload: HrMailboxValidateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
):
    """Tests a submitted SMTP+IMAP credential set for real -- a test email send and an
    IMAP login -- WITHOUT ever writing it to the hr_integrations row. Used by the Settings
    page's Connect/Edit dialog to validate before it ever calls PUT /hr-inbox/settings, so
    a failed attempt can never overwrite (and thus lose) a previously-working saved
    password -- the exact risk a save-then-verify-then-revert flow couldn't fully avoid.
    """
    password = payload.smtp_password
    if not password:
        existing = get_hr_integration(db)
        if not existing.smtp_password:
            no_password_error = "A password is required (none is currently stored for this mailbox)"
            return HrMailboxValidateResult(
                smtp_ok=False, smtp_error=no_password_error, imap_ok=False, imap_error=no_password_error,
            )
        try:
            password = decrypt(existing.smtp_password)
        except InvalidToken:
            decrypt_error = "Stored SMTP password could not be decrypted"
            return HrMailboxValidateResult(
                smtp_ok=False, smtp_error=decrypt_error, imap_ok=False, imap_error=decrypt_error,
            )

    # A throwaway, never-persisted stand-in for the HrIntegration row -- send_hr_email/
    # test_imap_connection only ever read attributes off it (duck-typed, same pattern as
    # confirmation.create_confirmed_calendar_event elsewhere in this app), so this never
    # touches the database. Re-encrypted only because those functions decrypt whatever
    # they're handed -- never persisted, so the fact that it's encrypted at all here is
    # incidental plumbing, not a security boundary.
    probe = SimpleNamespace(
        smtp_host=payload.smtp_host, smtp_port=payload.smtp_port, use_tls=payload.use_tls,
        smtp_username=payload.smtp_username, smtp_password=encrypt(password),
        from_address=payload.from_address, hr_module_email=payload.hr_module_email,
        imap_host=payload.imap_host, imap_port=payload.imap_port, use_ssl=payload.use_ssl,
    )

    smtp_ok, smtp_error = True, None
    try:
        send_hr_email(
            probe, to=(payload.from_address or payload.smtp_username), subject="HR mailbox validation",
            body="This is a validation email confirming the shared HR mailbox's SMTP settings work.",
        )
    except SmtpError as exc:
        smtp_ok, smtp_error = False, str(exc)

    imap_ok, imap_error = True, None
    try:
        test_imap_connection(probe)
    except ImapError as exc:
        imap_ok, imap_error = False, str(exc)

    return HrMailboxValidateResult(smtp_ok=smtp_ok, smtp_error=smtp_error, imap_ok=imap_ok, imap_error=imap_error)


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
