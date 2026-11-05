"""Part 17.12: interviewer availability and pools, kept in the app (no Excel).

Me (any staff login):
- GET  /api/v1/ui/interviewers/me              my weekly hours, blocked dates, limits, upcoming interviews, pools
- PUT  /api/v1/ui/interviewers/me              save them
HR (recruitment.interview.view / .edit):
- GET  /api/v1/ui/interviewers                 everyone: hours, blocked dates, booked this week, free slots tomorrow, pools
- PUT  /api/v1/ui/interviewers/{email}         edit someone's availability
- GET|POST /api/v1/ui/interviewers/pools, PATCH|DELETE /api/v1/ui/interviewers/pools/{id}
- POST /api/v1/ui/interviewers/import-excel    ONE-TIME copy from the old Excel tracker (dry_run first)
- GET  /api/v1/ui/interviewers/import-sample   sample workbook for that import

weekly_pattern: {"mon": [{"start": "09:00", "end": "18:00"}], ..., "sun": false}  (company time)
exceptions:     [{"date": "2026-10-02", "available": false, "note": "Holiday"}]
Every query filters on the current company's tenant_id explicitly.
"""

import io
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.interview_scheduling.availability import _WEEKDAY_KEYS, _company_tz, free_slots, get_availability_for_email, upsert_availability
from app.models.interview import Interview
from app.models.interviewer_availability import InterviewerAvailability
from app.models.interviewer_pool import InterviewerPool
from app.models.job_role import JobRole
from app.models.user import User
from app.platform.iam.authz import has_permission
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/ui/interviewers", tags=["ui-interviewers"])
DEFAULT_HOURS = [{"start": "10:00", "end": "18:00"}]


def _need(db, tenant, user, permission: str) -> None:
    if not has_permission(db, tenant, user, permission):
        raise HTTPException(status_code=403, detail=f"Missing permission: {permission}")


class AvailabilityIn(BaseModel):
    weekly_pattern: dict[str, Any] = Field(default_factory=dict)
    exceptions: list[dict] = Field(default_factory=list)
    max_interviews_per_day: Optional[int] = Field(None, ge=0, le=20)
    max_interviews_per_week: Optional[int] = Field(None, ge=0, le=100)
    interviewer_name: Optional[str] = Field(None, max_length=200)

    @field_validator("weekly_pattern")
    @classmethod
    def _pattern(cls, v: dict) -> dict:
        for key, day in v.items():
            if key not in _WEEKDAY_KEYS:
                raise ValueError(f"{key!r} isn't a day of the week")
            if day is False:
                continue
            if not isinstance(day, list):
                raise ValueError(f"{key}: choose \"not working\" or add the times they can interview")
            for r in day:
                start, end = str(r.get("start", ""))[:5], str(r.get("end", ""))[:5]
                if len(start) != 5 or len(end) != 5 or start >= end:
                    raise ValueError(f"{key}: each time range needs start before end, e.g. 09:00 - 13:00")
        return v

    @field_validator("exceptions")
    @classmethod
    def _exceptions(cls, v: list) -> list:
        for e in v:
            try:
                date.fromisoformat(str(e.get("date")))
            except ValueError as exc:
                raise ValueError("each blocked date needs a date like 2026-10-02") from exc
        return v


def _set_limits(db, tenant, email: str, payload: "AvailabilityIn") -> None:
    """An empty limit means "no limit" (upsert_availability only ever sets non-empty values)."""
    row = get_availability_for_email(db, tenant, email)
    if row is not None:
        row.max_interviews_per_day = payload.max_interviews_per_day or None
        row.max_interviews_per_week = payload.max_interviews_per_week or None
        db.commit()


def _pools_of(db, tenant, email: str) -> list[str]:
    return [p.name for p in db.query(InterviewerPool).filter(InterviewerPool.tenant_id == tenant.tenant_id, InterviewerPool.active.is_(True)).all()
            if email in [str(e).lower() for e in p.member_emails_json or []]]


def _tomorrow_slots(db, tenant) -> list[datetime]:
    from app.interview_scheduling.negotiation import _negotiation_mechanics, _slot_times_for_day, _tomorrow_ist

    mech = _negotiation_mechanics(db, tenant)
    return _slot_times_for_day(_tomorrow_ist(datetime.now(timezone.utc)), mech["slot_hours"])


