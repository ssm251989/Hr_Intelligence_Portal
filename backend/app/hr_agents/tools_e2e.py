"""Tools for the rest of the hiring-to-exit team: Interview, Salary, Documents & BGV, Offer,
Onboarding, Exit and HR policy agents (the Job and Screening tools are in tools.py).

Same rules as tools.py: permission first, the app's own services only, small dict results.
Anything that decides an outcome for a person or sends a decision to someone outside the
company becomes an APPROVAL CARD (`_card`) in My approvals; approvals.py runs the real
service when HR approves. Routine follow-ups (re-sending a form or an invite the candidate
already has, a reminder) run directly, because the screens let HR do them with one click and
nothing is decided by them.
"""

from datetime import date
from typing import Any, Optional

from app.hr_agents.tools import AgentContext, ToolSpec, _str_list, _uuid

# ------------------------------------------------------------------ helpers


def _application(ctx: AgentContext, application_id: str):
    from app.models.application import Application

    app = ctx.db.get(Application, _uuid(application_id, "application_id"))
    if app is None or app.tenant_id != ctx.tenant.tenant_id or app.removed_at is not None:
        raise LookupError("application not found")
    return app


def _names(ctx: AgentContext, app) -> dict:
    from app.models.candidate import Candidate
    from app.models.job_role import JobRole

    cand = ctx.db.get(Candidate, app.candidate_id)
    job = ctx.db.get(JobRole, app.job_role_id)
    return {"application_id": str(app.id), "candidate": getattr(cand, "full_name", None), "job": getattr(job, "title", None), "status": app.status}


def _card(ctx: AgentContext, *, kind: str, by_agent: str, title: str, payload: dict, permission: str,
          entity_type: Optional[str] = None, entity_id=None, agent_column: str = "recruiter") -> dict:
    """One approval card in My approvals. agent_suggestions.agent is limited by a DB check to
    the original agent names, so hiring cards use "recruiter" and people cards "onboarding";
    the card's payload names the team agent that proposed it."""
    from app.agents.service import suggest

    card = suggest(ctx.db, ctx.tenant, agent=agent_column, kind=kind, title=f"{title} ({by_agent.capitalize()} agent)",
                   payload={"by_agent": by_agent, **payload}, reviewer_permission=permission, entity_type=entity_type, entity_id=entity_id)
    ctx.suggestions.append({"id": str(card.id), "title": card.title})
    return {"approval_card_id": str(card.id), "next": "HR approves or rejects it in My approvals; nothing happens before that."}


def _by_status(ctx: AgentContext, statuses: tuple, job_id: Optional[str], limit: int = 30) -> list:
    from app.models.application import Application

    q = ctx.db.query(Application).filter(Application.tenant_id == ctx.tenant.tenant_id, Application.status.in_(statuses),
                                         Application.removed_at.is_(None))
    if job_id:
        q = q.filter(Application.job_role_id == _uuid(job_id, "job_id"))
    return q.order_by(Application.updated_at.asc()).limit(limit).all()


# ------------------------------------------------------------------ shared


def find_candidate(ctx: AgentContext, name: str) -> dict:
    from app.models.application import Application
    from app.models.candidate import Candidate

    name = (name or "").strip()
    if len(name) < 2:
        raise ValueError("give at least two letters of the name or the email")
    cands = (ctx.db.query(Candidate).filter(Candidate.tenant_id == ctx.tenant.tenant_id)
             .filter((Candidate.full_name.ilike(f"%{name}%")) | (Candidate.email.ilike(f"%{name}%"))).limit(10).all())
    out = []
    for c in cands:
        for app in ctx.db.query(Application).filter(Application.candidate_id == c.id, Application.removed_at.is_(None)).all():
            out.append(_names(ctx, app))
    return {"matches": out}


FIND_CANDIDATE = ToolSpec("find_candidate", "Find a candidate's applications (id, job, status) by part of the name or email.",
                          {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}, find_candidate, "recruitment.application.view")
_APP = {"type": "string", "description": "application_id from find_candidate or a queue"}
_JOB = {"type": "string", "description": "optional job_id to limit to one job"}


