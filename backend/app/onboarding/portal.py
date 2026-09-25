"""PreboardingPortal (docs/HRMS_COMPLETE_SPEC.txt Part 9 section 1, named in this part's
own CHECKS): the offer-accepted -> joining-day experience for a new hire, authenticated by
a magic-link `portal_token` on the case itself (weeks-long, rotatable -- a 15-minute
login-style MagicLink from Part 5 would expire long before a typical notice period ends).

What the portal needs is tenant DATA, never code: which forms (Part 6 `meta_forms` keys),
which documents (`document_type` master codes) and which policies must be acknowledged
all come from `onboarding.*` settings, overridable per case via `attributes_json`.
"""

import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core_hr import employees as employees_service
from app.models.candidate import Candidate
from app.models.application import Application
from app.models.offer import Offer
from app.models.onboarding import OnboardingPlan, OnboardingTask, PreboardingCase, PreboardingDocument
from app.platform.metadata import forms as forms_service
from app.platform.metadata import masters
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import TenantContext

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = BACKEND_ROOT / "uploads" / "onboarding"


class PortalAuthError(Exception):
    """str(exc) is one of "invalid" | "expired" | "closed"."""


class PortalValidationError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _append_history(case: PreboardingCase, event: str, actor: str, **details) -> None:
    case.history_json = [*(case.history_json or []), {"event": event, "actor": actor, "at": _now().isoformat(), **details}]


