"""Core HR tables (docs/HRMS_COMPLETE_SPEC.txt Part 7) -- the organisation model,
employee master, effective-dated employment history, documents/letters, and the import
toolkit. All `TenantOwned` + RLS, same as every other business-data table in this build.

**Effective-dating scope decision** (see docs/build_log.md's own Part 7 note): only
`employment_records` is effective-dated (`effective_from`/`effective_to`) -- the ONE table
the spec's own TESTS section explicitly names ("effective-dating queries (as-of date)").
`legal_entities`/`business_units`/`departments`/`locations`/`cost_centers`/`positions` stay
simpler always-current master data; a real historical-org-chart feature (effective-dated
departments/positions too) is real future work, not attempted here.

**Encrypted PII**: `employees`' identity-document and bank-account columns are
`*_secret_ref` strings, never plaintext -- routed through `platform.secrets`' own envelope
encryption (`SecretStore`), the exact same mechanism Part 3's Connection passwords and
Part 5's TOTP secrets already use, not a new one invented for this part.
"""

import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned

EMPLOYEE_STATUSES = ("pre_hire", "active", "on_notice", "inactive", "terminated", "rehire_eligible", "exited", "absconded")  # part 20: exited / absconded
WORKER_TYPES = ("employee", "contractor", "intern", "consultant", "gig")
WORK_MODES = ("onsite", "hybrid", "remote")
POSITION_STATUSES = ("vacant", "filled", "frozen")
DOCUMENT_VISIBILITY = ("employee", "hr", "manager")
IMPORT_ENTITY_TYPES = ("employee",)
IMPORT_BATCH_STATUSES = ("preview", "dry_run", "committed", "rolled_back")
IMPORT_ROW_STATUSES = ("valid", "invalid", "committed")
LIFECYCLE_EVENT_TYPES = (
    "hire", "probation_extension", "confirmation", "transfer", "promotion", "demotion", "redesignation",
    "manager_change", "compensation_change", "secondment", "sabbatical", "suspension", "resignation",
    "termination", "retirement", "death", "rehire", "contract_renewal",
)


# ---- organisation model ----