# ------------------------------------------------------------------ Interview agent (extra tools)


def interview_status(ctx: AgentContext, application_id: str) -> dict:
    from app.interview_scheduling import live_status

    app = _application(ctx, application_id)
    st = live_status.status(ctx.db, app)
    return {**_names(ctx, app), "scheduling": {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in st.items()
                                               if isinstance(v, (str, int, float, bool, type(None))) or hasattr(v, "isoformat")}}


def resend_interview_invite(ctx: AgentContext, application_id: str) -> dict:
    from app.interview_scheduling import live_status

    app = _application(ctx, application_id)
    out = live_status.resend(ctx.db, app, ctx.user)
    return {**_names(ctx, app), "result": {k: v for k, v in (out or {}).items() if isinstance(v, (str, int, float, bool, type(None)))}}


# ------------------------------------------------------------------ Salary agent


def salary_queue(ctx: AgentContext, job_id: Optional[str] = None) -> dict:
    rows = _by_status(ctx, ("interview_selected", "salary_above_band"), job_id)
    out = []
    for app in rows:
        chk = app.salary_check or {}
        out.append({**_names(ctx, app), "salary_state": chk.get("state"), "expected": chk.get("expected"), "band": [chk.get("band_min"), chk.get("band_max")],
                    "reasons": chk.get("reasons"), "auto_approvable": chk.get("auto_approvable"), "missing": chk.get("missing")})
    return {"waiting_for_salary": out}


def send_salary_form(ctx: AgentContext, application_id: str, reminder: bool = False) -> dict:
    from app.recruitment import salary_auto

    app = _application(ctx, application_id)
    out = salary_auto.send_form(ctx.db, ctx.tenant, app, actor=ctx.user.email, reminder=bool(reminder))
    return {**_names(ctx, app), "sent": bool(out.get("sent")), "note": None if out.get("sent") else "Email failed; share the link from the Salary screen."}


def run_salary_check(ctx: AgentContext, application_id: str) -> dict:
    """The same check as the Salary screen: band, hike %, budget. Inside every limit the app's own
    rule approves it (as it does without agents); otherwise it waits for HR."""
    from app.recruitment import salary_auto

    app = _application(ctx, application_id)
    result = salary_auto.check(ctx.db, ctx.tenant, app, actor=ctx.user.email)
    ctx.db.refresh(app)
    return {**_names(ctx, app), "check": {k: v for k, v in (result or {}).items() if isinstance(v, (str, int, float, bool, type(None), list))}}


def propose_salary_decision(ctx: AgentContext, application_id: str, decision: str, amount: Optional[float] = None, reason: Optional[str] = None) -> dict:
    app = _application(ctx, application_id)
    if decision not in ("approve", "counter", "reject"):
        raise ValueError("decision is approve, counter or reject")
    if app.status not in ("salary_above_band", "interview_selected", "salary_ok"):
        raise ValueError(f"no salary decision is due (status is '{app.status}')")
    if decision == "reject" and not reason:
        raise ValueError("a rejection needs a reason HR can read")
    n = _names(ctx, app)
    return _card(ctx, kind="agent_salary_decision", by_agent="salary", title=f"Salary {decision} for {n['candidate']}",
                 payload={**n, "decision": decision, "amount": amount, "reason": reason, "salary_check": app.salary_check or {}},
                 permission="recruitment.salary.edit", entity_type="application", entity_id=app.id)


# ------------------------------------------------------------------ Documents & BGV agent


def bgv_queue(ctx: AgentContext, job_id: Optional[str] = None) -> dict:
    from app.bgv import vendors

    out = []
    for app in _by_status(ctx, ("salary_approved", "bgv_requested", "bgv_pending"), job_id):
        a = vendors.current(ctx.db, app.id)
        out.append({**_names(ctx, app), "stage": "documents" if app.status == "salary_approved" else "bgv",
                    "vendor_assigned": bool(a), "vendor_status": getattr(a, "status", None)})
    return {"documents_and_bgv": out}


