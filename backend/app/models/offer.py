from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, text
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
    # fix 2026-10-04: sign in the app when DocuSign isn't connected (app/offers/esign.py)
    sign_token = Column(Text, unique=True)  # the candidate's "Review & sign" link
    sent_at = Column(DateTime(timezone=True))
    viewed_at = Column(DateTime(timezone=True))
    signed_at = Column(DateTime(timezone=True))
    signed_name = Column(Text)  # the full name typed to sign
    signed_ip = Column(String(64))
    signed_user_agent = Column(Text)
    signed_pdf_path = Column(Text)  # the letter stamped with the signature
    sign_method = Column(String(20))  # in_app | docusign | manual
    # fix 2026-10-05: resend + revised offers (app/offers/revisions.py). This row is always the LATEST version;
    # earlier ones are frozen in offer_versions.
    version_no = Column(Integer, nullable=False, server_default=text("1"))
    designation = Column(Text)  # else the job title
    work_location = Column(Text)  # else the job's location
    terms = Column(Text)  # extra terms HR adds to the letter
    resend_count = Column(Integer, nullable=False, server_default=text("0"))
    last_resent_at = Column(DateTime(timezone=True))
    declined_at = Column(DateTime(timezone=True))


class OfferVersion(Base, TenantOwned):
    """One version of an offer (fix 2026-10-05). The current version's row holds who sent it, why and what
    changed; its live state (viewed / signed) is on `offers`. When a newer version replaces it, its state is
    copied here and it is marked "replaced"; its old sign link then says "replaced by a newer version".
    status: current | pending_approval | replaced | rejected"""

    __tablename__ = "offer_versions"
    __table_args__ = (UniqueConstraint("offer_id", "version_no", name="offer_versions_no_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    offer_id = Column(UUID(as_uuid=True), ForeignKey("offers.id", ondelete="CASCADE"), nullable=False, index=True)
    version_no = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, server_default=text("'current'"))
    letter_html = Column(Text)
    ctc_total = Column(Numeric)
    ctc_breakup_json = Column(JSONB)
    joining_date = Column(Date)
    designation = Column(Text)
    work_location = Column(Text)
    terms = Column(Text)
    expiry_date = Column(Date)
    reason_code = Column(String(30))  # salary | joining_date | designation | other (null for v1)
    reason_note = Column(Text)
    changes_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))  # [{"field", "label", "old", "new"}]
    approval_json = Column(JSONB)  # {"needed": [...reasons], "approved_by", "approved_at"} when above the limit
    sent_by = Column(String(200))
    sent_at = Column(DateTime(timezone=True))
    resend_count = Column(Integer, nullable=False, server_default=text("0"))
    # frozen from `offers` when replaced
    sign_token = Column(Text, unique=True)
    viewed_at = Column(DateTime(timezone=True))
    signed_at = Column(DateTime(timezone=True))
    signed_name = Column(Text)
    signed_ip = Column(String(64))
    sign_method = Column(String(20))
    signed_pdf_path = Column(Text)
    docusign_envelope_id = Column(String(255))
    replaced_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
