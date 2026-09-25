"""Background verification cases (docs/HRMS_COMPLETE_SPEC.txt Part 9 section 2).

Lifecycle: awaiting_consent -> (consent captured) -> initiated -> in_progress (vendor
webhook) -> completed. Initiation is refused without consent. A vendor webhook updates
per-check statuses / report / discrepancy only; the final `decision` is always a human's
(`decide()`), never the vendor's -- HITL, per the spec.

Sits beside (does not replace) the older per-application `bgv_documents` flow in
app/bgv/router.py, which stays exactly as it is for the existing 13-module parity.
"""

import hmac
import secrets
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.onboarding import BGV_CHECK_STATUSES, BGV_CHECK_TYPES, BGV_DECISIONS, BgvCase
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import TenantContext


class BgvError(Exception):
    pass


class BgvConsentRequiredError(BgvError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_case(
    db: Session, tenant: TenantContext, *, subject_type: str, subject_id: UUID, package: Optional[list[str]] = None,
    package_code: Optional[str] = None, preboarding_case_id: Optional[UUID] = None, vendor_connection_id: Optional[UUID] = None,
) -> BgvCase:
    checks = package or SettingsService(db).get("onboarding.bgv.default_package", SettingContext(tenant=tenant)) or []
    unknown = [c for c in checks if c not in BGV_CHECK_TYPES]
    if unknown or not checks:
        raise BgvError(f"invalid BGV package: {unknown or 'empty'}")
    case = BgvCase(
        tenant_id=tenant.tenant_id, subject_type=subject_type, subject_id=subject_id, package_code=package_code,
        preboarding_case_id=preboarding_case_id, vendor_connection_id=vendor_connection_id,
        checks_json=[{"type": c, "status": "pending"} for c in checks], webhook_token=secrets.token_urlsafe(32),
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def record_consent(db: Session, case: BgvCase, *, consent_text: str) -> BgvCase:
    if not consent_text.strip():
        raise BgvError("consent text is required")
    case.consent_at = _now()
    case.consent_text = consent_text
    db.commit()
    db.refresh(case)
    return case


def initiate(db: Session, case: BgvCase, *, vendor_reference: Optional[str] = None) -> BgvCase:
    if case.consent_at is None:
        raise BgvConsentRequiredError("consent must be captured before BGV is initiated")
    if case.status not in ("awaiting_consent", "initiated"):
        raise BgvError(f"cannot initiate a case in status {case.status!r}")
    case.status = "initiated"
    case.initiated_at = case.initiated_at or _now()
    if vendor_reference:
        case.vendor_reference = vendor_reference
    db.commit()
    db.refresh(case)
    return case


def find_by_webhook_token(db: Session, tenant: TenantContext, token: str) -> Optional[BgvCase]:
    for case in db.query(BgvCase).filter(BgvCase.tenant_id == tenant.tenant_id, BgvCase.webhook_token == token).limit(1):
        if hmac.compare_digest(case.webhook_token, token):
            return case
    return None


def apply_webhook(db: Session, case: BgvCase, payload: dict) -> BgvCase:
    """Vendor status push. payload: {"checks": [{"type", "status", "notes"?}], "report_file"?,
    "discrepancy"?, "vendor_reference"?}. Idempotent: replaying the same payload is a no-op
    in effect. Never touches `decision`."""
    if case.status in ("awaiting_consent", "cancelled"):
        raise BgvError(f"case is {case.status!r}; webhook ignored")
    by_type = {c["type"]: dict(c) for c in case.checks_json or []}
    for update in payload.get("checks", []):
        check_type, status = update.get("type"), update.get("status")
        if check_type not in by_type:
            raise BgvError(f"check {check_type!r} is not part of this case's package")
        if status not in BGV_CHECK_STATUSES:
            raise BgvError(f"unknown check status {status!r}")
        by_type[check_type]["status"] = status
        if update.get("notes") is not None:
            by_type[check_type]["notes"] = update["notes"]
    case.checks_json = list(by_type.values())
    if payload.get("report_file"):
        case.report_file_path = payload["report_file"]
    if payload.get("discrepancy"):
        case.discrepancy = payload["discrepancy"]
    if payload.get("vendor_reference"):
        case.vendor_reference = payload["vendor_reference"]
    if all(c["status"] not in ("pending", "in_progress") for c in case.checks_json):
        case.status = "completed"
        case.completed_at = case.completed_at or _now()
    else:
        case.status = "in_progress"
    db.commit()
    db.refresh(case)
    return case


def decide(db: Session, case: BgvCase, *, decision: str, actor: str) -> BgvCase:
    if decision not in BGV_DECISIONS or decision == "pending":
        raise BgvError(f"invalid decision {decision!r}")
    if case.status != "completed":
        raise BgvError("a decision can only be recorded once every check has a result")
    if decision == "clear" and any(c["status"] != "clear" for c in case.checks_json):
        raise BgvError("'clear' requires every check to be clear -- use accept_with_discrepancy or reject")
    case.decision = decision
    case.decided_by = actor
    case.decided_at = _now()
    db.commit()
    db.refresh(case)
    return case


def case_to_dict(case: BgvCase, *, include_webhook_token: bool = False) -> dict:
    data = {
        "id": str(case.id), "subject_type": case.subject_type, "subject_id": str(case.subject_id),
        "preboarding_case_id": str(case.preboarding_case_id) if case.preboarding_case_id else None,
        "package_code": case.package_code, "checks": case.checks_json or [], "status": case.status,
        "consent_at": case.consent_at.isoformat() if case.consent_at else None, "vendor_reference": case.vendor_reference,
        "report_file_path": case.report_file_path, "discrepancy": case.discrepancy, "decision": case.decision,
        "decided_by": case.decided_by,
    }
    if include_webhook_token:
        data["webhook_token"] = case.webhook_token
    return data
