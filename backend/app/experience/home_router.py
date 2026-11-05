"""Part 15 STEP 15.5 -- role-based home screens (L-N2, O1-O4, V3/V5).

- `GET /api/v1/me/home` -- which home this user gets (hr / manager / employee), the widget
  layout to show (their own saved layout, else the company default for that home, else
  none -> the frontend's built-in default), and whether they may set company defaults.
- `PUT|DELETE /api/v1/me/home/layout` -- save / reset the caller's own widget layout (O3).
- `PUT /api/v1/home/defaults/{kind}` -- an admin sets the company default layout per home.
- `GET /api/v1/home/hiring-flow` -- "Where candidates go" Sankey (V5), from where every
  application is now: each stage's count = applications that reached it; the drop-outs are
  the terminal "not selected / did not pass / declined / checks failed" statuses.
- `GET /api/v1/home/alerts` -- the heads-up panel (O4): helpdesk response times missed,
  interview feedback overdue, joiners in the next 3 days whose onboarding isn't ready (P6).
- `GET /api/v1/home/people-by-office` -- headcount per office with map coordinates.

Layouts are stored through the Settings service (user scope for "mine", tenant scope for the
company defaults), so they get the same history/revert as every other setting.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.platform.iam.authz import has_permission, require
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1", tags=["home"])

HOME_KINDS = ("hr", "manager", "employee")
_HR_ROLES = {"Super Admin", "HR Admin", "HRBP", "Recruiter"}
_MANAGER_ROLES = {"Manager", "Hiring Manager", "Interviewer"}
_MAX_WIDGETS = 40


def _home_kind(db: Session, tenant, user: User) -> str:
    from app.platform.iam.org_scope import direct_reportees, my_employee_id
    from app.platform.iam.roles import role_names_for

    roles = set(role_names_for(db, tenant, user))
    if roles & _HR_ROLES or user.role in ("admin", "recruiter"):
        return "hr"
    if roles & _MANAGER_ROLES or user.role in ("hiring_manager", "interviewer"):
        return "manager"
    me = my_employee_id(db, tenant, user)
    if me is not None and direct_reportees(db, tenant, me):
        return "manager"
    return "employee"


def _settings():
    from app.platform.settings.resolver import SettingsService

    return SettingsService


def _ctx(tenant, user: Optional[User] = None):
    from app.platform.settings.resolver import SettingContext

    return SettingContext(tenant=tenant, scope_ids={"user": user.id} if user else {})


def _clean_layout(layout: Any) -> list[dict]:
    """Only {i, x, y, w, h} integers per widget -- nothing else is stored."""
    if not isinstance(layout, list) or len(layout) > _MAX_WIDGETS:
        raise HTTPException(status_code=400, detail="That layout isn't valid. Please reset the home page and try again.")
    out = []
    for item in layout:
        if not isinstance(item, dict) or not isinstance(item.get("i"), str) or len(item["i"]) > 60:
            raise HTTPException(status_code=400, detail="That layout isn't valid. Please reset the home page and try again.")
        try:
            out.append({"i": item["i"], **{k: max(0, min(48, int(item.get(k, 0)))) for k in ("x", "y", "w", "h")}})
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="That layout isn't valid. Please reset the home page and try again.")
    return out


@router.get("/me/home")
def my_home(kind: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    own_kind = _home_kind(db, tenant, current_user)
    can_set_defaults = has_permission(db, tenant, current_user, "platform.settings.configure")
    # Admins may open any home to arrange its company default; everyone else gets their own.
    shown = kind if (kind in HOME_KINDS and can_set_defaults) else own_kind
    service = _settings()(db)
    mine = service.get("ux.home_layout", _ctx(tenant, current_user)) if shown == own_kind else None
    mine = (mine or {}).get(shown) if isinstance(mine, dict) else None
    default = service.get(f"ux.home_default_{shown}", _ctx(tenant))
    return {
        "kind": shown,
        "own_kind": own_kind,
        "layout": mine or default or None,
        "layout_source": "mine" if mine else "company" if default else "built_in",
        "can_set_defaults": can_set_defaults,
    }


class LayoutIn(BaseModel):
    kind: str
    layout: list[dict]


@router.put("/me/home/layout")
def save_my_layout(payload: LayoutIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if payload.kind not in HOME_KINDS:
        raise HTTPException(status_code=400, detail="Unknown home page.")
    tenant = require_current_tenant()
    service = _settings()(db)
    current = service.get("ux.home_layout", _ctx(tenant, current_user))
    value = dict(current) if isinstance(current, dict) else {}
    value[payload.kind] = _clean_layout(payload.layout)
    service.set("ux.home_layout", value, scope_type="user", scope_id=current_user.id, actor=current_user.email, tenant=tenant)
    return {"ok": True}


@router.delete("/me/home/layout")
def reset_my_layout(kind: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    service = _settings()(db)
    current = service.get("ux.home_layout", _ctx(tenant, current_user))
    value = dict(current) if isinstance(current, dict) else {}
    value.pop(kind, None)
    service.set("ux.home_layout", value, scope_type="user", scope_id=current_user.id, actor=current_user.email, tenant=tenant)
    return {"ok": True}


@router.put("/home/defaults/{kind}")
def set_company_default(kind: str, payload: LayoutIn, db: Session = Depends(get_db),
                        current_user: User = Depends(require("platform.settings.configure"))):
    if kind not in HOME_KINDS:
        raise HTTPException(status_code=400, detail="Unknown home page.")
    tenant = require_current_tenant()
    _settings()(db).set(f"ux.home_default_{kind}", _clean_layout(payload.layout), scope_type="tenant", scope_id=None,
                        actor=current_user.email, tenant=tenant)
    return {"ok": True}


# ---- hiring flow (Sankey) ----

# Stage ladder: an application "reached" a stage if its current status is at or past it.
_LADDER = ["received", "screened", "shortlisted", "interview", "passed", "offer", "joined"]
_RANK = {
    "received": 0, "screened": 1, "hr_selected": 2, "on_hold": 2,
    "interview_scheduled": 3, "interview_selected": 4,
    "salary_ok": 4, "salary_above_band": 4, "salary_approved": 4,
    "bgv_requested": 5, "bgv_pending": 5, "bgv_cleared": 5, "offer_sent": 5,
    "onboarding_started": 5, "onboarding_completed": 6,
    # drop-outs: (rank reached, drop label)
}
_DROPS = {
    "hr_rejected": (1, "not_selected"), "interview_rejected": (3, "did_not_pass"),
    "salary_rejected": (4, "salary_declined"), "bgv_rejected": (5, "checks_failed"),
}


# Part 18.28: "interviewed" / "passed" come from real interview rows, never from the status
# label alone. Statuses at those two steps count only as far as the records prove.
_INTERVIEW_STEP = {"interview_scheduled", "interview_selected", "salary_ok", "salary_above_band", "salary_approved", "salary_rejected"}


def _counts_with_evidence(db: Session, q):
    """[(status, has_interview, has_selected_interview, n)] for an Application.status query."""
    from sqlalchemy import exists

    from app.models.application import Application
    from app.models.interview import Interview

    has_iv = exists().where(Interview.application_id == Application.id)
    has_sel = exists().where(Interview.application_id == Application.id, Interview.decision == "selected")
    rows = q.with_entities(Application.status, has_iv, has_sel, func.count()).group_by(Application.status, has_iv, has_sel).all()
    return [(status or "received", bool(iv), bool(sel), n) for status, iv, sel, n in rows]


def _proven_rank(status: str, rank: int, has_iv: bool, has_sel: bool, *, interview_rank: int, passed_rank: Optional[int]) -> int:
    if status not in _INTERVIEW_STEP:
        return rank
    if not has_iv:
        return min(rank, interview_rank - 1)
    if passed_rank is not None and not has_sel:
        return min(rank, passed_rank - 1)
    return rank


@router.get("/home/hiring-flow")
def hiring_flow(job_id: Optional[str] = None, db: Session = Depends(get_db),
                current_user: User = Depends(require("recruitment.pipeline.view"))):
    from app.models.application import Application

    tenant = require_current_tenant()
    q = db.query(Application.status, func.count()).filter(Application.tenant_id == tenant.tenant_id)
    if job_id:
        q = q.filter(Application.job_role_id == job_id)
    reached = [0] * len(_LADDER)
    drops: dict[tuple[int, str], int] = {}
    for status, has_iv, has_sel, n in _counts_with_evidence(db, q):
        if status in _DROPS:
            rank, label = _DROPS[status]
            for i in range(rank + 1):
                reached[i] += n
            drops[(rank, label)] = drops.get((rank, label), 0) + n
        else:
            rank = _proven_rank(status, _RANK.get(status, 0), has_iv, has_sel, interview_rank=3, passed_rank=4)
            for i in range(rank + 1):
                reached[i] += n

    nodes = [{"key": k} for k in _LADDER] + [{"key": label} for (_r, label) in sorted(drops)]
    index = {n["key"]: i for i, n in enumerate(nodes)}
    links = []
    for i in range(len(_LADDER) - 1):
        if reached[i + 1]:
            links.append({"source": i, "target": i + 1, "value": reached[i + 1]})
    for (rank, label), n in drops.items():
        # a drop at `rank` leaves from the stage AFTER the one it reached (e.g. rejected at screening)
        src = min(rank, len(_LADDER) - 1)
        links.append({"source": src, "target": index[label], "value": n})
    # "still here" = reached a stage but neither moved on nor dropped out there
    stage_totals = {_LADDER[i]: reached[i] for i in range(len(_LADDER))}
    return {"nodes": nodes, "links": links, "stages": stage_totals, "total": reached[0]}


# ---- hiring funnel (Part 17.2) ----

# Funnel stage -> the application statuses that count as "reached it" (at or past it), the
# statuses that mean "stopped right after it", and the status whose pipeline-stage name
# labels it. "Reached" is cumulative, so a candidate now at Offer also counts as Applied,
# Screened, Shortlisted and Interviewed.
_FUNNEL = (
    ("applied", "received"),
    ("screened", "screened"),
    ("shortlisted", "hr_selected"),
    ("interviewed", "interview_scheduled"),
    ("offered", "offer_sent"),
    ("joined", "onboarding_completed"),
)
_FUNNEL_RANK = {
    "received": 0, "screened": 1, "hr_rejected": 1,
    "hr_selected": 2, "on_hold": 2,
    "interview_scheduled": 3, "interview_selected": 3, "interview_rejected": 3,
    "salary_ok": 3, "salary_above_band": 3, "salary_approved": 3, "salary_rejected": 3,
    "bgv_requested": 3, "bgv_pending": 3, "bgv_cleared": 3, "bgv_rejected": 3,
    "offer_sent": 4, "onboarding_started": 4, "onboarding_completed": 5,
}
_FUNNEL_STOPPED = {"hr_rejected", "interview_rejected", "salary_rejected", "bgv_rejected"}
FUNNEL_PERIODS = {"7d": 7, "30d": 30, "90d": 90}


def _stage_names(db: Session, tenant, locale: str) -> dict[str, str]:
    """The company's own names for the funnel's anchor statuses, from its default pipeline."""
    from app.models.pipeline import PipelineStage, PipelineTemplate

    template = (db.query(PipelineTemplate).filter(PipelineTemplate.tenant_id == tenant.tenant_id)
                .order_by(PipelineTemplate.is_default.desc()).first())
    if template is None:
        return {}
    names = {}
    for stage in db.query(PipelineStage).filter(PipelineStage.tenant_id == tenant.tenant_id, PipelineStage.template_id == template.id).all():
        i18n = stage.name_i18n or {}
        name = i18n.get(locale) or i18n.get("en")
        # the seeded default names are just the status code in words ("Hr Selected") -- only
        # a name the company actually changed replaces the page's own plain wording
        if name and name.strip().lower() != (stage.code or "").replace("_", " ").lower():
            names[stage.code] = name
    return names


@router.get("/home/funnel")
def hiring_funnel(period: str = "30d", job_id: Optional[str] = None, locale: str = "en", db: Session = Depends(get_db),
                  current_user: User = Depends(require("recruitment.pipeline.view"))):
    """Horizontal funnel: per stage the applications that reached it, % of the stage before,
    and how many did not move on (split into "stopped here" = rejected, and "still here")."""
    from app.models.application import Application

    tenant = require_current_tenant()
    today = datetime.now(timezone.utc)
    if period == "year":
        since = datetime(today.year, 1, 1, tzinfo=timezone.utc)
    elif period in FUNNEL_PERIODS:
        since = today - timedelta(days=FUNNEL_PERIODS[period])
    else:
        raise HTTPException(status_code=400, detail="period must be one of 7d, 30d, 90d, year")
    q = (db.query(Application.status, func.count()).filter(Application.tenant_id == tenant.tenant_id, Application.created_at >= since))
    if job_id:
        q = q.filter(Application.job_role_id == job_id)
    reached = [0] * len(_FUNNEL)
    stopped = [0] * len(_FUNNEL)
    for status, has_iv, has_sel, n in _counts_with_evidence(db, q):
        rank = _proven_rank(status, _FUNNEL_RANK.get(status, 0), has_iv, has_sel, interview_rank=3, passed_rank=None)
        for i in range(rank + 1):
            reached[i] += n
        if status in _FUNNEL_STOPPED:
            stopped[rank] += n
    names = _stage_names(db, tenant, locale.split("-")[0])
    stages = []
    for i, (key, anchor) in enumerate(_FUNNEL):
        statuses = sorted(s for s, r in _FUNNEL_RANK.items() if r >= i)
        prev = reached[i - 1] if i else None
        not_next = reached[i] - reached[i + 1] if i + 1 < len(_FUNNEL) else 0
        stages.append({
            "key": key,
            "label": names.get(anchor),  # None -> the page's own wording
            "count": reached[i],
            "pct_of_previous": None if i == 0 else (round(100 * reached[i] / prev) if prev else 0),
            "statuses": statuses,
            # between this stage and the next one
            "drop": not_next,
            "stopped": stopped[i],
            "still_here": max(0, not_next - stopped[i]),
        })
    return {"period": period, "since": since.date().isoformat(), "job_id": job_id, "total": reached[0], "stages": stages}


# ---- heads-up alerts ----


@router.get("/home/alerts")
def home_alerts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    now = datetime.now(timezone.utc)
    alerts: list[dict] = []

    if has_permission(db, tenant, current_user, "helpdesk.ticket.view"):
        from app.models.service_desk import Ticket

        missed = db.query(func.count(Ticket.id)).filter(
            Ticket.tenant_id == tenant.tenant_id, Ticket.status.notin_(("resolved", "closed", "cancelled")),
            Ticket.resolution_due_at.isnot(None), Ticket.resolution_due_at < now,
        ).scalar() or 0
        if missed:
            alerts.append({"key": "helpdesk_missed", "tone": "coral", "emoji": "fire", "count": missed, "path": "/helpdesk"})

    if has_permission(db, tenant, current_user, "recruitment.pipeline.view"):
        from app.models.interview import Interview

        q = db.query(func.count(Interview.id)).filter(
            Interview.tenant_id == tenant.tenant_id, Interview.scheduled_at.isnot(None),
            Interview.scheduled_at < now - timedelta(hours=24), Interview.decision.is_(None), Interview.overall_rating.is_(None),
        )
        overdue = q.scalar() or 0
        if overdue:
            alerts.append({"key": "feedback_overdue", "tone": "sun", "emoji": "alarm_clock", "count": overdue, "path": "/interviews/list"})
        # fix 2026-10-04: a shortlisted candidate whose interview isn't being arranged -- never silent
        from app.interview_scheduling.automation import problems as _scheduling_problems

        for p in _scheduling_problems(db, tenant)[:10]:
            mailbox = p["kind"] == "mailbox"
            alerts.append({"key": "interview_not_scheduled", "tone": "coral", "emoji": "calendar", "count": 1, "path": f"/candidates/{p['application_id']}",
                           "name": p["name"], "job": p["job"], "reason": p["reason"], "kind": p["kind"],
                           "actions": ([{"key": "fix_mailbox", "path": "/settings/communication/mailboxes"}] if mailbox else
                                       [{"key": "add_availability", "path": "/interviews/interviewers"}])
                           + [{"key": "schedule_manually", "path": f"/candidates/{p['application_id']}?book=1"}]})
    else:
        from app.models.interview import Interview

        mine = db.query(func.count(Interview.id)).filter(
            Interview.tenant_id == tenant.tenant_id, Interview.interviewer_id == current_user.id,
            Interview.scheduled_at.isnot(None), Interview.scheduled_at < now, Interview.decision.is_(None), Interview.overall_rating.is_(None),
        ).scalar() or 0
        if mine:
            alerts.append({"key": "my_feedback_due", "tone": "sun", "emoji": "alarm_clock", "count": mine, "path": "/interviews/my"})

    if has_permission(db, tenant, current_user, "onboarding.preboarding.view"):
        from app.models.onboarding import PreboardingCase

        soon = date.today() + timedelta(days=3)
        not_ready = db.query(func.count(PreboardingCase.id)).filter(
            PreboardingCase.tenant_id == tenant.tenant_id, PreboardingCase.joining_date >= date.today(),
            PreboardingCase.joining_date <= soon, PreboardingCase.status.in_(("invited", "in_progress")),
        ).scalar() or 0
        if not_ready:
            alerts.append({"key": "joiners_not_ready", "tone": "coral", "emoji": "warning", "count": not_ready, "path": "/onboarding"})

    return {"alerts": alerts}


# ---- people by office (map) ----


@router.get("/home/people-by-office")
def people_by_office(db: Session = Depends(get_db), current_user: User = Depends(require("core_hr.employee.view"))):
    from app.models.core_hr import Employee, EmploymentRecord, Location

    tenant = require_current_tenant()
    rows = (
        db.query(Location.id, Location.name, Location.geo_lat, Location.geo_lng, func.count(func.distinct(EmploymentRecord.employee_id)))
        .join(EmploymentRecord, EmploymentRecord.location_id == Location.id)
        .join(Employee, Employee.id == EmploymentRecord.employee_id)
        .filter(Location.tenant_id == tenant.tenant_id, EmploymentRecord.effective_to.is_(None), Employee.status.in_(("active", "on_notice")))
        .group_by(Location.id, Location.name, Location.geo_lat, Location.geo_lng)
        .all()
    )

    def _num(v):
        try:
            return float(v) if v not in (None, "") else None
        except ValueError:
            return None

    return {"offices": [{"id": str(r[0]), "name": r[1], "lat": _num(r[2]), "lng": _num(r[3]), "count": r[4]} for r in rows]}


# ---- manager home: my team + my feedback to give ----


@router.get("/home/my-team")
def my_team(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """The caller's direct reports (their own org position, not a permission scope)."""
    from app.models.core_hr import Employee, EmploymentRecord
    from app.platform.iam.org_scope import direct_reportees, my_employee_id

    tenant = require_current_tenant()
    me = my_employee_id(db, tenant, current_user)
    ids = direct_reportees(db, tenant, me) if me else set()
    if not ids:
        return {"people": []}
    records = {r.employee_id: r for r in db.query(EmploymentRecord).filter(
        EmploymentRecord.tenant_id == tenant.tenant_id, EmploymentRecord.employee_id.in_(ids), EmploymentRecord.effective_to.is_(None))}
    people = []
    for e in db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id, Employee.id.in_(ids)).order_by(Employee.first_name):
        rec = records.get(e.id)
        people.append({"id": str(e.id), "name": " ".join(p for p in (e.first_name, e.last_name) if p), "status": e.status,
                       "designation": rec.designation if rec else None})
    return {"people": people}