class PreboardingPortal:
    def __init__(self, db: Session, tenant: TenantContext):
        self.db = db
        self.tenant = tenant
        self._settings = SettingsService(db)
        self._ctx = SettingContext(tenant=tenant)

    def _setting(self, key: str):
        return self._settings.get(key, self._ctx)

    # ---- case lifecycle ----

    def create_case(
        self, *, email: str, joining_date: date, first_name: str, last_name: Optional[str] = None,
        candidate_id: Optional[UUID] = None, application_id: Optional[UUID] = None, offer_id: Optional[UUID] = None,
        attributes: Optional[dict] = None, welcome_content: Optional[dict] = None, created_by: str = "system",
    ) -> PreboardingCase:
        if offer_id is not None:
            existing = self.db.query(PreboardingCase).filter(PreboardingCase.tenant_id == self.tenant.tenant_id, PreboardingCase.offer_id == offer_id).first()
            if existing is not None:
                return existing  # one case per accepted offer
        employee = employees_service.create_employee(
            self.db, self.tenant, first_name=first_name, last_name=last_name, status="pre_hire",
            worker_type=(attributes or {}).get("worker_type", "employee"), personal_email=email,
        )
        case = PreboardingCase(
            tenant_id=self.tenant.tenant_id, candidate_id=candidate_id, application_id=application_id, offer_id=offer_id,
            employee_id=employee.id, email=email.lower(), joining_date=joining_date, status="invited",
            portal_token=secrets.token_urlsafe(32),
            portal_token_expires_at=_now() + timedelta(days=int(self._setting("onboarding.portal.link_ttl_days"))),
            attributes_json=attributes or {}, welcome_content_json=welcome_content or {},
        )
        _append_history(case, "created", created_by)
        self.db.add(case)
        self.db.commit()
        self.db.refresh(case)
        return case

    def create_case_from_offer(self, offer_id: UUID, *, joining_date: Optional[date] = None, attributes: Optional[dict] = None, created_by: str = "system") -> PreboardingCase:
        offer = self.db.get(Offer, offer_id)
        if offer is None:
            raise PortalValidationError("offer not found")
        application = self.db.get(Application, offer.application_id) if offer.application_id else None
        candidate = self.db.get(Candidate, application.candidate_id) if application else None
        if candidate is None or not candidate.email:
            raise PortalValidationError("offer has no candidate with an email address")
        doj = joining_date or offer.joining_date
        if doj is None:
            raise PortalValidationError("joining_date is required (offer has none)")
        name = (candidate.full_name or candidate.email).split(" ", 1)
        return self.create_case(
            email=candidate.email, joining_date=doj, first_name=name[0], last_name=name[1] if len(name) > 1 else None,
            candidate_id=candidate.id, application_id=application.id, offer_id=offer.id, attributes=attributes, created_by=created_by,
        )

    def rotate_token(self, case: PreboardingCase) -> PreboardingCase:
        case.portal_token = secrets.token_urlsafe(32)
        case.portal_token_expires_at = _now() + timedelta(days=int(self._setting("onboarding.portal.link_ttl_days")))
        self.db.commit()
        self.db.refresh(case)
        return case

    def authenticate(self, token: str) -> PreboardingCase:
        case = self.db.query(PreboardingCase).filter(PreboardingCase.tenant_id == self.tenant.tenant_id, PreboardingCase.portal_token == token).first()
        if case is None:
            raise PortalAuthError("invalid")
        if case.portal_token_expires_at < _now():
            raise PortalAuthError("expired")
        if case.status in ("revoked", "no_show", "joined"):
            raise PortalAuthError("closed")
        return case

    def change_joining_date(self, case: PreboardingCase, new_date: date, *, actor: str, reason: Optional[str] = None) -> PreboardingCase:
        from app.onboarding import plans

        old = case.joining_date
        case.joining_date = new_date
        _append_history(case, "joining_date_changed", actor, old=old.isoformat(), new=new_date.isoformat(), reason=reason)
        self.db.commit()
        plan = self.db.query(OnboardingPlan).filter(OnboardingPlan.tenant_id == self.tenant.tenant_id, OnboardingPlan.case_id == case.id).first()
        if plan is not None:
            plans.reschedule(self.db, self.tenant, plan, new_date)
        self.db.refresh(case)
        return case

    def _close(self, case: PreboardingCase, status: str, *, actor: str, reason: Optional[str]) -> PreboardingCase:
        if case.status == "joined":
            raise PortalValidationError("case already converted to an employee")
        case.status = status
        _append_history(case, status, actor, reason=reason)
        if case.employee_id:
            from app.models.core_hr import Employee

            employee = self.db.get(Employee, case.employee_id)
            if employee is not None and employee.status == "pre_hire":
                employee.status = "inactive"  # kept, never deleted -- the record of an offer that didn't convert
        for task in self._open_tasks(case):
            task.status = "skipped"
        self.db.commit()
        self.db.refresh(case)
        return case

    def mark_no_show(self, case: PreboardingCase, *, actor: str, reason: Optional[str] = None) -> PreboardingCase:
        return self._close(case, "no_show", actor=actor, reason=reason)

    def revoke_offer(self, case: PreboardingCase, *, actor: str, reason: Optional[str] = None) -> PreboardingCase:
        return self._close(case, "revoked", actor=actor, reason=reason)

    def _open_tasks(self, case: PreboardingCase) -> list[OnboardingTask]:
        plan = self.db.query(OnboardingPlan).filter(OnboardingPlan.tenant_id == self.tenant.tenant_id, OnboardingPlan.case_id == case.id).first()
        if plan is None:
            return []
        return (
            self.db.query(OnboardingTask)
            .filter(OnboardingTask.tenant_id == self.tenant.tenant_id, OnboardingTask.plan_id == plan.id, OnboardingTask.status.in_(("pending", "blocked")))
            .all()
        )

    # ---- requirements (tenant data, per-case overridable) ----

    def required_forms(self, case: PreboardingCase) -> list[str]:
        return list((case.attributes_json or {}).get("required_forms") or self._setting("onboarding.portal.required_forms") or [])

    def required_documents(self, case: PreboardingCase) -> list[str]:
        return list((case.attributes_json or {}).get("required_documents") or self._setting("onboarding.documents.required_types") or [])

    def required_policies(self, case: PreboardingCase) -> list[str]:
        return list((case.attributes_json or {}).get("required_policies") or self._setting("onboarding.portal.required_policies") or [])

    # ---- new-hire actions ----

    def _touch(self, case: PreboardingCase) -> None:
        if case.status == "invited":
            case.status = "in_progress"

    def submit_form(self, case: PreboardingCase, form_key: str, data: dict) -> PreboardingCase:
        form = forms_service.get_form(self.db, self.tenant, form_key)
        if form is None:
            raise PortalValidationError(f"unknown form {form_key!r}")
        missing = [f for f in (form.schema_json or {}).get("required", []) if data.get(f) in (None, "")]
        if missing:
            raise PortalValidationError(f"missing required fields: {', '.join(missing)}")
        case.form_submissions_json = {**(case.form_submissions_json or {}), form_key: {"data": data, "submitted_at": _now().isoformat()}}
        self._touch(case)
        self._refresh_ready(case)
        self.db.commit()
        self.db.refresh(case)
        return case

    def acknowledge_policy(self, case: PreboardingCase, policy_code: str) -> PreboardingCase:
        if policy_code not in self.required_policies(case) and policy_code not in (case.welcome_content_json or {}).get("policies", []):
            raise PortalValidationError(f"unknown policy {policy_code!r}")
        case.policy_acks_json = {**(case.policy_acks_json or {}), policy_code: _now().isoformat()}
        self._touch(case)
        self._refresh_ready(case)
        self.db.commit()
        self.db.refresh(case)
        return case

    def upload_document(self, case: PreboardingCase, document_type_code: str, file_bytes: bytes, extension: str) -> PreboardingDocument:
        allowed = {v.code for v in masters.list_values(self.db, self.tenant, "document_type")}
        if document_type_code not in allowed:
            raise PortalValidationError(f"{document_type_code!r} is not an active document_type")
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4()}.{extension.lstrip('.').lower() or 'bin'}"
        (UPLOAD_DIR / filename).write_bytes(file_bytes)
        document = PreboardingDocument(tenant_id=self.tenant.tenant_id, case_id=case.id, document_type_code=document_type_code, file_path=filename)
        self.db.add(document)
        self._touch(case)
        self.db.commit()
        self.db.refresh(document)
        return document

    def extract_document(self, document: PreboardingDocument, document_text: str) -> PreboardingDocument:
        """AI prefill via the `llm.resume_extraction` purpose (the spec's own choice).
        Advisory only -- stored for HR's verification queue, never auto-verifies."""
        from app.platform.ai import gateway

        system = (
            "You extract structured fields from an identity, education or employment document. "
            "Return only a JSON object of the fields you can read; use null for anything not present. Never guess."
        )
        try:
            fields = gateway.complete_json(
                self.db, self.tenant, purpose="llm.resume_extraction", system=system,
                messages=[{"role": "user", "content": f"Document type: {document.document_type_code}\n\n{document_text}"}],
            )
            document.extracted_json = {"fields": fields, "source": "ai"}
        except Exception as exc:  # no connection routed / provider error -> HR just verifies manually
            document.extracted_json = {"error": type(exc).__name__}
        self.db.commit()
        self.db.refresh(document)
        return document

    def verify_document(self, document: PreboardingDocument, *, actor: str, approve: bool, reason: Optional[str] = None) -> PreboardingDocument:
        document.verification_status = "verified" if approve else "rejected"
        document.verified_by = actor
        document.verified_at = _now()
        document.rejection_reason = None if approve else reason
        case = self.db.get(PreboardingCase, document.case_id)
        if case is not None:
            self._refresh_ready(case)
        self.db.commit()
        self.db.refresh(document)
        return document

    def documents(self, case: PreboardingCase) -> list[PreboardingDocument]:
        return (
            self.db.query(PreboardingDocument)
            .filter(PreboardingDocument.tenant_id == self.tenant.tenant_id, PreboardingDocument.case_id == case.id)
            .order_by(PreboardingDocument.uploaded_at.asc())
            .all()
        )

    # ---- readiness ----

    def readiness(self, case: PreboardingCase) -> dict:
        forms_req = self.required_forms(case)
        docs_req = self.required_documents(case)
        policies_req = self.required_policies(case)
        submitted = set((case.form_submissions_json or {}).keys())
        verified_docs = {d.document_type_code for d in self.documents(case) if d.verification_status == "verified"}
        acked = set((case.policy_acks_json or {}).keys())

        plan = self.db.query(OnboardingPlan).filter(OnboardingPlan.tenant_id == self.tenant.tenant_id, OnboardingPlan.case_id == case.id).first()
        pre_doj_tasks = []
        if plan is not None:
            pre_doj_tasks = (
                self.db.query(OnboardingTask)
                .filter(OnboardingTask.tenant_id == self.tenant.tenant_id, OnboardingTask.plan_id == plan.id, OnboardingTask.due_offset_days <= 0)
                .all()
            )
        items = (
            [f in submitted for f in forms_req] + [d in verified_docs for d in docs_req]
            + [p in acked for p in policies_req] + [t.status in ("done", "skipped") for t in pre_doj_tasks]
        )
        percent = 100 if not items else round(100 * sum(items) / len(items))
        return {
            "percent": percent,
            "forms": {"required": forms_req, "submitted": sorted(submitted & set(forms_req))},
            "documents": {"required": docs_req, "verified": sorted(verified_docs & set(docs_req))},
            "policies": {"required": policies_req, "acknowledged": sorted(acked & set(policies_req))},
            "pre_joining_tasks": {"total": len(pre_doj_tasks), "done": sum(t.status in ("done", "skipped") for t in pre_doj_tasks)},
        }

    def _refresh_ready(self, case: PreboardingCase) -> None:
        self.db.flush()
        if case.status in ("invited", "in_progress", "ready"):
            case.status = "ready" if self.readiness(case)["percent"] == 100 else "in_progress"

    def portal_view(self, case: PreboardingCase) -> dict:
        """What the new hire sees -- never HR-only fields (verified_by, history, attributes)."""
        return {
            "status": case.status,
            "joining_date": case.joining_date.isoformat(),
            "welcome": case.welcome_content_json or {},
            "readiness": self.readiness(case),
            "documents": [
                {"id": str(d.id), "document_type": d.document_type_code, "status": d.verification_status, "rejection_reason": d.rejection_reason}
                for d in self.documents(case)
            ],
            "forms_submitted": sorted((case.form_submissions_json or {}).keys()),
            "policies_acknowledged": sorted((case.policy_acks_json or {}).keys()),
        }


def case_to_dict(case: PreboardingCase) -> dict:
    return {
        "id": str(case.id), "candidate_id": str(case.candidate_id) if case.candidate_id else None,
        "offer_id": str(case.offer_id) if case.offer_id else None, "employee_id": str(case.employee_id) if case.employee_id else None,
        "email": case.email, "joining_date": case.joining_date.isoformat(), "status": case.status,
        "attributes": case.attributes_json or {}, "history": case.history_json or [],
        "joined_at": case.joined_at.isoformat() if case.joined_at else None,
    }
