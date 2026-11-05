"""Employee master (docs/HRMS_COMPLETE_SPEC.txt Part 7 section 2) -- identity docs and
bank account numbers are encrypted through `platform.secrets` (the exact same envelope-
encryption `SecretStore` Part 3's Connection passwords and Part 5's TOTP secrets already
use), never stored plaintext. `employee_code` comes from Part 6's own numbering sequences
-- a real payoff of that part, not a new ID scheme invented here.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.core_hr import Employee
from app.models.secret import Secret, SecretScope
from app.platform.metadata.sequences import SequenceNotFoundError, define, next_value
from app.platform.secrets.store import SecretNotFoundError, get_secret_store
from app.platform.tenancy.context import TenantContext

_ENCRYPTED_FIELDS = ("pan", "aadhaar", "passport", "visa", "driving_licence", "bank_account")
EMPLOYEE_CODE_SEQUENCE_KEY = "core_hr.employee_code"
DEFAULT_EMPLOYEE_CODE_PATTERN = "EMP-{SEQ:5}"


def _secret_store(db: Session, tenant: TenantContext):
    return get_secret_store(db, Secret, SecretScope, str(tenant.tenant_id))


def _secret_ref(employee_id: UUID, field: str) -> str:
    return f"employee-{employee_id}-{field}"


def generate_employee_code(db: Session, tenant: TenantContext) -> str:
    try:
        return next_value(db, tenant, EMPLOYEE_CODE_SEQUENCE_KEY)
    except SequenceNotFoundError:
        define(db, tenant, key=EMPLOYEE_CODE_SEQUENCE_KEY, pattern=DEFAULT_EMPLOYEE_CODE_PATTERN, reset="never")
        return next_value(db, tenant, EMPLOYEE_CODE_SEQUENCE_KEY)


def create_employee(
    db: Session, tenant: TenantContext, *, first_name: str, last_name: Optional[str] = None,
    employee_code: Optional[str] = None, status: str = "pre_hire", worker_type: str = "employee", **kwargs,
) -> Employee:
    employee = Employee(
        tenant_id=tenant.tenant_id, employee_code=employee_code or generate_employee_code(db, tenant),
        first_name=first_name, last_name=last_name, status=status, worker_type=worker_type, **kwargs,
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def set_encrypted_field(db: Session, tenant: TenantContext, employee: Employee, field: str, plaintext: str, *, created_by: str) -> None:
    if field not in _ENCRYPTED_FIELDS:
        raise ValueError(f"{field!r} is not an encrypted employee field (one of {_ENCRYPTED_FIELDS})")
    ref = _secret_ref(employee.id, field)
    store = _secret_store(db, tenant)
    try:
        store.rotate(ref, plaintext, created_by=created_by)
    except SecretNotFoundError:
        store.put(ref, plaintext, created_by=created_by)
    setattr(employee, f"{field}_secret_ref", ref)
    if field == "aadhaar":
        employee.aadhaar_last4 = plaintext[-4:] if len(plaintext) >= 4 else plaintext
    db.commit()


def get_encrypted_field(db: Session, tenant: TenantContext, employee: Employee, field: str) -> Optional[str]:
    ref = getattr(employee, f"{field}_secret_ref", None)
    if not ref:
        return None
    try:
        return _secret_store(db, tenant).get(ref)
    except SecretNotFoundError:
        return None


def masked_aadhaar(employee: Employee) -> Optional[str]:
    """Section 2's own "Aadhaar (masked last 4)" -- for display without ever decrypting
    the full number. `aadhaar_last4` is the ONE unencrypted fragment this row stores; see
    app.models.core_hr's own docstring for why storing just that is acceptable (masking
    display needs it, it alone can't reconstruct a real Aadhaar number)."""
    if not employee.aadhaar_secret_ref:
        return None
    return f"XXXX-XXXX-{employee.aadhaar_last4 or 'XXXX'}"


def employee_to_dict(employee: Employee, *, reveal_encrypted: Optional[dict[str, str]] = None) -> dict:
    """A plain dict for API responses -- encrypted fields never appear except as the
    masked/presence-only form below, unless the caller explicitly passed a decrypted
    value in `reveal_encrypted` (an authz-gated, audited reveal -- see api_router.py)."""
    reveal_encrypted = reveal_encrypted or {}
    return {
        "id": str(employee.id), "employee_code": employee.employee_code, "user_id": str(employee.user_id) if employee.user_id else None,
        "status": employee.status, "worker_type": employee.worker_type,
        "first_name": employee.first_name, "last_name": employee.last_name, "preferred_name": employee.preferred_name,
        "pronouns": employee.pronouns, "dob": employee.dob.isoformat() if employee.dob else None,
        "gender": employee.gender, "marital_status": employee.marital_status, "nationality": employee.nationality,
        "blood_group": employee.blood_group, "personal_email": employee.personal_email, "personal_phone": employee.personal_phone,
        "addresses": employee.addresses_json, "emergency_contacts": employee.emergency_contacts_json,
        "family": employee.family_json, "education": employee.education_json, "prior_employment": employee.prior_employment_json,
        "skills": employee.skills_json, "certifications": employee.certifications_json, "languages": employee.languages_json,
        "pan": reveal_encrypted.get("pan", "***" if employee.pan_secret_ref else None),
        "aadhaar": reveal_encrypted.get("aadhaar", masked_aadhaar(employee)),
        "passport": reveal_encrypted.get("passport", "***" if employee.passport_secret_ref else None),
        "bank_account": reveal_encrypted.get("bank_account", "***" if employee.bank_account_secret_ref else None),
        "bank_verification_status": employee.bank_verification_status,
        "custom_fields": employee.custom_fields,
    }