def _row(db, tenant, email: str, name: Optional[str], row: Optional[InterviewerAvailability], slots: list[datetime]) -> dict:
    tz = _company_tz(db, tenant)
    now = datetime.now(timezone.utc)
    week = (db.query(Interview).filter(Interview.tenant_id == tenant.tenant_id, Interview.interviewer_email == email,
                                       Interview.scheduled_at >= now, Interview.scheduled_at < now + timedelta(days=7)).count())
    today = datetime.now(tz).date().isoformat()
    return {
        "email": email, "name": (row.interviewer_name if row else None) or name or email,
        "weekly_pattern": (row.weekly_pattern_json if row else None) or {},
        "exceptions": [e for e in (row.exceptions_json if row else []) or [] if str(e.get("date")) >= today],
        "max_interviews_per_day": row.max_interviews_per_day if row else None,
        "max_interviews_per_week": row.max_interviews_per_week if row else None,
        "has_availability": has_hours(row), "booked_next_7_days": week, "pools": _pools_of(db, tenant, email),
        "free_tomorrow": [s.astimezone(tz).strftime("%H:%M") for s in free_slots(db, tenant, email, slots)],
        "source": row.source if row else None,
    }


# ---------------------------------------------------------------- me

@router.get("/me")
def my_availability(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    email = current_user.email.lower()
    row = get_availability_for_email(db, tenant, email)
    out = _row(db, tenant, email, current_user.full_name, row, _tomorrow_slots(db, tenant))
    now = datetime.now(timezone.utc)
    upcoming = (db.query(Interview).filter(Interview.tenant_id == tenant.tenant_id, Interview.interviewer_email == email, Interview.scheduled_at >= now)
                .order_by(Interview.scheduled_at).limit(20).all())
    out["upcoming"] = [{"id": str(i.id), "scheduled_at": i.scheduled_at.isoformat(), "application_id": str(i.application_id)} for i in upcoming]
    if not row:
        out["weekly_pattern"] = {k: (DEFAULT_HOURS if k not in ("sat", "sun") else False) for k in _WEEKDAY_KEYS}
        out["suggested"] = True
    return out


@router.put("/me")
def save_my_availability(payload: AvailabilityIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    upsert_availability(db, tenant, interviewer_email=current_user.email, interviewer_name=payload.interviewer_name or current_user.full_name,
                        weekly_pattern=payload.weekly_pattern, exceptions=payload.exceptions,
                        max_interviews_per_day=payload.max_interviews_per_day, max_interviews_per_week=payload.max_interviews_per_week, source="manual")
    _set_limits(db, tenant, current_user.email, payload)
    log_action(db, "interviewer_availability", None, "availability_saved", current_user.email[:50], {"email": current_user.email})
    return my_availability(db, current_user)


# ---------------------------------------------------------------- HR view

@router.get("")
def all_interviewers(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    _need(db, tenant, current_user, "recruitment.interview.view")
    rows = {r.interviewer_email: r for r in db.query(InterviewerAvailability).filter(InterviewerAvailability.tenant_id == tenant.tenant_id).all()}
    emails = set(rows)
    for p in db.query(InterviewerPool).filter(InterviewerPool.tenant_id == tenant.tenant_id).all():
        emails |= {str(e).lower() for e in p.member_emails_json or []}
    for u in db.query(User).filter(User.tenant_id == tenant.tenant_id, User.role.in_(("interviewer", "hiring_manager"))).all():
        emails.add(u.email.lower())
    names = {u.email.lower(): u.full_name for u in db.query(User).filter(User.tenant_id == tenant.tenant_id).all()}
    slots = _tomorrow_slots(db, tenant)
    tz = _company_tz(db, tenant)
    items = sorted((_row(db, tenant, e, names.get(e), rows.get(e), slots) for e in emails), key=lambda r: (r["name"] or "").lower())
    return {"items": items, "slot_times_tomorrow": [s.astimezone(tz).strftime("%H:%M") for s in slots]}


@router.put("/{email}")
def save_availability_for(email: str, payload: AvailabilityIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    _need(db, tenant, current_user, "recruitment.interview.edit")
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Give the interviewer's email")
    upsert_availability(db, tenant, interviewer_email=email, interviewer_name=payload.interviewer_name, weekly_pattern=payload.weekly_pattern,
                        exceptions=payload.exceptions, max_interviews_per_day=payload.max_interviews_per_day,
                        max_interviews_per_week=payload.max_interviews_per_week, source="manual")
    _set_limits(db, tenant, email, payload)
    log_action(db, "interviewer_availability", None, "availability_saved", current_user.email[:50], {"email": email.lower(), "by_hr": True})
    row = get_availability_for_email(db, tenant, email)
    return _row(db, tenant, email.lower(), None, row, _tomorrow_slots(db, tenant))


# ---------------------------------------------------------------- pools

class PoolIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    job_role_id: Optional[UUID] = None
    skills: list[str] = Field(default_factory=list)
    member_emails: list[str] = Field(default_factory=list)
    active: bool = True


def _pool(p: InterviewerPool, jobs: dict) -> dict:
    return {"id": str(p.id), "name": p.name, "job_role_id": str(p.job_role_id) if p.job_role_id else None, "job_title": jobs.get(p.job_role_id),
            "skills": p.skills_json or [], "member_emails": p.member_emails_json or [], "active": p.active, "source": p.source}


@router.get("/pools")
def list_pools(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    _need(db, tenant, current_user, "recruitment.interview.view")
    jobs = dict(db.query(JobRole.id, JobRole.title).filter(JobRole.tenant_id == tenant.tenant_id).all())
    return [_pool(p, jobs) for p in db.query(InterviewerPool).filter(InterviewerPool.tenant_id == tenant.tenant_id).order_by(InterviewerPool.name).all()]


def _clean_members(emails: list[str]) -> list[str]:
    out = []
    for e in emails:
        e = str(e).strip().lower()
        if "@" not in e:
            raise HTTPException(status_code=400, detail=f"'{e}' isn't an email address")
        if e not in out:
            out.append(e)
    return out


def has_hours(row) -> bool:
    """Part 18.28: availability means at least one day with hours, not just a row (an Excel
    import can leave a row with an empty week)."""
    return row is not None and any((row.weekly_pattern_json or {}).values())


def interviewer_problem(db: Session, tenant, email: str) -> Optional[dict]:
    """Part 18.28: an interviewer can only be used when they have an email AND availability
    (the days / hours they can interview). Returns the plain-words problem, or None."""
    email = (email or "").strip().lower()
    if "@" not in email:
        return {"code": "INTERVIEWER_NO_EMAIL", "message": f"'{email or '(blank)'}' isn't an email address.",
                "fix": "Give the interviewer's work email.", "fix_path": "/interviews/interviewers", "fix_label": "Open interviewers"}
    row = db.query(InterviewerAvailability).filter(InterviewerAvailability.tenant_id == tenant.tenant_id,
                                                   InterviewerAvailability.interviewer_email == email).first()
    if not has_hours(row):
        who = (row.interviewer_name if row and row.interviewer_name else None) or email
        return {"code": "INTERVIEWER_NO_AVAILABILITY", "message": f"{who} has no availability yet, so we can't offer interview times for them.",
                "fix": "Add the days and hours they can interview first.", "fix_path": f"/interviews/interviewers?edit={email}",
                "fix_label": "Add availability", "email": email}
    return None


def _check_members_ready(db: Session, tenant, emails: list[str]) -> None:
    for e in emails:
        problem = interviewer_problem(db, tenant, e)
        if problem:
            raise HTTPException(status_code=400, detail=problem)


@router.post("/pools", status_code=201)
def create_pool(payload: PoolIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    _need(db, tenant, current_user, "recruitment.interview.edit")
    if payload.job_role_id is None and not payload.skills:
        raise HTTPException(status_code=400, detail="Pick the job this pool is for, or the skills it covers")
    _check_members_ready(db, tenant, _clean_members(payload.member_emails))
    p = InterviewerPool(tenant_id=tenant.tenant_id, name=payload.name.strip(), job_role_id=payload.job_role_id,
                        skills_json=[s.strip() for s in payload.skills if s.strip()], member_emails_json=_clean_members(payload.member_emails), active=payload.active)
    db.add(p)
    db.commit()
    log_action(db, "interviewer_pool", p.id, "pool_created", current_user.email[:50], {"name": p.name})
    jobs = dict(db.query(JobRole.id, JobRole.title).filter(JobRole.tenant_id == tenant.tenant_id).all())
    return _pool(p, jobs)


@router.patch("/pools/{pool_id}")
def update_pool(pool_id: UUID, payload: PoolIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    _need(db, tenant, current_user, "recruitment.interview.edit")
    p = db.query(InterviewerPool).filter(InterviewerPool.tenant_id == tenant.tenant_id, InterviewerPool.id == pool_id).first()
    if p is None:
        raise HTTPException(status_code=404, detail="Pool not found")
    p.name, p.job_role_id, p.active = payload.name.strip(), payload.job_role_id, payload.active
    p.skills_json = [s.strip() for s in payload.skills if s.strip()]
    members = _clean_members(payload.member_emails)
    _check_members_ready(db, tenant, [e for e in members if e not in (p.member_emails_json or [])])  # only newly added people
    p.member_emails_json = members
    db.commit()
    log_action(db, "interviewer_pool", p.id, "pool_updated", current_user.email[:50], {"name": p.name, "members": len(p.member_emails_json)})
    jobs = dict(db.query(JobRole.id, JobRole.title).filter(JobRole.tenant_id == tenant.tenant_id).all())
    return _pool(p, jobs)


@router.delete("/pools/{pool_id}", status_code=204)
def delete_pool(pool_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    _need(db, tenant, current_user, "recruitment.interview.edit")
    p = db.query(InterviewerPool).filter(InterviewerPool.tenant_id == tenant.tenant_id, InterviewerPool.id == pool_id).first()
    if p is None:
        raise HTTPException(status_code=404, detail="Pool not found")
    db.delete(p)
    db.commit()
    log_action(db, "interviewer_pool", pool_id, "pool_deleted", current_user.email[:50], {"name": p.name})


# ---------------------------------------------------------------- one-time Excel import

def _read_tracker(data: bytes) -> tuple[dict[str, list[str]], dict[str, str]]:
    """(job title -> interviewer names) from 'Interviewer Pool', (name -> email) from 'Mails'."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    pools: dict[str, list[str]] = {}
    mails: dict[str, str] = {}
    if "Interviewer Pool" in wb.sheetnames:
        rows = list(wb["Interviewer Pool"].iter_rows(values_only=True))
        header = [str(h or "").strip() for h in (rows[0] if rows else [])]
        if "Job Title" in header and "Eligible Interviewers" in header:
            jc, ic = header.index("Job Title"), header.index("Eligible Interviewers")
            for r in rows[1:]:
                if r and len(r) > max(jc, ic) and r[jc]:
                    names = [n.strip() for n in str(r[ic] or "").split(",") if n.strip()]
                    pools[str(r[jc]).strip()] = list(dict.fromkeys(names))
    if "Mails" in wb.sheetnames:
        rows = list(wb["Mails"].iter_rows(values_only=True))
        header = [str(h or "").strip() for h in (rows[0] if rows else [])]
        if "Name" in header and "Mail Id" in header:
            nc, mc = header.index("Name"), header.index("Mail Id")
            for r in rows[1:]:
                if r and len(r) > max(nc, mc) and r[nc] and r[mc] and "@" in str(r[mc]):
                    mails[str(r[nc]).strip().lower()] = str(r[mc]).strip().lower()
    if not pools and not mails:
        raise HTTPException(status_code=400, detail="This file has no 'Interviewer Pool' or 'Mails' sheet. Download the sample to see the layout.")
    return pools, mails


@router.post("/import-excel")
async def import_excel(file: UploadFile = File(...), dry_run: bool = Form(True), db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    _need(db, tenant, current_user, "recruitment.interview.edit")
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Please upload the tracker as an .xlsx file.")
    pools, mails = _read_tracker(await file.read())
    jobs = {t.strip().lower(): i for i, t in db.query(JobRole.id, JobRole.title).filter(JobRole.tenant_id == tenant.tenant_id).all()}
    plan_pools, missing_email = [], []
    for title, names in pools.items():
        emails = []
        for n in names:
            e = mails.get(n.lower())
            if e:
                emails.append(e)
            else:
                missing_email.append(n)
        plan_pools.append({"name": f"{title} interviewers", "job_title": title, "job_found": title.lower() in jobs, "members": emails})
    report = {"dry_run": dry_run, "pools": len(plan_pools), "interviewers": len(mails), "names_without_email": sorted(set(missing_email)),
              "pools_detail": plan_pools}
    if dry_run:
        return report
    created_pools = 0
    for pp in plan_pools:
        job_id = jobs.get(pp["job_title"].lower())
        exists = db.query(InterviewerPool).filter(InterviewerPool.tenant_id == tenant.tenant_id, InterviewerPool.name == pp["name"]).first()
        if exists is None:
            db.add(InterviewerPool(tenant_id=tenant.tenant_id, name=pp["name"], job_role_id=job_id,
                                   skills_json=[] if job_id else [pp["job_title"]], member_emails_json=pp["members"], source="excel_import"))
            created_pools += 1
    db.commit()
    added = 0
    for name, email in mails.items():
        if get_availability_for_email(db, tenant, email) is None:
            upsert_availability(db, tenant, interviewer_email=email, interviewer_name=name.title(), source="excel_import")
            added += 1
    log_action(db, "interviewer_pool", None, "excel_tracker_imported", current_user.email[:50], {"pools": created_pools, "interviewers": added})
    return {**report, "created_pools": created_pools, "created_interviewers": added}


@router.get("/import-sample")
def import_sample(current_user: User = Depends(get_current_user)):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Interviewer Pool"
    ws.append(["Job Title", "Eligible Interviewers"])
    ws.append(["RPA Developer", "Priya Raman, Arjun Mehta"])
    ms = wb.create_sheet("Mails")
    ms.append(["Name", "Mail Id"])
    ms.append(["Priya Raman", "priya.raman@example.com"])
    ms.append(["Arjun Mehta", "arjun.mehta@example.com"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": 'attachment; filename="interviewer-tracker-sample.xlsx"'})
