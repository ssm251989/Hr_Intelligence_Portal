"""Part 15.6 agency portal (docs/HRMS_COMPLETE_SPEC.txt: "agency users submit candidates to
assigned jobs only").

HR side (recruitment.agency.view / .edit):
- GET    /api/v1/agencies                               agencies + counts
- POST   /api/v1/agencies                               add an agency
- PATCH  /api/v1/agencies/{id}                          rename / contact / pause
- GET    /api/v1/agencies/{id}                          jobs, users, submissions
- PUT    /api/v1/agencies/{id}/jobs                     which jobs it may send candidates for
- POST   /api/v1/agencies/{id}/members                  invite a user (set-password link)
- DELETE /api/v1/agencies/{id}/members/{user_id}        take portal access away (user kept)

Agency side (agency.portal.* + an agency_members row; flat role "agency" is locked to these
paths by app/auth/dependencies.py):
- GET    /api/v1/agency-portal/me                       my agency + assigned open jobs
- GET    /api/v1/agency-portal/submissions              candidates my agency sent + plain stage
- POST   /api/v1/agency-portal/submit                   send a candidate (resume + consent)

Ownership rule: the first submission wins -- a person whose email is already in the
candidate database is refused (409), so an agency never gets credit for someone the company
already knew. Agencies only ever see a plain stage, never scores or notes.
Every query filters on the current company's tenant_id explicitly.
"""

import secrets
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.agency import AgencyJobAssignment, AgencyMember, AgencySubmission, RecruitmentAgency
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.user import User
from app.platform.iam.authz import has_permission, require
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/agencies", tags=["agencies"])
portal_router = APIRouter(prefix="/api/v1/agency-portal", tags=["agency-portal"])

# What an agency may see of an application -- never the internal status names.
_STAGE = {
    "received": "received", "screened": "received",
    "hr_selected": "shortlisted", "on_hold": "on_hold",
    "interview_scheduled": "interviewing",
    "interview_selected": "final_stages", "salary_ok": "final_stages", "salary_above_band": "final_stages",
    "salary_approved": "final_stages", "bgv_requested": "final_stages", "bgv_pending": "final_stages", "bgv_cleared": "final_stages",
    "offer_sent": "offer", "onboarding_started": "hired", "onboarding_completed": "hired",
    "hr_rejected": "not_selected", "interview_rejected": "not_selected", "salary_rejected": "not_selected", "bgv_rejected": "not_selected",
}


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def _tid():
    return require_current_tenant().tenant_id


def _agency_or_404(db: Session, agency_id: uuid.UUID) -> RecruitmentAgency:
    agency = db.query(RecruitmentAgency).filter(RecruitmentAgency.tenant_id == _tid(), RecruitmentAgency.id == agency_id).first()
    if agency is None:
        raise HTTPException(status_code=404, detail="Agency not found")
    return agency


def _open_job(job: Optional[JobRole]) -> bool:
    from app.jobs.service import get_application_deadline

    if job is None or job.status != "published":
        return False
    deadline = get_application_deadline(job)
    return deadline is None or deadline >= date.today()


# ---------------------------------------------------------------- HR side

# Part 21.5: Recruitment / BGV / Both, with contact, contract, fees (recruitment) and checks + prices, SLA, report format (BGV)
AGENCY_TYPES = ("recruitment", "bgv", "both")
BGV_CHECKS = ("education", "employment", "address", "criminal", "identity", "reference", "drug")


class AgencyFields(BaseModel):
    agency_type: Optional[str] = None
    contact_person: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    address: Optional[str] = None
    gst_pan: Optional[str] = Field(None, max_length=50)
    contract_start: Optional[date] = None
    contract_end: Optional[date] = None
    fee_type: Optional[str] = None
    fee_value: Optional[float] = Field(None, ge=0)
    payment_terms: Optional[str] = None
    bgv_checks: Optional[list[dict]] = None  # [{"check": "education", "price": 800}]
    turnaround_days: Optional[int] = Field(None, ge=0, le=365)
    report_format: Optional[str] = None


class AgencyIn(AgencyFields):
    name: str = Field(min_length=1, max_length=255)
    contact_email: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None


class AgencyPatch(AgencyFields):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    contact_email: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None
    active: Optional[bool] = None