class LegalEntity(Base, TenantOwned):
    __tablename__ = "legal_entities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    registration_ids_json = Column(JSONB, server_default=text("'{}'::jsonb"))
    address = Column(Text)
    logo_file_id = Column(UUID(as_uuid=True))
    currency = Column(String(3), server_default=text("'INR'"))
    fiscal_year_start = Column(String(5), server_default=text("'04-01'"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class BusinessUnit(Base, TenantOwned):
    __tablename__ = "business_units"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    legal_entity_id = Column(UUID(as_uuid=True), ForeignKey("legal_entities.id"))
    parent_id = Column(UUID(as_uuid=True), ForeignKey("business_units.id"))


class Department(Base, TenantOwned):
    __tablename__ = "departments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    business_unit_id = Column(UUID(as_uuid=True), ForeignKey("business_units.id"))
    parent_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"))  # tree -- also how sub_departments are represented, not a second table


class Location(Base, TenantOwned):
    __tablename__ = "locations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    legal_entity_id = Column(UUID(as_uuid=True), ForeignKey("legal_entities.id"))
    name = Column(Text, nullable=False)
    address = Column(Text)
    geo_lat = Column(String(20))
    geo_lng = Column(String(20))
    timezone = Column(String(50), server_default=text("'Asia/Kolkata'"))
    state = Column(String(100))
    work_week_json = Column(JSONB, server_default=text("'{}'::jsonb"))
    # Working days + holidays used ONLY for SLA timers (section 1's own explicit
    # carve-out) -- never a leave/attendance system of record.
    business_calendar_json = Column(JSONB, server_default=text("'{}'::jsonb"))


class CostCenter(Base, TenantOwned):
    __tablename__ = "cost_centers"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="cost_centers_tenant_code_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(50), nullable=False)
    name = Column(Text, nullable=False)


class Position(Base, TenantOwned):
    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="positions_tenant_code_uq"),
        CheckConstraint("status IN (" + ",".join(f"'{s}'" for s in POSITION_STATUSES) + ")", name="positions_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(50), nullable=False)
    title = Column(Text, nullable=False)  # a designation master's code or free text
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"))
    location_id = Column(UUID(as_uuid=True), ForeignKey("locations.id"))
    grade = Column(String(50))
    reports_to_position_id = Column(UUID(as_uuid=True), ForeignKey("positions.id"))
    headcount_budget = Column(Integer, server_default=text("1"))
    status = Column(String(20), nullable=False, server_default=text("'vacant'"))
    is_critical = Column(Boolean, nullable=False, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


# ---- employee master ----


class Employee(Base, TenantOwned):
    __tablename__ = "employees"
    __table_args__ = (
        UniqueConstraint("tenant_id", "employee_code", name="employees_tenant_code_uq"),
        CheckConstraint("status IN (" + ",".join(f"'{s}'" for s in EMPLOYEE_STATUSES) + ")", name="employees_status_check"),
        CheckConstraint("worker_type IN (" + ",".join(f"'{w}'" for w in WORKER_TYPES) + ")", name="employees_worker_type_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_code = Column(String(50), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))  # NULL for a pre_hire not yet given login access
    status = Column(String(20), nullable=False, server_default=text("'pre_hire'"))
    worker_type = Column(String(20), nullable=False, server_default=text("'employee'"))

    first_name = Column(Text, nullable=False)
    last_name = Column(Text)
    preferred_name = Column(Text)
    pronouns = Column(String(50))
    dob = Column(Date)
    gender = Column(String(30))
    marital_status = Column(String(30))
    nationality = Column(String(100))
    blood_group = Column(String(10))

    personal_email = Column(Text)
    personal_phone = Column(String(50))
    addresses_json = Column(JSONB, server_default=text("'[]'::jsonb"))
    emergency_contacts_json = Column(JSONB, server_default=text("'[]'::jsonb"))
    family_json = Column(JSONB, server_default=text("'[]'::jsonb"))
    education_json = Column(JSONB, server_default=text("'[]'::jsonb"))
    prior_employment_json = Column(JSONB, server_default=text("'[]'::jsonb"))
    skills_json = Column(JSONB, server_default=text("'[]'::jsonb"))  # [{"skill":..,"proficiency":..,"source":"self"|"manager"|"ai"}]
    certifications_json = Column(JSONB, server_default=text("'[]'::jsonb"))
    languages_json = Column(JSONB, server_default=text("'[]'::jsonb"))

    # Encrypted (platform.secrets, see this module's own docstring) -- never plaintext.
    pan_secret_ref = Column(Text)
    aadhaar_secret_ref = Column(Text)
    aadhaar_last4 = Column(String(4))  # the ONE piece of the Aadhaar number ever stored unencrypted -- masking display needs it, section 2's own "masked last 4"
    passport_secret_ref = Column(Text)
    visa_secret_ref = Column(Text)
    driving_licence_secret_ref = Column(Text)
    bank_account_secret_ref = Column(Text)
    bank_verification_status = Column(String(20), server_default=text("'unverified'"))

    custom_fields = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    # Part 20.1 Employees list
    company_email = Column(Text)
    company_email_provider = Column(String(20))  # test | google | microsoft | manual
    joined_on = Column(Date)
    previous_experience_months = Column(Integer)
    rehire_eligible = Column(Boolean)
    exited_on = Column(Date)
    candidate_id = Column(UUID(as_uuid=True))


class EmploymentRecord(Base, TenantOwned):
    """Effective-dated (see this module's own docstring for why this is the ONE
    effective-dated table) -- every job-info change is a NEW row here, never an
    in-place edit of a previous one (section 2's own "no silent edits of job info")."""

    __tablename__ = "employment_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)  # NULL = still current

    legal_entity_id = Column(UUID(as_uuid=True), ForeignKey("legal_entities.id"))
    business_unit_id = Column(UUID(as_uuid=True), ForeignKey("business_units.id"))
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"))
    location_id = Column(UUID(as_uuid=True), ForeignKey("locations.id"))
    position_id = Column(UUID(as_uuid=True), ForeignKey("positions.id"))
    designation = Column(Text)
    grade = Column(String(50))
    manager_employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"))
    functional_manager_employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"))
    hrbp_employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"))
    cost_center_id = Column(UUID(as_uuid=True), ForeignKey("cost_centers.id"))
    employment_type = Column(String(30))
    probation_end = Column(Date)
    confirmation_date = Column(Date)
    notice_period_days = Column(Integer)
    work_mode = Column(String(20))

    event_type = Column(String(30), nullable=False)
    event_reason = Column(Text)
    workflow_instance_id = Column(UUID(as_uuid=True))  # set when this change was gated by a Part 5 workflow
    created_by = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        CheckConstraint("event_type IN (" + ",".join(f"'{e}'" for e in LIFECYCLE_EVENT_TYPES) + ")", name="employment_records_event_type_check"),
    )


# ---- documents & letters ----


class EmployeeDocument(Base, TenantOwned):
    __tablename__ = "employee_documents"
    __table_args__ = (
        CheckConstraint("visibility IN (" + ",".join(f"'{v}'" for v in DOCUMENT_VISIBILITY) + ")", name="employee_documents_visibility_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    type = Column(String(50), nullable=False)  # a document_type master code
    file_ref = Column(Text)
    issued_date = Column(Date)
    expiry_date = Column(Date)
    verified_by = Column(Text)
    visibility = Column(String(20), nullable=False, server_default=text("'hr'"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


LETTER_TEMPLATE_KEYS = (
    "offer", "appointment", "confirmation", "increment", "promotion", "transfer",
    "experience", "relieving", "address_proof", "noc",
)


class LetterTemplate(Base, TenantOwned):
    __tablename__ = "letter_templates"
    __table_args__ = (UniqueConstraint("tenant_id", "key", "version", name="letter_templates_tenant_key_version_uq"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(String(50), nullable=False)
    name = Column(Text, nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    status = Column(String(20), nullable=False, server_default=text("'draft'"))
    html_tpl = Column(Text, nullable=False)
    variables_schema_json = Column(JSONB, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class LetterRecord(Base, TenantOwned):
    """The "letter register" (section 4's own wording) -- every letter ever generated,
    permanently, plus a `verification_token` a recipient's own link can be checked
    against (the "digital verification QR/URL" minus an actual QR IMAGE -- see docs/
    build_log.md's own Part 7 note on why no qrcode library was added for this)."""

    __tablename__ = "letter_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    template_key = Column(String(50), nullable=False)
    template_version = Column(Integer, nullable=False)
    rendered_html = Column(Text, nullable=False)
    verification_token = Column(Text, nullable=False, unique=True)
    generated_by = Column(Text)
    generated_at = Column(DateTime(timezone=True), server_default=text("now()"))


# ---- data import / migration toolkit ----


class ImportBatch(Base, TenantOwned):
    __tablename__ = "import_batches"
    __table_args__ = (
        CheckConstraint("entity IN (" + ",".join(f"'{e}'" for e in IMPORT_ENTITY_TYPES) + ")", name="import_batches_entity_check"),
        CheckConstraint("status IN (" + ",".join(f"'{s}'" for s in IMPORT_BATCH_STATUSES) + ")", name="import_batches_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity = Column(String(30), nullable=False)
    column_mapping_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status = Column(String(20), nullable=False, server_default=text("'preview'"))
    row_count = Column(Integer, nullable=False, server_default=text("0"))
    error_count = Column(Integer, nullable=False, server_default=text("0"))
    created_by = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class ImportRow(Base, TenantOwned):
    __tablename__ = "import_rows"
    __table_args__ = (
        CheckConstraint("status IN (" + ",".join(f"'{s}'" for s in IMPORT_ROW_STATUSES) + ")", name="import_rows_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id = Column(UUID(as_uuid=True), ForeignKey("import_batches.id"), nullable=False)
    row_number = Column(Integer, nullable=False)
    raw_json = Column(JSONB, nullable=False)
    status = Column(String(20), nullable=False, server_default=text("'valid'"))
    errors_json = Column(JSONB)
    committed_entity_id = Column(UUID(as_uuid=True))
