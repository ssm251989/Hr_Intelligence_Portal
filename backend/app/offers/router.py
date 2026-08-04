import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.ai_services.offer_letter_generator import generate_offer_letter
from app.audit.service import log_action
from app.core.database import get_db
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.offer import Offer
from app.models.user import User
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


@router.post("/{application_id}/offer/generate", response_model=OfferRead)
def generate_offer(application_id: uuid.UUID, payload: OfferGenerateRequest, db: Session = Depends(get_db)):
    application = _get_application_or_404(db, application_id)
    if application.status != "bgv_cleared":
        raise HTTPException(
            status_code=400, detail="Application must be bgv_cleared before an offer can be generated"
        )

    salary_value = (
        application.approved_salary
        if application.approved_salary is not None
        else application.expected_salary
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

    result = generate_offer_letter(
        candidate_name=candidate.full_name,
        job_title=job.title if job else "Unknown role",
        approved_salary=str(float(salary_value)),
        start_date=payload.start_date,
        reporting_manager_name=reporting_manager_name,
    )

    log_action(db, "application", application.id, "ai_offer_letter_generated", "system", result)

    offer = db.query(Offer).filter(Offer.application_id == application.id).one_or_none()
    if offer is None:
        offer = Offer(application_id=application.id)
        db.add(offer)
    offer.offer_letter_text = result["offer_letter_text"]

    application.status = "offer_sent"
    db.commit()
    db.refresh(offer)
    return offer


@router.post("/{application_id}/offer/mark-signed", response_model=OfferRead)
def mark_offer_signed(application_id: uuid.UUID, payload: OfferSendRequest, db: Session = Depends(get_db)):
    application = _get_application_or_404(db, application_id)
    offer = _get_offer_or_404(db, application_id)

    # Real DocuSign integration is out of scope for the MVP -- this endpoint
    # just records the signed state manually (HR pastes the envelope ID from
    # whatever channel actually collected the signature, if any).
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
def complete_onboarding(application_id: uuid.UUID, db: Session = Depends(get_db)):
    application = _get_application_or_404(db, application_id)
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
def get_offer(application_id: uuid.UUID, db: Session = Depends(get_db)):
    _get_application_or_404(db, application_id)
    return _get_offer_or_404(db, application_id)
