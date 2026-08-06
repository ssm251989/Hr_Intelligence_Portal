import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.ai_services.document_validator import DocumentValidationError, validate_document
from app.audit.service import log_action
from app.auth.dependencies import get_current_user, require_roles
from app.bgv.document_extraction import extract_bgv_text
from app.bgv.storage import resolve_bgv_path, save_bgv_file
from app.candidates.resume_extraction import ResumeExtractionError, UnsupportedFileTypeError
from app.core.database import get_db
from app.models.application import Application
from app.models.bgv_document import BgvDocument
from app.models.user import User
from app.schemas.application import ApplicationRead
from app.schemas.bgv import BGV_DOC_TYPES, BgvClearRequest, BgvDocumentRead

router = APIRouter(prefix="/applications", tags=["bgv"])

ALLOWED_EXTENSIONS = {"pdf", "docx", "jpg", "jpeg", "png"}
BGV_IN_PROGRESS_STATUSES = {"bgv_requested", "bgv_pending"}


def _get_application_or_404(db: Session, application_id: uuid.UUID) -> Application:
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


def _get_document_or_404(db: Session, application_id: uuid.UUID, doc_id: uuid.UUID) -> BgvDocument:
    document = db.get(BgvDocument, doc_id)
    if not document or document.application_id != application_id:
        raise HTTPException(status_code=404, detail="BGV document not found")
    return document


@router.post("/{application_id}/bgv/request", response_model=ApplicationRead)
def request_bgv(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "admin")),
):
    application = _get_application_or_404(db, application_id)
    if application.status != "salary_approved":
        raise HTTPException(
            status_code=400,
            detail="Application must have an approved salary before BGV can be requested",
        )

    previous_status = application.status
    application.status = "bgv_requested"
    db.commit()
    db.refresh(application)

    log_action(
        db,
        "application",
        application.id,
        "bgv_requested",
        "system",
        {"previous_status": previous_status, "new_status": "bgv_requested"},
    )
    return application


@router.post("/{application_id}/bgv/documents", response_model=BgvDocumentRead, status_code=201)
async def upload_bgv_document(
    application_id: uuid.UUID,
    doc_type: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "admin")),
):
    if doc_type not in BGV_DOC_TYPES:
        raise HTTPException(status_code=400, detail=f"doc_type must be one of {sorted(BGV_DOC_TYPES)}")

    application = _get_application_or_404(db, application_id)
    if application.status not in BGV_IN_PROGRESS_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="Application must be in bgv_requested or bgv_pending status to upload BGV documents",
        )

    extension = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported file type for BGV document")

    file_bytes = await file.read()
    try:
        extract_bgv_text(file_bytes, file.filename)
    except (UnsupportedFileTypeError, ResumeExtractionError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not read document: {exc}") from exc

    is_first_document = (
        db.query(BgvDocument).filter(BgvDocument.application_id == application.id).count() == 0
    )

    file_path = save_bgv_file(file_bytes, extension)
    document = BgvDocument(application_id=application.id, doc_type=doc_type, file_path=file_path)
    db.add(document)

    if is_first_document and application.status == "bgv_requested":
        application.status = "bgv_pending"

    db.commit()
    db.refresh(document)

    log_action(
        db,
        "bgv_document",
        document.id,
        "bgv_document_uploaded",
        "system",
        {"application_id": str(application.id), "doc_type": doc_type, "file_path": file_path},
    )
    return document


@router.get("/{application_id}/bgv/documents", response_model=list[BgvDocumentRead])
def list_bgv_documents(
    application_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    _get_application_or_404(db, application_id)
    return (
        db.query(BgvDocument)
        .filter(BgvDocument.application_id == application_id)
        .order_by(BgvDocument.created_at)
        .all()
    )


@router.post("/{application_id}/bgv/documents/{doc_id}/validate", response_model=BgvDocumentRead)
def validate_bgv_document(
    application_id: uuid.UUID,
    doc_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "admin")),
):
    _get_application_or_404(db, application_id)
    document = _get_document_or_404(db, application_id, doc_id)

    file_path = resolve_bgv_path(document.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="BGV document file missing on disk")

    try:
        ocr_text = extract_bgv_text(file_path.read_bytes(), file_path.name)
    except (UnsupportedFileTypeError, ResumeExtractionError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not read document: {exc}") from exc

    try:
        result = validate_document(document.doc_type, ocr_text)
    except DocumentValidationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    log_action(db, "bgv_document", document.id, "ai_document_validator_scored", "system", result)
    # Pass validation_status through as-is -- 'needs_review' must never be
    # collapsed to 'invalid' here; a human makes that call at /bgv/clear.
    document.validation_status = result["validation_status"]
    document.validator_output = result
    db.commit()
    db.refresh(document)
    return document


@router.post("/{application_id}/bgv/clear", response_model=ApplicationRead)
def clear_bgv(
    application_id: uuid.UUID,
    payload: BgvClearRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "admin")),
):
    application = _get_application_or_404(db, application_id)
    if application.status not in BGV_IN_PROGRESS_STATUSES:
        raise HTTPException(status_code=400, detail="Application is not awaiting a BGV clearance decision")

    previous_status = application.status

    if payload.decision == "clear":
        documents = db.query(BgvDocument).filter(BgvDocument.application_id == application.id).all()
        if not documents:
            raise HTTPException(
                status_code=400, detail="No BGV documents have been uploaded for this application"
            )
        not_valid = [doc for doc in documents if doc.validation_status != "valid"]
        if not_valid:
            detail = "Cannot clear BGV — the following documents are not yet valid: " + ", ".join(
                f"{doc.doc_type} ({doc.validation_status})" for doc in not_valid
            )
            raise HTTPException(status_code=400, detail=detail)
        new_status = "bgv_cleared"
    else:
        new_status = "bgv_rejected"

    application.status = new_status
    db.commit()
    db.refresh(application)

    log_action(
        db,
        "application",
        application.id,
        "bgv_clearance_decision",
        payload.cleared_by or current_user.email,
        {
            "decision": payload.decision,
            "notes": payload.notes,
            "previous_status": previous_status,
            "new_status": new_status,
        },
    )
    return application
