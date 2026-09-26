import uuid

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.ai_services.offer_letter_generator import OfferLetterGenerationError, generate_offer_letter
from app.audit.service import log_action
from app.auth.dependencies import get_current_user, require_roles
from app.candidates.hold import assert_application_not_on_hold
from app.core.crypto import decrypt
from app.core.database import get_db
from app.integrations.docusign import DocuSignError, create_envelope, get_envelope_status
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.offer import Offer
from app.models.user import User
from app.models.user_integration import UserIntegration
from app.schemas.offer import OfferGenerateRequest, OfferRead, OfferSendRequest

router = APIRouter(prefix="/applications", tags=["offers"])


def _get_application_or_404(db: Session, application_id: uuid.UUID) -> Application:
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


def _get_offer_or_404(db: Session, application_id: uuid.UUID) -> Offer:
    offer = db.query(Offer).filter(Offer.application_id == application_id).one_or_none()
    if not offer:
        raise HTTPException(status_code=404, detail="No offer found for this application")
    return offer


def _get_docusign_integration(db: Session, user_id: uuid.UUID) -> UserIntegration | None:
    return (
        db.query(UserIntegration)
        .filter(UserIntegration.user_id == user_id, UserIntegration.provider == "docusign")
        .first()
    )


def _try_create_docusign_envelope(
    db: Session, offer: Offer, candidate: Candidate, sender: User
) -> str | None:
    """Create a real DocuSign envelope if the generating user has connected DocuSign.

    Returns None (never raises) when there's no connection, no candidate email, or the
    DocuSign API call fails, so a DocuSign outage can't block offer generation -- callers
    fall back to the existing manual "mark signed" flow.
    """
    integration = _get_docusign_integration(db, sender.id)
    if not integration or not candidate.email:
        return None

    try:
        return create_envelope(
            decrypt(integration.refresh_token),
            document_text=offer.offer_letter_text,
            document_name=f"Offer Letter - {candidate.full_name}",
            signer_email=candidate.email,
            signer_name=candidate.full_name,
        )
    except (DocuSignError, InvalidToken) as exc:
        error = str(exc) or "Stored DocuSign refresh token could not be decrypted"
        log_action(
            db,
            "application",
            offer.application_id,
            "docusign_envelope_creation_failed",
            "system",
            {"sender_id": str(sender.id), "error": error},
        )
        return None


@router.post("/{application_id}/offer/generate", response_model=OfferRead)
def generate_offer(
    application_id: uuid.UUID,
    payload: OfferGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "admin")),
):
    application = _get_application_or_404(db, application_id)
    assert_application_not_on_hold(application)
    if application.status != "bgv_cleared":
        raise HTTPException(
            status_code=400, detail="Application must be bgv_cleared before an offer can be generated"
        )

    # Part 17.8: approved figure, else the suggested offer inside the band, else what they expect
    salary_value = (
        application.approved_salary
        if application.approved_salary is not None
        else (application.salary_check or {}).get("suggestion") or application.expected_salary
    )
    if salary_value is None:
        raise HTTPException(status_code=400, detail="Application has no approved or expected salary set")

    job = db.get(JobRole, application.job_role_id)
    candidate = db.get(Candidate, application.candidate_id)
    if not candidate or not candidate.full_name:
        raise HTTPException(status_code=400, detail="Candidate full name is not set")

    reporting_manager_name = payload.reporting_manager_name
    if not reporting_manager_name and job and job.hiring_manager_id:
        hiring_manager = db.get(User, job.hiring_manager_id)
        if hiring_manager:
            reporting_manager_name = hiring_manager.full_name or hiring_manager.email
    reporting_manager_name = reporting_manager_name or "Not specified"

    try:
        result = generate_offer_letter(
            candidate_name=candidate.full_name,
            job_title=job.title if job else "Unknown role",
            approved_salary=str(float(salary_value)),
            start_date=payload.start_date,
            reporting_manager_name=reporting_manager_name,
        )
    except OfferLetterGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    log_action(db, "application", application.id, "ai_offer_letter_generated", "system", result)

    offer = db.query(Offer).filter(Offer.application_id == application.id).one_or_none()
    if offer is None:
        offer = Offer(application_id=application.id)
        db.add(offer)
    offer.offer_letter_text = result["offer_letter_text"]

    envelope_id = _try_create_docusign_envelope(db, offer, candidate, current_user)
    if envelope_id:
        offer.docusign_envelope_id = envelope_id
        offer.docusign_sender_id = current_user.id

    application.status = "offer_sent"
    db.commit()
    db.refresh(offer)
    return offer