def documents_status(ctx: AgentContext, application_id: str) -> dict:
    from app.recruitment import joining_docs

    app = _application(ctx, application_id)
    st = joining_docs.status(ctx.db, ctx.tenant, app)
    items = [{"code": i.get("code"), "name": i.get("label"), "received": i["received"], "approved": i["approved"],
              "check": i.get("level")} for i in st["items"]]
    return {**_names(ctx, app), "documents": items, "missing": st["missing"], "all_received": st["all_received"],
            "all_approved": st["all_approved"], "red_flags": st["reds"], "amber_flags": st["ambers"],
            "cross_check": joining_docs.cross_check(ctx.db, ctx.tenant, app)}


def send_documents_form(ctx: AgentContext, application_id: str, reminder: bool = False) -> dict:
    from app.recruitment import joining_docs

    app = _application(ctx, application_id)
    out = joining_docs.send_form(ctx.db, ctx.tenant, app, actor=ctx.user.email, reminder=bool(reminder))
    return {**_names(ctx, app), "sent": bool(out.get("sent"))}


def list_bgv_vendors(ctx: AgentContext) -> dict:
    from app.bgv import vendors

    return {"vendors": [{k: v for k, v in r.items() if k != "email"} for r in vendors.vendors(ctx.db, ctx.tenant)]}


def propose_documents_approval(ctx: AgentContext, application_id: str, note: Optional[str] = None) -> dict:
    from app.recruitment import joining_docs

    app = _application(ctx, application_id)
    st = joining_docs.status(ctx.db, ctx.tenant, app)
    if not st["all_received"]:
        raise ValueError(f"documents still missing: {', '.join(st['missing'])}")
    n = _names(ctx, app)
    return _card(ctx, kind="agent_documents_approve", by_agent="bgv", title=f"Approve documents of {n['candidate']} and start BGV",
                 payload={**n, "note": note, "red_flags": st["reds"], "amber_flags": st["ambers"]},
                 permission="recruitment.bgv.edit", entity_type="application", entity_id=app.id)


def propose_vendor_assignment(ctx: AgentContext, application_id: str, agency_id: str, checks: Any, due_date: Optional[str] = None) -> dict:
    from app.bgv import vendors

    app = _application(ctx, application_id)
    if app.status not in ("bgv_requested", "bgv_pending"):
        raise ValueError(f"a vendor can be assigned once BGV has started (status is '{app.status}')")
    vendor = next((v for v in vendors.vendors(ctx.db, ctx.tenant) if v["id"] == str(_uuid(agency_id, "agency_id"))), None)
    if vendor is None:
        raise LookupError("BGV vendor not found (use list_bgv_vendors)")
    if due_date:
        date.fromisoformat(due_date)
    n = _names(ctx, app)
    return _card(ctx, kind="agent_bgv_assign", by_agent="bgv", title=f"Send {n['candidate']}'s BGV to {vendor['name']}",
                 payload={**n, "agency_id": vendor["id"], "vendor": vendor["name"], "checks": _str_list(checks) or [], "due_date": due_date},
                 permission="recruitment.bgv.edit", entity_type="application", entity_id=app.id)


def propose_bgv_decision(ctx: AgentContext, application_id: str, decision: str, note: Optional[str] = None, reason: Optional[str] = None) -> dict:
    app = _application(ctx, application_id)
    if decision not in ("passed", "discrepancy", "failed"):
        raise ValueError("decision is passed, discrepancy or failed")
    if app.status not in ("bgv_requested", "bgv_pending"):
        raise ValueError(f"no BGV decision is due (status is '{app.status}')")
    if decision == "discrepancy" and not note:
        raise ValueError("a discrepancy needs a note")
    if decision == "failed" and not reason:
        raise ValueError("a failed BGV needs a reason")
    n = _names(ctx, app)
    return _card(ctx, kind="agent_bgv_decision", by_agent="bgv", title=f"BGV {decision} for {n['candidate']}",
                 payload={**n, "decision": decision, "note": note, "reason": reason},
                 permission="recruitment.bgv.edit", entity_type="application", entity_id=app.id)


# ------------------------------------------------------------------ Offer agent


