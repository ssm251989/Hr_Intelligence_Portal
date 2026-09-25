from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned


class Offer(Base, TenantOwned):
    __tablename__ = "offers"
    __table_args__ = (
        CheckConstraint(
            "onboarding_status IN ('not_started','in_progress','completed')",
            name="offers_onboarding_status_check",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id"))
    offer_letter_text = Column(Text)
    docusign_envelope_id = Column(String(255))
    # Set only when the envelope above was created for real via the DocuSign API (as
    # opposed to a manually-pasted envelope ID) -- identifies whose stored DocuSign
    # integration to use when checking the envelope's actual signing status.
    docusign_sender_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    signed = Column(Boolean, server_default=text("false"))
    onboarding_status = Column(String(50), server_default=text("'not_started'"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    # Part 8 section 7 -- CTC breakup builder (display-only, see app/recruitment/ctc.py),
    # joining-date confirmation, offer expiry & reminders, counter-offer tracking.
    ctc_breakup_json = Column(JSONB)
    joining_date = Column(Date)
    expiry_date = Column(Date)
    # [{"amount": float, "notes": str, "recorded_at": iso str}], oldest first.
    counter_offer_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