@router.get("/home/my-feedback")
def my_feedback_due(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Interviews this user ran (or will run) that still have no scorecard -- oldest first."""
    from app.models.application import Application
    from app.models.candidate import Candidate
    from app.models.interview import Interview
    from app.scheduling.access import mine_filter

    tenant = require_current_tenant()
    rows = (
        db.query(Interview, Candidate.full_name)
        .outerjoin(Application, Application.id == Interview.application_id)
        .outerjoin(Candidate, Candidate.id == Application.candidate_id)
        .filter(Interview.tenant_id == tenant.tenant_id, mine_filter(db, current_user),  # Part 20.4: by email too
                Interview.decision.is_(None), Interview.overall_rating.is_(None), Interview.scheduled_at.isnot(None))
        .order_by(Interview.scheduled_at.asc()).limit(20).all()
    )
    now = datetime.now(timezone.utc)
    return {"items": [{
        "id": str(i.id), "application_id": str(i.application_id) if i.application_id else None, "candidate": name,
        "scheduled_at": i.scheduled_at.isoformat(), "meeting_link": i.meeting_link, "past": i.scheduled_at < now,
    } for i, name in rows]}


@router.get("/home/my-goals")
def my_goals(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """The caller's own goals, plus (for managers) their direct reports' goals."""
    from app.models.performance import Goal
    from app.performance.goals import goal_to_dict
    from app.platform.iam.org_scope import direct_reportees, my_employee_id

    tenant = require_current_tenant()
    me = my_employee_id(db, tenant, current_user)
    if me is None:
        return {"mine": [], "team": []}
    team_ids = direct_reportees(db, tenant, me)
    base = db.query(Goal).filter(Goal.tenant_id == tenant.tenant_id)
    mine = [goal_to_dict(g) for g in base.filter(Goal.owner_employee_id == me).order_by(Goal.created_at.asc()).limit(20)]
    team = [goal_to_dict(g) for g in base.filter(Goal.owner_employee_id.in_(team_ids)).order_by(Goal.created_at.asc()).limit(50)] if team_ids else []
    return {"mine": mine, "team": team}
