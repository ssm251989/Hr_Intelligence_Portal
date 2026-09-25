"""Control-plane tables (docs/HRMS_COMPLETE_SPEC.txt Part 2 section 1) -- live in the
CONTROL_PLANE_DATABASE_URL database, never in a tenant's own database.
"""

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.platform.tenancy.database_cp import ControlPlaneBase

TENANT_STATUSES = ("provisioning", "active", "suspended", "archived", "deleted")
TENANT_ISOLATIONS = ("dedicated_db", "shared_rls")
TLS_STATUSES = ("pending", "issued", "failed")
PROVISIONING_JOB_STATUSES = ("pending", "running", "succeeded", "failed")


class Tenant(ControlPlaneBase):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("status IN (" + ",".join(f"'{s}'" for s in TENANT_STATUSES) + ")", name="tenants_status_check"),
        CheckConstraint(
            "isolation IN (" + ",".join(f"'{i}'" for i in TENANT_ISOLATIONS) + ")", name="tenants_isolation_check"
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    slug = Column(String(63), nullable=False, unique=True)
    display_name = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, server_default=text("'provisioning'"))
    isolation = Column(String(20), nullable=False, server_default=text("'dedicated_db'"))
    # A SecretStore ref (never a plaintext DSN) -- resolved via platform.secrets.store to
    # get the tenant's own tenant-data database connection string. NULL only while a tenant
    # is still mid-provisioning (status='provisioning') and its database doesn't exist yet.
    db_dsn_secret_ref = Column(Text)
    region = Column(String(50))
    data_residency = Column(String(50))
    plan_id = Column(UUID(as_uuid=True), ForeignKey("plans.id"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    suspended_reason = Column(Text)


class TenantDomain(ControlPlaneBase):
    __tablename__ = "tenant_domains"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    host = Column(String(255), nullable=False, unique=True)
    is_primary = Column(Boolean, nullable=False, server_default=text("false"))
    verified_at = Column(DateTime(timezone=True))
    tls_status = Column(String(20), server_default=text("'pending'"))

    __table_args__ = (
        CheckConstraint("tls_status IN (" + ",".join(f"'{s}'" for s in TLS_STATUSES) + ")", name="tenant_domains_tls_status_check"),
    )


class Plan(ControlPlaneBase):
    __tablename__ = "plans"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    code = Column(String(50), nullable=False, unique=True)
    name = Column(Text, nullable=False)
    module_codes = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    limits_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))


class TenantModule(ControlPlaneBase):
    __tablename__ = "tenant_modules"
    __table_args__ = (UniqueConstraint("tenant_id", "module_code", name="tenant_modules_tenant_module_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    module_code = Column(String(50), nullable=False)
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    limits_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))


class FeatureFlag(ControlPlaneBase):
    __tablename__ = "feature_flags"

    key = Column(String(100), primary_key=True)
    description = Column(Text)
    default_bool = Column(Boolean, nullable=False, server_default=text("false"))


class TenantFeatureFlag(ControlPlaneBase):
    __tablename__ = "tenant_feature_flags"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="tenant_feature_flags_tenant_key_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    key = Column(String(100), ForeignKey("feature_flags.key"), nullable=False)
    value_bool = Column(Boolean, nullable=False)


class PlatformAdmin(ControlPlaneBase):
    """Super-admin console users (Part 13) -- entirely separate from any tenant's own
    `users` table; a platform admin is never a member of a tenant."""

    __tablename__ = "platform_admins"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    email = Column(String(255), nullable=False, unique=True)
    mfa_secret_ref = Column(Text)
    # Part 13: the console's own credentials -- bcrypt hash + mandatory TOTP (the secret
    # itself lives in the control-plane SecretStore behind mfa_secret_ref).
    password_hash = Column(String(255))
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    last_login_at = Column(DateTime(timezone=True))


class TenantProvisioningJob(ControlPlaneBase):
    __tablename__ = "tenant_provisioning_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ",".join(f"'{s}'" for s in PROVISIONING_JOB_STATUSES) + ")",
            name="tenant_provisioning_jobs_status_check",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    step = Column(String(100), nullable=False)
    status = Column(String(20), nullable=False, server_default=text("'pending'"))
    log = Column(Text)


class ControlPlaneSecretScope(ControlPlaneBase):
    """See platform/secrets/store.py's own module docstring -- one row per encryption
    scope (today: a single "control_plane" scope for tenant-DSN bootstrapping secrets)."""

    __tablename__ = "secret_scopes"

    scope = Column(String(100), primary_key=True)
    wrapped_dek = Column(Text, nullable=False)


class ControlPlaneSecret(ControlPlaneBase):
    """Control-plane-level secrets only -- today, exactly one kind: each tenant's own
    dedicated-database DSN (`tenants.db_dsn_secret_ref` points at a row here by `ref`).
    Tenant-scoped secrets (Part 3 connection credentials) live in the TENANT's own database
    instead, in an identically-shaped table -- never here."""

    __tablename__ = "secrets"
    __table_args__ = (UniqueConstraint("scope", "ref", name="secrets_scope_ref_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    scope = Column(String(100), ForeignKey("secret_scopes.scope"), nullable=False)
    ref = Column(Text, nullable=False)
    backend = Column(String(20), nullable=False, server_default=text("'db_encrypted'"))
    ciphertext = Column(Text, nullable=False)
    key_version = Column(Integer, nullable=False, server_default=text("1"))
    created_by = Column(Text)
    rotated_at = Column(DateTime(timezone=True))


class ImpersonationSession(ControlPlaneBase):
    """Audited, time-boxed support access to a tenant (Part 13 section B). The same event
    is also written to the TENANT's own audit_log so the tenant can see it happened."""

    __tablename__ = "impersonation_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    platform_admin_id = Column(UUID(as_uuid=True), ForeignKey("platform_admins.id"), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    target_user_id = Column(UUID(as_uuid=True), nullable=False)  # a user in the tenant's own DB
    reason = Column(Text, nullable=False)
    started_at = Column(DateTime(timezone=True), server_default=text("now()"))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True))


class SuperAdminAudit(ControlPlaneBase):
    __tablename__ = "superadmin_audit"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    admin_email = Column(String(255), nullable=False)
    action = Column(String(100), nullable=False)
    tenant_id = Column(UUID(as_uuid=True))
    details_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