def _apply_fields(agency: RecruitmentAgency, data: dict) -> None:
    if "agency_type" in data:
        if data["agency_type"] not in AGENCY_TYPES:
            raise HTTPException(status_code=400, detail="Type must be Recruitment, BGV or Both.")
        agency.agency_type = data["agency_type"]
    if "fee_type" in data and data["fee_type"] not in (None, "", "percent", "fixed"):
        raise HTTPException(status_code=400, detail="Fee must be a percentage or a fixed amount.")
    if data.get("contract_start") and data.get("contract_end") and data["contract_end"] < data["contract_start"]:
        raise HTTPException(status_code=400, detail="The contract can't end before it starts.")
    for key in ("contact_person", "phone", "address", "gst_pan", "contract_start", "contract_end", "fee_type", "fee_value", "payment_terms",
                "turnaround_days", "report_format"):
        if key in data:
            value = data[key]
            setattr(agency, key, (value.strip() or None) if isinstance(value, str) else value)
    if "bgv_checks" in data and data["bgv_checks"] is not None:
        checks = []
        for c in data["bgv_checks"]:
            code = str((c or {}).get("check") or "").strip().lower()
            if code not in BGV_CHECKS:
                raise HTTPException(status_code=400, detail=f"Unknown check: {code or '(empty)'}.")
            try:
                price = float(c.get("price")) if c.get("price") not in (None, "") else None
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"The price for {code} must be a number.")
            checks.append({"check": code, "price": price})
        agency.bgv_checks_json = checks


class JobsIn(BaseModel):
    job_ids: list[uuid.UUID]


class MemberIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    full_name: Optional[str] = Field(None, max_length=255)


def _counts(db: Session, model, agency_ids: list[uuid.UUID]) -> dict:
    if not agency_ids:
        return {}
    rows = (db.query(model.agency_id, func.count(model.id))
            .filter(model.tenant_id == _tid(), model.agency_id.in_(agency_ids)).group_by(model.agency_id).all())
    return {a: n for a, n in rows}


def _agency_row(agency: RecruitmentAgency, jobs: int = 0, members: int = 0, submissions: int = 0) -> dict:
    return {"id": str(agency.id), "name": agency.name, "contact_email": agency.contact_email, "notes": agency.notes,
            "active": agency.active, "created_at": _iso(agency.created_at), "jobs": jobs, "members": members, "submissions": submissions,
            # Part 21.5
            "agency_type": agency.agency_type or "recruitment", "contact_person": agency.contact_person, "phone": agency.phone,
            "address": agency.address, "gst_pan": agency.gst_pan, "contract_start": _iso(agency.contract_start), "contract_end": _iso(agency.contract_end),
            "fee_type": agency.fee_type, "fee_value": float(agency.fee_value) if agency.fee_value is not None else None,
            "payment_terms": agency.payment_terms, "bgv_checks": agency.bgv_checks_json or [], "turnaround_days": agency.turnaround_days,
            "report_format": agency.report_format}


def _stats(db: Session, agency: RecruitmentAgency) -> dict:
    """Part 21.5: recruitment -> submitted, hired, fees due; BGV -> cases, average turnaround, overdue, cost so far."""
    from app.models.agency import BgvAssignment
    from app.models.offer import Offer

    tid = _tid()
    out: dict = {}
    if (agency.agency_type or "recruitment") in ("recruitment", "both"):
        rows = (db.query(Application).join(AgencySubmission, AgencySubmission.application_id == Application.id)
                .filter(AgencySubmission.tenant_id == tid, AgencySubmission.agency_id == agency.id).all())
        hired = [a for a in rows if a.status in ("onboarding_started", "onboarding_completed")]
        due, unknown = 0.0, 0
        for a in hired:
            if agency.fee_type == "fixed" and agency.fee_value is not None:
                due += float(agency.fee_value)
            elif agency.fee_type == "percent" and agency.fee_value is not None:
                o = db.query(Offer).filter(Offer.application_id == a.id).first()
                ctc = (o.ctc_breakup_json or {}) if o is not None else {}
                annual = ctc.get("annual_ctc") or ctc.get("total") or ctc.get("ctc")
                if annual:
                    due += float(annual) * float(agency.fee_value) / 100
                else:
                    unknown += 1
            else:
                unknown += 1
        out["recruitment"] = {"submitted": len(rows), "hired": len(hired), "fees_due": round(due, 2), "fees_unknown": unknown}
    if (agency.agency_type or "recruitment") in ("bgv", "both"):
        cases = db.query(BgvAssignment).filter(BgvAssignment.tenant_id == tid, BgvAssignment.agency_id == agency.id).all()
        done = [c for c in cases if c.report_uploaded_at is not None and c.created_at is not None]
        avg = round(sum((c.report_uploaded_at - c.created_at).total_seconds() for c in done) / len(done) / 86400, 1) if done else None
        today = date.today()
        out["bgv"] = {"cases": len(cases), "open": sum(1 for c in cases if c.status in ("assigned", "in_progress")),
                      "average_turnaround_days": avg,
                      "overdue": sum(1 for c in cases if c.status in ("assigned", "in_progress") and c.due_date and c.due_date < today),
                      "cost_so_far": round(sum(float(c.cost or 0) for c in cases if c.status in ("report_received", "decided")), 2)}
    return out