def _offer_for(ctx: AgentContext, app):
    from app.models.offer import Offer

    return ctx.db.query(Offer).filter(Offer.application_id == app.id).order_by(Offer.created_at.desc()).first()


def offer_queue(ctx: AgentContext, job_id: Optional[str] = None) -> dict:
    from app.recruitment import joining_dates

    out = []
    for app in _by_status(ctx, ("bgv_cleared", "offer_sent"), job_id):
        offer = _offer_for(ctx, app)
        out.append({**_names(ctx, app), "joining_dates": joining_dates.info(app), "offer_signed": bool(getattr(offer, "signed", False)) if offer else None})
    return {"offers": out}


def offer_status(ctx: AgentContext, application_id: str) -> dict:
    from app.offers import revisions
    from app.recruitment import joining_dates

    app = _application(ctx, application_id)
    offer = _offer_for(ctx, app)
    summary = revisions.summary(ctx.db, ctx.tenant, offer, ctx.user) if offer else None
    keep = ("status", "signed", "sent_count", "last_sent_at", "can_resend", "resend_available_at")
    return {**_names(ctx, app), "joining_dates": joining_dates.info(app),
            "offer": {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in (summary or {}).items() if k in keep} if summary else None}


def propose_joining_dates(ctx: AgentContext, application_id: str, dates: Any, note: Optional[str] = None) -> dict:
    app = _application(ctx, application_id)
    if app.status != "bgv_cleared":
        raise ValueError(f"joining dates are offered after BGV is cleared (status is '{app.status}')")
    picked = _str_list(dates) or []
    if len(picked) != 3 or len(set(picked)) != 3:
        raise ValueError("give exactly three different dates (YYYY-MM-DD)")
    for d in picked:
        if date.fromisoformat(d) <= date.today():
            raise ValueError(f"{d} is not in the future")
    n = _names(ctx, app)
    return _card(ctx, kind="agent_joining_dates", by_agent="offer", title=f"Offer joining dates to {n['candidate']}",
                 payload={**n, "dates": picked, "note": note}, permission="recruitment.offer.edit", entity_type="application", entity_id=app.id)


def resend_offer(ctx: AgentContext, application_id: str) -> dict:
    from app.offers import revisions

    app = _application(ctx, application_id)
    offer = _offer_for(ctx, app)
    if offer is None:
        raise ValueError("no offer has been sent yet")
    out = revisions.resend(ctx.db, ctx.tenant, offer, actor=ctx.user.email)
    return {**_names(ctx, app), "resent": True, "result": {k: v for k, v in (out or {}).items() if isinstance(v, (str, int, float, bool, type(None)))}}


# ------------------------------------------------------------------ Onboarding agent


def onboarding_board(ctx: AgentContext) -> dict:
    from app.models.onboarding import PreboardingCase
    from app.onboarding import joiner_stage
    from app.onboarding.portal import PreboardingPortal

    portal = PreboardingPortal(ctx.db, ctx.tenant)
    out = []
    for case in ctx.db.query(PreboardingCase).filter(PreboardingCase.tenant_id == ctx.tenant.tenant_id).order_by(PreboardingCase.joining_date).limit(60).all():
        st = joiner_stage.stage(ctx.db, case)
        if st == "closed":
            continue
        try:
            ready = portal.readiness(case)
        except Exception:  # noqa: BLE001 -- readiness is a nice-to-have in this summary
            ready = {}
        app = None
        if case.application_id:
            from app.models.application import Application

            app = ctx.db.get(Application, case.application_id)
        out.append({"case_id": str(case.id), **(_names(ctx, app) if app else {"candidate": case.email}), "joining_date": case.joining_date.isoformat(),
                    "stage": st, "actions_now": joiner_stage.allowed_actions(ctx.db, case),
                    "ready": {k: v for k, v in ready.items() if isinstance(v, (bool, int, float, str))}})
    return {"joiners": out[:30]}


def pending_employee_cards(ctx: AgentContext) -> dict:
    from app.employees import creation

    return {"employee_cards": [{k: v for k, v in r.items() if isinstance(v, (str, int, float, bool, type(None)))} for r in creation.pending(ctx.db, ctx.tenant)][:20]}


