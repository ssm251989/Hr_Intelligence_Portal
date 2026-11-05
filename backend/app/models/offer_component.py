"""CTC breakup builder (docs/HRMS_COMPLETE_SPEC.txt Part 8 section 7) -- a tenant-defined
catalog of compensation components (basic, HRA, PF, variable pay, ...). Display-only, NOT
payroll (spec's own wording) -- `app/recruitment/ctc.py` computes a breakdown for one
Offer from this catalog against a base CTC number; nothing here feeds an actual payroll
run."""

import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, Numeric, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned

OFFER_COMPONENT_TYPES = ("fixed", "percentage_of_base")


class OfferComponent(Base, TenantOwned):
    __tablename__ = "offer_components"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="offer_components_tenant_code_uq"),
        CheckConstraint("type IN (" + ",".join(f"'{t}'" for t in OFFER_COMPONENT_TYPES) + ")", name="offer_components_type_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    type = Column(Text, nullable=False, server_default=text("'percentage_of_base'"))
    # "fixed": `value` is an absolute annual amount. "percentage_of_base": `value` is a
    # fraction (0.4 = 40%) of the offer's base CTC component.
    value = Column(Numeric, nullable=False)
    order = Column(Numeric, nullable=False, server_default=text("0"))
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