@router.get("")
def list_agencies(agency_type: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(require("recruitment.agency.view"))):
    q = db.query(RecruitmentAgency).filter(RecruitmentAgency.tenant_id == _tid())
    if agency_type in ("recruitment", "bgv"):  # Part 21.5: "Both" counts for either
        q = q.filter(RecruitmentAgency.agency_type.in_((agency_type, "both")))
    agencies = q.order_by(RecruitmentAgency.name).all()
    ids = [a.id for a in agencies]
    jobs, members, subs = _counts(db, AgencyJobAssignment, ids), _counts(db, AgencyMember, ids), _counts(db, AgencySubmission, ids)
    return [_agency_row(a, jobs.get(a.id, 0), members.get(a.id, 0), subs.get(a.id, 0)) for a in agencies]


@router.post("", status_code=201)
def create_agency(payload: AgencyIn, db: Session = Depends(get_db), current_user: User = Depends(require("recruitment.agency.edit"))):
    name = payload.name.strip()
    if db.query(RecruitmentAgency).filter(RecruitmentAgency.tenant_id == _tid(), func.lower(RecruitmentAgency.name) == name.lower()).first():
        raise HTTPException(status_code=409, detail="An agency with this name already exists")
    agency = RecruitmentAgency(tenant_id=_tid(), name=name, contact_email=(payload.contact_email or "").strip().lower() or None, notes=payload.notes)
    _apply_fields(agency, payload.model_dump(exclude_unset=True))
    db.add(agency)
    db.commit()
    db.refresh(agency)
    log_action(db, "recruitment_agency", agency.id, "agency_created", current_user.email, {"name": agency.name})
    return _agency_row(agency)


IMPORT_COLUMNS = ["Name", "Type (Recruitment / BGV / Both)", "Contact person", "Email", "Phone", "Address", "GST / PAN", "Contract start (YYYY-MM-DD)",
                  "Contract end (YYYY-MM-DD)", "Fee type (percent / fixed)", "Fee value", "Payment terms", "BGV checks (check:price; ...)",
                  "Turnaround days", "Report format", "Notes"]


@router.get("/import-sample")
def import_sample(db: Session = Depends(get_db), current_user: User = Depends(require("recruitment.agency.edit"))):
    """Part 21.5: an Excel file to fill in and import."""
    import io

    from fastapi.responses import StreamingResponse
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Agencies"
    ws.append(IMPORT_COLUMNS)
    ws.append(["TalentBridge Staffing", "Recruitment", "Ravi Kumar", "ravi@talentbridge.example", "+91 98000 11111", "Hyderabad", "", "2026-04-01",
               "2027-03-31", "percent", 8.33, "30 days after joining", "", "", "", "Sample row - replace it"])
    ws.append(["VerifyFirst BGV", "BGV", "Anita Rao", "ops@verifyfirst.example", "+91 98000 22222", "Bengaluru", "", "2026-04-01", "2027-03-31", "", "", "",
               "education:800; employment:1000; address:600; criminal:900; identity:300", 7, "PDF report per candidate", "Sample row - replace it"])
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 24
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": 'attachment; filename="agencies-import-sample.xlsx"'})