@router.post("/{application_id}/offer/mark-signed", response_model=OfferRead)
def mark_offer_signed(
    application_id: uuid.UUID,
    payload: OfferSendRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "admin")),
):
    application = _get_application_or_404(db, application_id)
    assert_application_not_on_hold(application)
    offer = _get_offer_or_404(db, application_id)

    if offer.docusign_sender_id is not None:
        # A real envelope was created via the DocuSign API -- verify its actual signing
        # status instead of accepting a manual signed=true claim.
        integration = _get_docusign_integration(db, offer.docusign_sender_id)
        if not integration:
            raise HTTPException(
                status_code=409,
                detail="DocuSign is no longer connected for this offer's sender; cannot verify signing status",
            )
        try:
            envelope_status = get_envelope_status(decrypt(integration.refresh_token), offer.docusign_envelope_id)
        except (DocuSignError, InvalidToken) as exc:
            detail = str(exc) or "Stored DocuSign refresh token could not be decrypted"
            raise HTTPException(status_code=502, detail=detail) from exc

        if envelope_status != "completed":
            raise HTTPException(
                status_code=409,
                detail=f"DocuSign envelope is not yet signed (status: {envelope_status})",
            )

        offer.signed = True
        offer.onboarding_status = "in_progress"
        previous_status = application.status
        application.status = "onboarding_started"
        db.commit()
        db.refresh(offer)

        log_action(
            db,
            "application",
            application.id,
            "offer_signed",
            "system",
            {
                "docusign_envelope_id": offer.docusign_envelope_id,
                "docusign_status": envelope_status,
                "previous_status": previous_status,
                "new_status": "onboarding_started",
            },
        )
        return offer

    # Manual fallback path (no real DocuSign envelope) -- HR pastes the envelope ID from
    # whatever channel actually collected the signature, if any.
    if payload.docusign_envelope_id is not None:
        offer.docusign_envelope_id = payload.docusign_envelope_id
    offer.signed = True
    offer.onboarding_status = "in_progress"

    previous_status = application.status
    application.status = "onboarding_started"

    db.commit()
    db.refresh(offer)

    log_action(
        db,
        "application",
        application.id,
        "offer_signed",
        "system",
        {
            "docusign_envelope_id": payload.docusign_envelope_id,
            "previous_status": previous_status,
            "new_status": "onboarding_started",
        },
    )
    return offer


@router.post("/{application_id}/offer/complete-onboarding", response_model=OfferRead)
def complete_onboarding(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("recruiter", "admin")),
):
    application = _get_application_or_404(db, application_id)
    assert_application_not_on_hold(application)
    if application.status != "onboarding_started":
        raise HTTPException(
            status_code=400, detail="Application must be onboarding_started before onboarding can complete"
        )

    offer = _get_offer_or_404(db, application_id)

    previous_status = application.status
    offer.onboarding_status = "completed"
    application.status = "onboarding_completed"
    db.commit()
    db.refresh(offer)

    log_action(
        db,
        "application",
        application.id,
        "onboarding_completed",
        "system",
        {"previous_status": previous_status, "new_status": "onboarding_completed"},
    )
    return offer


@router.get("/{application_id}/offer", response_model=OfferRead)
def get_offer(
    application_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    _get_application_or_404(db, application_id)
    return _get_offer_or_404(db, application_id)
