import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, String, text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned


class User(Base, TenantOwned):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('recruiter','hiring_manager','interviewer','admin')",
            name="users_role_check",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255))
    role = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