@router.post("/import")
async def import_agencies(file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(require("recruitment.agency.edit"))):
    """Part 21.5: create agencies from the sample's columns; an existing name is updated. Returns what happened per row."""
    import io

    from openpyxl import load_workbook

    try:
        ws = load_workbook(io.BytesIO(await file.read()), data_only=True).active
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="That isn't an Excel file - use the sample.")
    results = []
    types = {"recruitment": "recruitment", "bgv": "bgv", "both": "both"}
    for n, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        vals = [(str(v).strip() if v is not None else "") for v in (list(row) + [None] * 16)[:16]]
        name = vals[0]
        if not name or "sample row" in vals[15].lower():
            continue
        try:
            checks = []
            for part in [x for x in vals[12].split(";") if x.strip()]:
                code, _, price = part.partition(":")
                checks.append({"check": code.strip().lower(), "price": price.strip() or None})
            data = {"agency_type": types.get(vals[1].lower(), "recruitment"), "contact_person": vals[2], "phone": vals[4], "address": vals[5],
                    "gst_pan": vals[6], "contract_start": date.fromisoformat(vals[7][:10]) if vals[7] else None,
                    "contract_end": date.fromisoformat(vals[8][:10]) if vals[8] else None, "fee_type": vals[9].lower() or None,
                    "fee_value": float(vals[10]) if vals[10] else None, "payment_terms": vals[11], "bgv_checks": checks,
                    "turnaround_days": int(float(vals[13])) if vals[13] else None, "report_format": vals[14]}
            agency = db.query(RecruitmentAgency).filter(RecruitmentAgency.tenant_id == _tid(), func.lower(RecruitmentAgency.name) == name.lower()).first()
            created = agency is None
            if created:
                agency = RecruitmentAgency(tenant_id=_tid(), name=name)
                db.add(agency)
            agency.contact_email = vals[3].lower() or agency.contact_email
            agency.notes = vals[15] or agency.notes
            _apply_fields(agency, data)
            db.commit()
            results.append({"row": n, "name": name, "result": "created" if created else "updated"})
        except HTTPException as exc:
            db.rollback()
            results.append({"row": n, "name": name, "result": "error", "error": exc.detail})
        except ValueError as exc:
            db.rollback()
            results.append({"row": n, "name": name, "result": "error", "error": f"Check the dates and numbers ({exc})"})
    log_action(db, "recruitment_agency", None, "agencies_imported", current_user.email, {"rows": len(results)})
    return {"results": results}


@router.patch("/{agency_id}")
def update_agency(agency_id: uuid.UUID, payload: AgencyPatch, db: Session = Depends(get_db),
                  current_user: User = Depends(require("recruitment.agency.edit"))):
    agency = _agency_or_404(db, agency_id)
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes:
        changes["name"] = changes["name"].strip()
    if "contact_email" in changes:
        changes["contact_email"] = (changes["contact_email"] or "").strip().lower() or None
    _apply_fields(agency, changes)
    for key, value in changes.items():
        if key in ("name", "contact_email", "notes", "active"):
            setattr(agency, key, value)
    db.commit()
    db.refresh(agency)
    log_action(db, "recruitment_agency", agency.id, "agency_updated", current_user.email, {k: v for k, v in changes.items() if k != "notes"})
    return _agency_row(agency)


@router.get("/{agency_id}")
def agency_detail(agency_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(require("recruitment.agency.view"))):
    agency = _agency_or_404(db, agency_id)
    tid = _tid()
    jobs = (db.query(JobRole).join(AgencyJobAssignment, AgencyJobAssignment.job_role_id == JobRole.id)
            .filter(AgencyJobAssignment.tenant_id == tid, AgencyJobAssignment.agency_id == agency.id).order_by(JobRole.title).all())
    members = (db.query(User, AgencyMember).join(AgencyMember, AgencyMember.user_id == User.id)
               .filter(AgencyMember.tenant_id == tid, AgencyMember.agency_id == agency.id).order_by(User.full_name).all())
    subs = (db.query(AgencySubmission, Application, Candidate, JobRole)
            .join(Application, Application.id == AgencySubmission.application_id)
            .join(Candidate, Candidate.id == Application.candidate_id)
            .join(JobRole, JobRole.id == Application.job_role_id)
            .filter(AgencySubmission.tenant_id == tid, AgencySubmission.agency_id == agency.id)
            .order_by(AgencySubmission.created_at.desc()).limit(200).all())
    return {
        **_agency_row(agency, len(jobs), len(members), len(subs)),
        "stats": _stats(db, agency),
        "job_list": [{"id": str(j.id), "title": j.title, "location": j.location, "status": j.status, "open": _open_job(j)} for j in jobs],
        "member_list": [{"user_id": str(u.id), "email": u.email, "full_name": u.full_name, "added_at": _iso(m.created_at)} for u, m in members],
        "submission_list": [{"application_id": str(a.id), "candidate_id": str(c.id), "candidate_name": c.full_name, "job_title": j.title,
                             "status": a.status, "submitted_at": _iso(s.created_at)} for s, a, c, j in subs],
    }


