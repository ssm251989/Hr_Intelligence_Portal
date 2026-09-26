import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned


class User(Base, TenantOwned):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('recruiter','hiring_manager','interviewer','admin','employee','agency')",
            name="users_role_check",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255))
    role = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))

    # Part 5A -- MFA + login-hardening columns. Additive to the existing flat `role` column
    # above (see app/models/iam.py's own module docstring for why the two systems coexist
    # rather than one replacing the other in this part).
    mfa_totp_secret_ref = Column(String(200))  # a platform.secrets ref, never a plaintext TOTP seed
    mfa_totp_enrolled_at = Column(DateTime(timezone=True))
    mfa_email_otp_enabled = Column(Boolean, nullable=False, server_default=text("false"))
    failed_login_attempts = Column(Integer, nullable=False, server_default=text("0"))
    locked_until = Column(DateTime(timezone=True))
    password_changed_at = Column(DateTime(timezone=True), server_default=text("now()"))
