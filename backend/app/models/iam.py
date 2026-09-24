"""IAM tables (docs/HRMS_COMPLETE_SPEC.txt Part 5A) -- roles/scopes/field-security/
delegation, plus the session/MFA/token machinery authentication needs. Sits ALONGSIDE the
existing `users.role` flat string + `require_roles()` (app/auth/dependencies.py), not in
place of it -- see docs/build_log.md's own Part 5 note for why a blanket rewrite of every
existing router's access control is out of scope for this part, and how the two systems
are bridged (each of the 4 existing flat roles gets a matching seeded `roles` row, so
`authz.require()` resolves real permissions for real, already-existing users immediately).
"""

import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned

SCOPE_TYPES = (
    "all", "legal_entity", "business_unit", "location", "department", "cost_center",
    "reportees_direct", "reportees_all", "self", "custom",
)
FIELD_ACCESS_LEVELS = ("hidden", "masked", "read", "write")


class Role(Base, TenantOwned):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="roles_tenant_name_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    description = Column(Text)
    is_system = Column(Boolean, nullable=False, server_default=text("false"))
    permissions = Column(ARRAY(String), nullable=False, server_default=text("'{}'"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class RoleAssignment(Base, TenantOwned):
    __tablename__ = "role_assignments"
    __table_args__ = (
        CheckConstraint("scope_type IN (" + ",".join(f"'{s}'" for s in SCOPE_TYPES) + ")", name="role_assignments_scope_type_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False)
    scope_type = Column(String(20), nullable=False, server_default=text("'all'"))
    scope_ids = Column(ARRAY(UUID(as_uuid=True)), server_default=text("'{}'"))
    condition_jsonlogic = Column(JSONB)
    valid_from = Column(DateTime(timezone=True))
    valid_to = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class FieldSecurity(Base, TenantOwned):
    __tablename__ = "field_security"
    __table_args__ = (
        UniqueConstraint("tenant_id", "entity", "field", "role_id", name="field_security_entity_field_role_uq"),
        CheckConstraint("access IN (" + ",".join(f"'{a}'" for a in FIELD_ACCESS_LEVELS) + ")", name="field_security_access_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity = Column(String(100), nullable=False)
    field = Column(String(100), nullable=False)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False)
    access = Column(String(20), nullable=False)


class UserDelegation(Base, TenantOwned):
    __tablename__ = "user_delegations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    to_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    permissions = Column(ARRAY(String))  # NULL means "all" of from_user's permissions
    starts_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class RefreshToken(Base, TenantOwned):
    """Rotating refresh tokens (section 1's own "JWT access (short) + rotating refresh").
    Only the SHA-256 hash of the token is stored -- same principle as a password hash, so a
    DB read alone can never mint a session."""

    __tablename__ = "refresh_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    device_id = Column(UUID(as_uuid=True), ForeignKey("user_devices.id"))
    token_hash = Column(Text, nullable=False, unique=True)
    replaced_by_id = Column(UUID(as_uuid=True))
    revoked_at = Column(DateTime(timezone=True))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class UserDevice(Base, TenantOwned):
    """A "remember this device" record (section 1) -- also doubles as the session list's
    own device row (`GET /auth/sessions` lists these, not raw refresh tokens)."""

    __tablename__ = "user_devices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    label = Column(Text)
    user_agent = Column(Text)
    ip_address = Column(Text)
    mfa_remembered_until = Column(DateTime(timezone=True))
    last_seen_at = Column(DateTime(timezone=True))
    revoked_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class MfaRecoveryCode(Base, TenantOwned):
    __tablename__ = "mfa_recovery_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    code_hash = Column(Text, nullable=False)
    used_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class MfaChallenge(Base, TenantOwned):
    """The server-side half of a login's MFA step: after password verification succeeds,
    `login()` mints a short-lived JWT ("mfa_challenge" purpose claim, carries this row's
    id) AND, for the email-OTP factor specifically, one of these rows holding the hashed
    6-digit code that JWT alone can't carry (a code embedded in the token itself would be
    readable by anyone who saw the token in transit before the user ever typed it in).
    TOTP has no matching row -- it's verified directly against the enrolled secret, no
    server-generated code to persist."""

    __tablename__ = "mfa_challenges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    method = Column(String(20), nullable=False)  # "totp" | "email_otp"
    code_hash = Column(Text)  # only set for method="email_otp"
    attempts = Column(Integer, nullable=False, server_default=text("0"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True))


class PasswordHistory(Base, TenantOwned):
    __tablename__ = "password_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    hashed_password = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class MagicLink(Base, TenantOwned):
    """Candidate/pre-hire portal login (section 1's own "magic links (+ email OTP), not
    2FA apps"). `candidate_id` is the only identity a magic link ever carries -- there is
    no separate candidate password to manage."""

    __tablename__ = "magic_links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id = Column(UUID(as_uuid=True), nullable=False)
    email = Column(Text, nullable=False)
    token = Column(Text, nullable=False, unique=True)
    otp_code_hash = Column(Text)  # set when this link's email also carried a 6-digit OTP fallback
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True))


class ActionToken(Base, TenantOwned):
    """The generic form of interview_scheduling/negotiation_token.py's own token pattern
    (section 5B.3 explicitly says to reuse it) -- one-time-use, signed-by-existence (the
    token string itself is the credential, `secrets.token_urlsafe`), always TenantOwned so
    RLS scopes it the same as every other row. `entity_type`/`entity_id` name what this
    token acts on (most often a `workflow_steps` row); `action` is a free-form verb
    ("approve"/"reject"/"confirm"/...) a caller defines, not a fixed enum -- unlike
    NegotiationToken's `role` column, which only ever needed two values."""

    __tablename__ = "action_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)
    action = Column(String(50), nullable=False)
    token = Column(Text, nullable=False, unique=True)
    payload_json = Column(JSONB)
    created_by = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    responded_at = Column(DateTime(timezone=True))
    invalidated_at = Column(DateTime(timezone=True))