def propose_mark_joined(ctx: AgentContext, case_id: str) -> dict:
    from app.models.onboarding import PreboardingCase
    from app.onboarding import joiner_stage

    case = ctx.db.get(PreboardingCase, _uuid(case_id, "case_id"))
    if case is None or case.tenant_id != ctx.tenant.tenant_id:
        raise LookupError("joiner not found (use onboarding_board)")
    if "mark_joined" not in joiner_stage.allowed_actions(ctx.db, case):
        raise ValueError(f"'joined' can be recorded on or after the joining date (stage is {joiner_stage.stage(ctx.db, case)})")
    return _card(ctx, kind="agent_mark_joined", by_agent="onboarding", title=f"Confirm {case.email} joined on {case.joining_date.isoformat()}",
                 payload={"case_id": str(case.id), "email": case.email, "joining_date": case.joining_date.isoformat()},
                 permission="onboarding.preboarding.approve", entity_type="preboarding_case", entity_id=case.id, agent_column="onboarding")


# ------------------------------------------------------------------ Exit agent

_OPEN_EXIT = ("submitted", "retention", "approved", "clearance")


def _separation(ctx: AgentContext, separation_id: str):
    from app.models.service_desk import Separation

    s = ctx.db.get(Separation, _uuid(separation_id, "separation_id"))
    if s is None or s.tenant_id != ctx.tenant.tenant_id:
        raise LookupError("exit not found (use open_exits)")
    return s


def _employee_name(ctx: AgentContext, employee_id) -> Optional[str]:
    from app.models.core_hr import Employee

    e = ctx.db.get(Employee, employee_id)
    return " ".join(x for x in (getattr(e, "first_name", None), getattr(e, "last_name", None)) if x) or None


def open_exits(ctx: AgentContext) -> dict:
    from app.employees import exit_checklist
    from app.models.service_desk import Separation

    rows = (ctx.db.query(Separation).filter(Separation.tenant_id == ctx.tenant.tenant_id, Separation.status.in_(_OPEN_EXIT))
            .order_by(Separation.submitted_on).limit(30).all())
    return {"exits": [{"separation_id": str(s.id), "employee": _employee_name(ctx, s.employee_id), "status": s.status, "type": s.separation_type,
                       "last_working_day": s.approved_lwd.isoformat() if s.approved_lwd else None,
                       "checklist_pending": len(exit_checklist.pending(ctx.db, s))} for s in rows]}


def exit_detail(ctx: AgentContext, separation_id: str) -> dict:
    from app.employees import exit_checklist, exit_interview
    from app.service_desk import separations

    s = _separation(ctx, separation_id)
    return {"employee": _employee_name(ctx, s.employee_id), **separations.exit_summary(ctx.db, s),
            "pending_items": [getattr(i, "title", None) or getattr(i, "code", None) for i in exit_checklist.pending(ctx.db, s)][:20],
            "relieving_blockers": separations.relieving_blockers(ctx.db, s), "exit_interview": exit_interview.status_of(s)}


def send_exit_interview_reminder(ctx: AgentContext, separation_id: str) -> dict:
    from app.employees import exit_interview

    s = _separation(ctx, separation_id)
    out = exit_interview.send_reminder(ctx.db, ctx.tenant, s, actor=ctx.user.email)
    return {"employee": _employee_name(ctx, s.employee_id), "result": {k: v for k, v in (out or {}).items() if isinstance(v, (str, int, float, bool, type(None)))}}


def propose_exit_letters(ctx: AgentContext, separation_id: str) -> dict:
    from app.service_desk import separations

    s = _separation(ctx, separation_id)
    blockers = separations.relieving_blockers(ctx.db, s)
    if blockers:
        raise ValueError(f"letters wait for: {', '.join(map(str, blockers))[:300]}")
    name = _employee_name(ctx, s.employee_id)
    return _card(ctx, kind="agent_exit_letters", by_agent="exit", title=f"Issue relieving and experience letters to {name}",
                 payload={"separation_id": str(s.id), "employee": name, "last_working_day": s.approved_lwd.isoformat() if s.approved_lwd else None},
                 permission="separation.case.approve", entity_type="separation", entity_id=s.id, agent_column="onboarding")