@router.put("/{agency_id}/jobs")
def set_agency_jobs(agency_id: uuid.UUID, payload: JobsIn, db: Session = Depends(get_db),
                    current_user: User = Depends(require("recruitment.agency.edit"))):
    agency = _agency_or_404(db, agency_id)
    tid = _tid()
    wanted = set(payload.job_ids)
    if wanted:
        found = {j for (j,) in db.query(JobRole.id).filter(JobRole.tenant_id == tid, JobRole.id.in_(wanted)).all()}
        if found != wanted:
            raise HTTPException(status_code=400, detail="One or more jobs were not found")
    current = {a.job_role_id: a for a in db.query(AgencyJobAssignment).filter(AgencyJobAssignment.tenant_id == tid, AgencyJobAssignment.agency_id == agency.id).all()}
    for job_id, row in current.items():
        if job_id not in wanted:
            db.delete(row)
    for job_id in wanted - set(current):
        db.add(AgencyJobAssignment(tenant_id=tid, agency_id=agency.id, job_role_id=job_id))
    db.commit()
    log_action(db, "recruitment_agency", agency.id, "agency_jobs_set", current_user.email, {"job_ids": sorted(str(j) for j in wanted)})
    return {"jobs": len(wanted)}


@router.post("/{agency_id}/members", status_code=201)
def invite_member(agency_id: uuid.UUID, payload: MemberIn, db: Session = Depends(get_db),
                  current_user: User = Depends(require("recruitment.agency.edit"))):
    """Creates the agency user with an unusable password and emails a one-time set-password
    link (template `recruitment.agency_invite`). If mail can't go out, the link is returned
    so HR can share it themselves -- same approach as the setup wizard's admin invite."""
    from app.core.config import settings as app_settings
    from app.core.security import hash_password
    from app.platform.comms.service import send
    from app.platform.iam.action_tokens import create_action_token
    from app.platform.iam.roles import bridge_single_user

    agency = _agency_or_404(db, agency_id)
    tenant = require_current_tenant()
    email = payload.email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if user is not None:
        if user.role != "agency":
            raise HTTPException(status_code=409, detail="This email belongs to a staff account, so it can't be used for an agency")
        if db.query(AgencyMember).filter(AgencyMember.tenant_id == tenant.tenant_id, AgencyMember.user_id == user.id).first():
            raise HTTPException(status_code=409, detail="This person already has agency portal access")
    else:
        user = User(tenant_id=tenant.tenant_id, email=email, full_name=(payload.full_name or "").strip() or email, role="agency",
                    hashed_password=hash_password(secrets.token_urlsafe(32)))
        db.add(user)
        db.commit()
        db.refresh(user)
        bridge_single_user(db, tenant, user)
    db.add(AgencyMember(tenant_id=tenant.tenant_id, agency_id=agency.id, user_id=user.id))
    db.commit()
    log_action(db, "recruitment_agency", agency.id, "agency_member_added", current_user.email, {"user_id": str(user.id), "email": email})

    token = create_action_token(db, tenant, entity_type="user", entity_id=user.id, action="set_password", created_by=current_user.email, ttl_days=7).token
    link = f"{app_settings.FRONTEND_URL.rstrip('/')}/set-password?token={token}"
    try:
        message = send(db, tenant, template_key="recruitment.agency_invite", to=[email],
                       ctx={"link": link, "agency_name": agency.name, "invited_by": current_user.full_name or current_user.email},
                       purpose="email.outbound.default")
        delivered = message.status in ("sent", "queued")
    except Exception:
        delivered = False
    return {"user_id": str(user.id), "email_sent": delivered, "link": None if delivered else link}