# ------------------------------------------------------------------ HR policy agent


def search_handbook(ctx: AgentContext, question: str) -> dict:
    from app.copilot import retrieval
    from app.platform.iam.roles import role_names_for

    hits = retrieval.search(ctx.db, ctx.tenant, question, role_names=role_names_for(ctx.db, ctx.tenant, ctx.user))
    return {"passages": [{"source": f"{h.document_title}{' - ' + h.heading if h.heading else ''}", "text": h.text[:1200]} for h in hits]}


# ------------------------------------------------------------------ catalog

INTERVIEW_EXTRA = (
    ToolSpec("interview_status", "Where interview scheduling stands for one candidate (sent, waiting, booked, interviewer).",
             {"type": "object", "required": ["application_id"], "properties": {"application_id": _APP}}, interview_status, "recruitment.interview.view"),
    ToolSpec("resend_interview_invite", "Send the slot emails again to whoever has not answered.",
             {"type": "object", "required": ["application_id"], "properties": {"application_id": _APP}}, resend_interview_invite, "recruitment.interview.edit"),
    FIND_CANDIDATE,
)

SALARY_TOOLS = (
    ToolSpec("salary_queue", "Candidates selected in interview who wait for the salary step, with band, expected CTC and hike %.",
             {"type": "object", "properties": {"job_id": _JOB}}, salary_queue, "recruitment.application.view"),
    ToolSpec("send_salary_form", "Email the candidate the salary details form (or a reminder).",
             {"type": "object", "required": ["application_id"], "properties": {"application_id": _APP, "reminder": {"type": "boolean"}}}, send_salary_form, "recruitment.application.edit"),
    ToolSpec("run_salary_check", "Run the salary check (band, hike %, budget). Within all limits the app's rule approves; otherwise HR decides.",
             {"type": "object", "required": ["application_id"], "properties": {"application_id": _APP}}, run_salary_check, "recruitment.application.view"),
    ToolSpec("propose_salary_decision", "Propose approve / counter / reject for a salary that needs HR. Creates an approval card.",
             {"type": "object", "required": ["application_id", "decision"], "properties": {
                 "application_id": _APP, "decision": {"type": "string", "enum": ["approve", "counter", "reject"]},
                 "amount": {"type": "number", "description": "annual CTC for approve/counter"}, "reason": {"type": "string"}}},
             propose_salary_decision, "recruitment.application.view"),
    FIND_CANDIDATE,
)

BGV_TOOLS = (
    ToolSpec("bgv_queue", "Candidates in the documents step or in BGV, with vendor status.",
             {"type": "object", "properties": {"job_id": _JOB}}, bgv_queue, "recruitment.bgv.view"),
    ToolSpec("documents_status", "One candidate's joining documents: received, approved, AI check flags and name/DOB cross-check.",
             {"type": "object", "required": ["application_id"], "properties": {"application_id": _APP}}, documents_status, "recruitment.bgv.view"),
    ToolSpec("send_documents_form", "Email the candidate the documents upload form (or a reminder).",
             {"type": "object", "required": ["application_id"], "properties": {"application_id": _APP, "reminder": {"type": "boolean"}}}, send_documents_form, "recruitment.bgv.edit"),
    ToolSpec("list_bgv_vendors", "Active BGV vendors with the checks they do and their turnaround.", {"type": "object", "properties": {}}, list_bgv_vendors, "recruitment.bgv.view"),
    ToolSpec("propose_documents_approval", "Propose approving all documents (moves the candidate to BGV). Creates an approval card.",
             {"type": "object", "required": ["application_id"], "properties": {"application_id": _APP, "note": {"type": "string"}}}, propose_documents_approval, "recruitment.bgv.view"),
    ToolSpec("propose_vendor_assignment", "Propose sending the BGV to a vendor (shares documents outside the company). Creates an approval card.",
             {"type": "object", "required": ["application_id", "agency_id", "checks"], "properties": {
                 "application_id": _APP, "agency_id": {"type": "string"}, "checks": {"type": "array", "items": {"type": "string"}},
                 "due_date": {"type": "string", "description": "YYYY-MM-DD"}}}, propose_vendor_assignment, "recruitment.bgv.view"),
    ToolSpec("propose_bgv_decision", "Propose the BGV result (passed / discrepancy with note / failed with reason). Creates an approval card.",
             {"type": "object", "required": ["application_id", "decision"], "properties": {
                 "application_id": _APP, "decision": {"type": "string", "enum": ["passed", "discrepancy", "failed"]},
                 "note": {"type": "string"}, "reason": {"type": "string"}}}, propose_bgv_decision, "recruitment.bgv.view"),
    FIND_CANDIDATE,
)

OFFER_TOOLS = (
    ToolSpec("offer_queue", "Candidates with BGV cleared (joining dates due) or an offer sent (signed or not).",
             {"type": "object", "properties": {"job_id": _JOB}}, offer_queue, "recruitment.offer.view"),
    ToolSpec("offer_status", "Joining dates and offer signing status for one candidate.",
             {"type": "object", "required": ["application_id"], "properties": {"application_id": _APP}}, offer_status, "recruitment.offer.view"),
    ToolSpec("propose_joining_dates", "Propose three joining dates for the candidate to choose from (then the offer goes out). Creates an approval card.",
             {"type": "object", "required": ["application_id", "dates"], "properties": {
                 "application_id": _APP, "dates": {"type": "array", "items": {"type": "string"}, "description": "three YYYY-MM-DD dates"},
                 "note": {"type": "string"}}}, propose_joining_dates, "recruitment.offer.view"),
    ToolSpec("resend_offer", "Email the same unsigned offer again (respects the resend wait time).",
             {"type": "object", "required": ["application_id"], "properties": {"application_id": _APP}}, resend_offer, "recruitment.offer.edit"),
    FIND_CANDIDATE,
)

ONBOARDING_TOOLS = (
    ToolSpec("onboarding_board", "New joiners: joining date, stage, what can be done now, portal readiness.",
             {"type": "object", "properties": {}}, onboarding_board, "onboarding.preboarding.view"),
    ToolSpec("pending_employee_cards", "Employee records prepared after joining that wait for HR approval.",
             {"type": "object", "properties": {}}, pending_employee_cards, "core_hr.employee.view"),
    ToolSpec("propose_mark_joined", "Propose recording that a joiner has joined (creates the employee record after approval). Creates an approval card.",
             {"type": "object", "required": ["case_id"], "properties": {"case_id": {"type": "string", "description": "case_id from onboarding_board"}}},
             propose_mark_joined, "onboarding.preboarding.view"),
)

EXIT_TOOLS = (
    ToolSpec("open_exits", "Open resignations and exits with status, last working day and pending checklist items.",
             {"type": "object", "properties": {}}, open_exits, "separation.case.view"),
    ToolSpec("exit_detail", "One exit: notice, last working day, pending checklist items, what blocks the letters, exit interview status.",
             {"type": "object", "required": ["separation_id"], "properties": {"separation_id": {"type": "string"}}}, exit_detail, "separation.case.view"),
    ToolSpec("send_exit_interview_reminder", "Remind the leaver to fill in the exit interview.",
             {"type": "object", "required": ["separation_id"], "properties": {"separation_id": {"type": "string"}}}, send_exit_interview_reminder,
             "separation_hr.exit_interview.edit"),
    ToolSpec("propose_exit_letters", "Propose issuing the relieving and experience letters (only when nothing blocks them). Creates an approval card.",
             {"type": "object", "required": ["separation_id"], "properties": {"separation_id": {"type": "string"}}}, propose_exit_letters, "separation.case.view"),
)

POLICY_TOOLS = (
    ToolSpec("search_handbook", "Search the company's HR policies and handbook. Answer only from the passages and name the source.",
             {"type": "object", "required": ["question"], "properties": {"question": {"type": "string"}}}, search_handbook, None),
)