@router.delete("/{agency_id}/members/{user_id}", status_code=204)
def remove_member(agency_id: uuid.UUID, user_id: uuid.UUID, db: Session = Depends(get_db),
                  current_user: User = Depends(require("recruitment.agency.edit"))):
    agency = _agency_or_404(db, agency_id)
    row = db.query(AgencyMember).filter(AgencyMember.tenant_id == _tid(), AgencyMember.agency_id == agency.id, AgencyMember.user_id == user_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Not a member of this agency")
    db.delete(row)
    db.commit()
    log_action(db, "recruitment_agency", agency.id, "agency_member_removed", current_user.email, {"user_id": str(user_id)})


# ---------------------------------------------------------------- agency side

def _my_agency(db: Session, user: User, permission: str) -> RecruitmentAgency:
    tenant = require_current_tenant()
    if not has_permission(db, tenant, user, permission):
        raise HTTPException(status_code=403, detail=f"Missing permission: {permission}")
    agency = (db.query(RecruitmentAgency).join(AgencyMember, AgencyMember.agency_id == RecruitmentAgency.id)
              .filter(AgencyMember.tenant_id == tenant.tenant_id, AgencyMember.user_id == user.id).first())
    if agency is None:
        raise HTTPException(status_code=403, detail="Your account isn't linked to an agency. Please ask the HR team.")
    return agency


def _assigned_open_jobs(db: Session, agency: RecruitmentAgency) -> list[JobRole]:
    jobs = (db.query(JobRole).join(AgencyJobAssignment, AgencyJobAssignment.job_role_id == JobRole.id)
            .filter(AgencyJobAssignment.tenant_id == _tid(), AgencyJobAssignment.agency_id == agency.id).order_by(JobRole.title).all())
    return [j for j in jobs if _open_job(j)]


@portal_router.get("/me")
def portal_me(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.jobs.service import get_application_deadline

    agency = _my_agency(db, current_user, "agency.portal.view")
    jobs = _assigned_open_jobs(db, agency) if agency.active else []
    sent = dict(db.query(Application.job_role_id, func.count(AgencySubmission.id))
                .join(Application, Application.id == AgencySubmission.application_id)
                .filter(AgencySubmission.tenant_id == _tid(), AgencySubmission.agency_id == agency.id).group_by(Application.job_role_id).all())
    return {
        "agency": {"id": str(agency.id), "name": agency.name, "active": agency.active},
        "user": {"full_name": current_user.full_name, "email": current_user.email},
        "jobs": [{"id": str(j.id), "title": j.title, "department": j.department, "location": j.location, "job_type": j.job_type,
                  "experience_min_years": float(j.experience_min_years) if j.experience_min_years is not None else None,
                  "experience_max_years": float(j.experience_max_years) if j.experience_max_years is not None else None,
                  "positions": j.positions_count, "deadline": _iso(get_application_deadline(j)), "jd_text": j.jd_text,
                  "sent": sent.get(j.id, 0)} for j in jobs],
    }


@portal_router.get("/submissions")
def portal_submissions(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    agency = _my_agency(db, current_user, "agency.portal.view")
    rows = (db.query(AgencySubmission, Application, Candidate, JobRole, User)
            .join(Application, Application.id == AgencySubmission.application_id)
            .join(Candidate, Candidate.id == Application.candidate_id)
            .join(JobRole, JobRole.id == Application.job_role_id)
            .outerjoin(User, User.id == AgencySubmission.submitted_by)
            .filter(AgencySubmission.tenant_id == _tid(), AgencySubmission.agency_id == agency.id)
            .order_by(AgencySubmission.created_at.desc()).limit(500).all())
    return [{"id": str(s.id), "candidate_name": c.full_name, "candidate_email": c.email, "job_title": j.title,
             "stage": _STAGE.get(a.status or "received", "received"), "submitted_at": _iso(s.created_at),
             "submitted_by": (u.full_name or u.email) if u else None} for s, a, c, j, u in rows]


@portal_router.post("/submit", status_code=201)
async def portal_submit(
    background_tasks: BackgroundTasks,
    job_id: uuid.UUID = Form(...),
    full_name: str = Form(..., min_length=1, max_length=255),
    email: str = Form(..., min_length=3, max_length=255),
    phone: Optional[str] = Form(None, max_length=50),
    consent_confirmed: bool = Form(...),
    resume: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.candidates.resume_extraction import ResumeExtractionError, UnsupportedFileTypeError, extract_text
    from app.candidates.router import ALLOWED_EXTENSIONS
    from app.candidates.storage import save_resume_file
    from app.jobs.service import notify_job_owner_of_new_application
    from app.platform.ops.av_scan import UploadRejectedError, ensure_clean
    from app.privacy.service import record_consent
    from app.public.router import _parse_resume_in_background
    from app.recruitment.career_site import CURRENT_CONSENT_VERSION

    agency = _my_agency(db, current_user, "agency.portal.create")
    if not agency.active:
        raise HTTPException(status_code=403, detail="Your agency is paused. Please ask the HR team.")
    if not consent_confirmed:
        raise HTTPException(status_code=400, detail="Please confirm the candidate agreed to share their details with us")
    tenant = require_current_tenant()
    job = next((j for j in _assigned_open_jobs(db, agency) if j.id == job_id), None)
    if job is None:
        raise HTTPException(status_code=404, detail="This job isn't open for your agency")

    email = email.strip().lower()
    if db.query(Candidate.id).filter(Candidate.tenant_id == tenant.tenant_id, func.lower(Candidate.email) == email).first():
        raise HTTPException(status_code=409, detail="This person is already in our system, so we can't take them as a new referral")
    from app.recruitment.automation import find_duplicate

    if phone and find_duplicate(db, tenant, phone=phone)[0] is not None:  # Part 17.13: same person, other email
        raise HTTPException(status_code=409, detail="This person is already in our system, so we can't take them as a new referral")

    extension = resume.filename.rsplit(".", 1)[-1].lower() if resume.filename and "." in resume.filename else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only PDF, Word (.docx / .doc) and image (JPG / PNG) resumes are supported")
    file_bytes = await resume.read()
    try:
        extract_text(file_bytes, resume.filename)
    except (UnsupportedFileTypeError, ResumeExtractionError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not read resume: {exc}") from exc
    try:
        ensure_clean(file_bytes)
    except UploadRejectedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    resume_path = save_resume_file(file_bytes, extension)

    from app.recruitment.automation import file_hash

    sha = file_hash(file_bytes)
    if find_duplicate(db, tenant, resume_sha256=sha)[0] is not None:
        raise HTTPException(status_code=409, detail="This resume is already in our system, so we can't take it as a new referral")
    candidate = Candidate(tenant_id=tenant.tenant_id, full_name=full_name.strip(), email=email, phone=(phone or "").strip() or None,
                          resume_path=resume_path, source="agency", resume_sha256=sha)
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    application = Application(tenant_id=tenant.tenant_id, job_role_id=job.id, candidate_id=candidate.id, status="received",
                              consent_given_at=datetime.now(timezone.utc), consent_version=CURRENT_CONSENT_VERSION)
    db.add(application)
    db.commit()
    db.refresh(application)
    submission = AgencySubmission(tenant_id=tenant.tenant_id, agency_id=agency.id, application_id=application.id, submitted_by=current_user.id)
    db.add(submission)
    db.commit()

    actor = f"agency:{current_user.email}"[:50]  # audit_log.actor is 50 chars
    details = {"source": "agency", "agency_id": str(agency.id), "agency_name": agency.name}
    log_action(db, "candidate", candidate.id, "candidate_uploaded", actor, {"resume_path": resume_path, **details})
    log_action(db, "application", application.id, "application_created", actor, {"status": application.status, "job_role_id": str(job.id), **details})
    record_consent(db, tenant, subject_type="candidate", subject_id=candidate.id, subject_email=email, purpose="recruitment.application",
                   channel="agency", evidence={"consent_version": CURRENT_CONSENT_VERSION, "confirmed_by": current_user.email, "agency_id": str(agency.id)})
    notify_job_owner_of_new_application(db, job, candidate)
    background_tasks.add_task(_parse_resume_in_background, candidate.id)
    return {"id": str(submission.id), "application_id": str(application.id), "stage": "received"}
