"""hrctl demo seed|clear -- clearly marked sample records for reviewing the Part 15 screens
(docs/PART15_FULL_PROMPT.txt STEP 15.8).

    python -m hrctl.demo seed  --tenant <slug> [--demo-categories]
    python -m hrctl.demo clear --tenant <slug>            # dry run: report only
    python -m hrctl.demo clear --tenant <slug> --yes      # actually remove

Every record this creates is a *demo record*: its visible name starts with "Demo - "
(departments, locations, employees' first name, goals, the review cycle, tickets, assets, the
agency), or it belongs solely to one (employment records, joiners' onboarding cases/plans,
goal check-ins, reviews of the demo cycle, asset allocations, the separation + its clearance
items and workflow, agency jobs/members). Seed is idempotent -- each record is looked up by
its demo name first.

Real configuration is never changed. The tenant's ticket / asset categories are used if they
exist; if there are none, tickets and assets are skipped unless `--demo-categories` is given,
which adds categories labelled "Demo - ..." (codes `demo_*`) that clear removes again.

Clear only ever selects by that prefix + ownership. Before deleting, every foreign key in the
schema is scanned: if any NON-demo row points at a demo record, that record (and whatever it
needs) is kept and listed as "kept, in use by real data". Each root is deleted in its own
savepoint, so an unexpected constraint error skips that root instead of failing the run.
"""

from datetime import date, timedelta

PREFIX = "Demo - "
ACTOR = "hrctl-demo"

DEPARTMENTS = ("Demo - Engineering", "Demo - People Team")
LOCATIONS = (
    ("Demo - Chennai office", "13.0827", "80.2707", "Tamil Nadu"),
    ("Demo - Bengaluru office", "12.9716", "77.5946", "Karnataka"),
)
# key, first name, last name, designation, department idx, location idx, manager key, skills, years in company
EMPLOYEES = (
    ("priya", "Priya", "Raman", "Head of Engineering", 0, 0, None, ["Leadership", "System design"], 4),
    ("arjun", "Arjun", "Mehta", "Engineering Manager", 0, 1, "priya", ["People management", "Python"], 3),
    ("kavya", "Kavya", "Iyer", "Senior Software Engineer", 0, 0, "arjun", ["Python", "PostgreSQL", "React"], 2),
    ("rahul", "Rahul", "Nair", "Software Engineer", 0, 1, "arjun", ["TypeScript", "React"], 1),
    ("meera", "Meera", "Das", "HR Lead", 1, 0, "priya", ["Employee relations", "Hiring"], 3),
    ("sameer", "Sameer", "Khan", "HR Executive", 1, 1, "meera", ["Onboarding", "Payroll basics"], 1),
)
JOINERS = (
    ("Ananya", "Rao", "demo.ananya.rao@example.com", 3, "Software Engineer", "kavya"),
    ("Vikram", "Singh", "demo.vikram.singh@example.com", 10, "HR Executive", "sameer"),
)
TICKETS = (
    ("kavya", "Demo - Laptop is not charging", "It stopped charging this morning, even with a different cable.", "high"),
    ("rahul", "Demo - Need access to the design folder", "Please add me to the shared design drive.", "medium"),
    ("sameer", "Demo - Question about my payslip", "The travel allowance looks different this month.", "low"),
)
ASSETS = (("DEMO-LAP-01", "Demo - Laptop 01", "kavya"), ("DEMO-LAP-02", "Demo - Laptop 02", None), ("DEMO-MON-01", "Demo - Monitor 01", None))
AGENCY_NAME = "Demo - Bright Talent Partners"
CYCLE_NAME = "Demo - 2026 annual review"
DEMO_CATEGORIES = {"ticket_category": ("demo_it", "Demo - IT help"), "asset_category": ("demo_laptop", "Demo - Laptops")}


def _full(first: str) -> str:
    return f"{PREFIX}{first}"


# ------------------------------------------------------------------ seed

def seed(db, tenant, *, demo_categories: bool = False) -> dict:
    from app.core_hr.employees import create_employee
    from app.models.agency import AgencyJobAssignment, RecruitmentAgency
    from app.models.core_hr import Department, Employee, EmploymentRecord, Location
    from app.models.job_role import JobRole
    from app.models.metadata import MasterValue
    from app.models.onboarding import OnboardingPlan, OnboardingPlanTemplate, PreboardingCase
    from app.models.performance import Goal, GoalCheckin, ReviewCycle
    from app.models.service_desk import Asset, Separation, Ticket
    from app.onboarding.plans import generate_plan
    from app.onboarding.portal import PreboardingPortal
    from app.performance.goals import check_in, create_goal
    from app.performance.reviews import _ensure_review, create_cycle
    from app.service_desk import assets as assets_service
    from app.service_desk import separations as separations_service
    from app.service_desk.tickets import create_ticket

    tid = tenant.tenant_id
    today = date.today()
    created: dict[str, int] = {}
    skipped: list[str] = []

    def bump(key: str) -> None:
        created[key] = created.get(key, 0) + 1

    # -- org
    depts = []
    for name in DEPARTMENTS:
        row = db.query(Department).filter(Department.tenant_id == tid, Department.name == name).first()
        if row is None:
            row = Department(tenant_id=tid, name=name)
            db.add(row)
            db.commit()
            bump("departments")
        depts.append(row)
    locs = []
    for name, lat, lng, state in LOCATIONS:
        row = db.query(Location).filter(Location.tenant_id == tid, Location.name == name).first()
        if row is None:
            row = Location(tenant_id=tid, name=name, geo_lat=lat, geo_lng=lng, state=state, address=name.replace(PREFIX, "") + ", India")
            db.add(row)
            db.commit()
            bump("locations")
        locs.append(row)

    # -- employees + a hire record each (manager tree)
    people: dict[str, Employee] = {}
    for key, first, last, designation, d, l, manager, skills, years in EMPLOYEES:
        emp = db.query(Employee).filter(Employee.tenant_id == tid, Employee.first_name == _full(first), Employee.last_name == last).first()
        if emp is None:
            emp = create_employee(db, tenant, first_name=_full(first), last_name=last, status="active",
                                  personal_email=f"demo.{first.lower()}.{last.lower()}@example.com",
                                  skills_json=[{"skill": s, "proficiency": "advanced" if i == 0 else "intermediate", "source": "manager"} for i, s in enumerate(skills)])
            bump("employees")
        people[key] = emp
    for key, first, last, designation, d, l, manager, skills, years in EMPLOYEES:
        emp = people[key]
        if db.query(EmploymentRecord).filter(EmploymentRecord.tenant_id == tid, EmploymentRecord.employee_id == emp.id).first() is None:
            db.add(EmploymentRecord(
                tenant_id=tid, employee_id=emp.id, effective_from=today - timedelta(days=365 * years + 30), event_type="hire",
                department_id=depts[d].id, location_id=locs[l].id, designation=designation, employment_type="full_time",
                manager_employee_id=people[manager].id if manager else None, work_mode="hybrid", notice_period_days=60,
                created_by=ACTOR,
            ))
            db.commit()
            bump("employment_records")

    # -- upcoming joiners (pre-hire employee + onboarding case, plan if a template exists)
    template = db.query(OnboardingPlanTemplate).filter(OnboardingPlanTemplate.tenant_id == tid).order_by(OnboardingPlanTemplate.code).first()
    portal = PreboardingPortal(db, tenant)
    for first, last, email, in_days, designation, buddy in JOINERS:
        case = (db.query(PreboardingCase).join(Employee, Employee.id == PreboardingCase.employee_id)
                .filter(PreboardingCase.tenant_id == tid, Employee.first_name == _full(first)).first())
        if case is None:
            b = people[buddy]
            case = portal.create_case(
                email=email, joining_date=today + timedelta(days=in_days), first_name=_full(first), last_name=last,
                attributes={"designation": designation}, created_by=ACTOR,
                welcome_content={
                    "message": f"We're so happy you're joining us, {first}! Here is everything for your first day.",
                    "buddy": {"name": f"{b.first_name} {b.last_name}", "title": "Your buddy for the first month", "note": "Ask me anything - no question is too small."},
                    "agenda": [{"time": "09:30", "title": "Welcome coffee with the team", "emoji": "coffee"},
                               {"time": "11:00", "title": "Laptop and accounts set-up", "emoji": "laptop"},
                               {"time": "13:00", "title": "Lunch with your buddy", "emoji": "bento"}],
                },
            )
            bump("onboarding_cases")
        if template is not None and db.query(OnboardingPlan).filter(OnboardingPlan.tenant_id == tid, OnboardingPlan.case_id == case.id).first() is None:
            generate_plan(db, tenant, case, template)
            bump("onboarding_plans")
    if template is None:
        skipped.append("onboarding plans/tasks: no onboarding plan template exists")

    # -- performance: cycle, company > team > personal goals, check-ins, reviews
    cycle = db.query(ReviewCycle).filter(ReviewCycle.tenant_id == tid, ReviewCycle.name == CYCLE_NAME).first()
    if cycle is None:
        cycle = create_cycle(
            db, tenant, name=CYCLE_NAME, cycle_type="annual", period_start=date(today.year, 1, 1), period_end=date(today.year, 12, 31),
            stages=[{"stage": "self", "weight": 30, "due_date": (today + timedelta(days=21)).isoformat()},
                    {"stage": "manager", "weight": 70, "due_date": (today + timedelta(days=35)).isoformat()}],
            sections=[{"key": "goals", "weight": 60},
                      {"key": "competencies", "weight": 40, "items": [{"key": "ownership", "label": "Takes ownership"}, {"key": "teamwork", "label": "Works well with others"}]}],
        )
        cycle.status = "active"
        db.commit()
        bump("review_cycles")
    manager_of = {k: m for k, _f, _l, _d, _di, _li, m, _s, _y in EMPLOYEES}
    added = 0
    for key, emp in people.items():
        added += _ensure_review(db, tenant, cycle, emp.id, emp.id, "self")
        if manager_of[key]:
            added += _ensure_review(db, tenant, cycle, emp.id, people[manager_of[key]].id, "manager")
    db.commit()
    if added:
        created["reviews"] = created.get("reviews", 0) + added

    def goal(title: str, **kw) -> Goal:
        row = db.query(Goal).filter(Goal.tenant_id == tid, Goal.title == title).first()
        if row is None:
            row = create_goal(db, tenant, title=title, cycle_id=cycle.id, due_date=date(today.year, 12, 31), **kw)
            row.status = "active"
            db.commit()
            bump("goals")
        return row

    company = goal("Demo - Make every new joiner productive in 30 days", level="company", description="Our company goal for this year.")
    team = goal("Demo - Ship the new onboarding experience", level="team", parent_goal_id=company.id, department_id=depts[0].id,
                owner_employee_id=people["arjun"].id, weightage=40)
    mine = [goal("Demo - Build the welcome portal pages", level="individual", parent_goal_id=team.id, owner_employee_id=people["kavya"].id, weightage=50),
            goal("Demo - Mentor two new joiners", level="individual", parent_goal_id=team.id, owner_employee_id=people["rahul"].id, weightage=30)]
    goal("Demo - Cut time-to-hire to 30 days", level="team", parent_goal_id=company.id, department_id=depts[1].id, owner_employee_id=people["meera"].id, weightage=40)
    for g, pct, note in ((mine[0], 45, "Welcome page and progress bar are done."), (mine[1], 25, "Met both joiners, weekly chats booked."), (team, 35, "On track for the launch.")):
        if db.query(GoalCheckin).filter(GoalCheckin.tenant_id == tid, GoalCheckin.goal_id == g.id).first() is None:
            check_in(db, tenant, g, progress_pct=pct, confidence=4, comment=note, actor=ACTOR)
            bump("goal_checkins")

    # -- categories (existing, or opt-in demo ones)
    def category(type_code: str) -> str | None:
        existing = (db.query(MasterValue).filter(MasterValue.tenant_id == tid, MasterValue.type_code == type_code, MasterValue.is_active.is_(True))
                    .order_by(MasterValue.sort, MasterValue.code).first())
        if existing is not None:
            return existing.code
        if not demo_categories:
            return None
        code, label = DEMO_CATEGORIES[type_code]
        db.add(MasterValue(tenant_id=tid, type_code=type_code, code=code, label_i18n={"en": label}, sort=999))
        db.commit()
        bump("demo_categories")
        return code

    # -- helpdesk tickets
    ticket_cat = category("ticket_category")
    if ticket_cat is None:
        skipped.append("tickets: the company has no ticket categories (re-run with --demo-categories to add a 'Demo - IT help' one)")
    else:
        for key, subject, body, priority in TICKETS:
            if db.query(Ticket).filter(Ticket.tenant_id == tid, Ticket.subject == subject).first() is None:
                create_ticket(db, tenant, category_code=ticket_cat, subject=subject, description=body, priority=priority,
                              requester_employee_id=people[key].id)
                bump("tickets")

    # -- assets (one handed over to a demo employee)
    asset_cat = category("asset_category")
    if asset_cat is None:
        skipped.append("assets: the company has no asset categories (re-run with --demo-categories to add a 'Demo - Laptops' one)")
    else:
        for tag, name, holder in ASSETS:
            asset = db.query(Asset).filter(Asset.tenant_id == tid, Asset.name == name).first()
            if asset is None:
                if db.query(Asset).filter(Asset.tenant_id == tid, Asset.asset_tag == tag).first() is not None:
                    skipped.append(f"asset {name}: tag {tag} is already used by a real asset")
                    continue
                asset = assets_service.register_asset(db, tenant, asset_tag=tag, category_code=asset_cat, name=name, serial_number=f"SN-{tag}",
                                                      vendor="Demo supplier", location_id=locs[0].id)
                bump("assets")
            if holder and asset.status == "in_stock" and assets_service.active_allocation(db, tenant, asset.id) is None:
                assets_service.allocate(db, tenant, asset, employee_id=people[holder].id, actor=ACTOR)
                bump("asset_allocations")

    # -- one exit (resignation) with its clearance board
    leaver = people["rahul"]
    sep = db.query(Separation).filter(Separation.tenant_id == tid, Separation.employee_id == leaver.id).first()
    if sep is None:
        reason = db.query(MasterValue).filter(MasterValue.tenant_id == tid, MasterValue.type_code == "exit_reason", MasterValue.is_active.is_(True)).first()
        sep = separations_service.initiate(db, tenant, employee_id=leaver.id, separation_type="resignation", actor=ACTOR,
                                           requested_lwd=today + timedelta(days=45), reason_code=reason.code if reason else None,
                                           reason_text="Moving to another city to be closer to family.")
        separations_service.generate_clearance(db, tenant, sep)
        bump("separations")

    # -- agency, assigned to one published job
    agency = db.query(RecruitmentAgency).filter(RecruitmentAgency.tenant_id == tid, RecruitmentAgency.name == AGENCY_NAME).first()
    if agency is None:
        agency = RecruitmentAgency(tenant_id=tid, name=AGENCY_NAME, contact_email="demo.agency@example.com", notes="Demo agency for review.")
        db.add(agency)
        db.commit()
        bump("agencies")
    job = db.query(JobRole).filter(JobRole.tenant_id == tid, JobRole.status == "published").order_by(JobRole.created_at.desc()).first()
    if job is None:
        skipped.append("agency job: no published job to share with the demo agency")
    elif db.query(AgencyJobAssignment).filter(AgencyJobAssignment.tenant_id == tid, AgencyJobAssignment.agency_id == agency.id).first() is None:
        db.add(AgencyJobAssignment(tenant_id=tid, agency_id=agency.id, job_role_id=job.id))
        db.commit()
        bump("agency_jobs")

    return {"created": created, "skipped": skipped, "nothing_new": not created}


# ------------------------------------------------------------------ clear

def _groups(db, tenant) -> list[dict]:
    """Demo roots in delete order, each with the rows it owns: {"kind", "label", "rows": [(Model, [ids])]}.
    Rows are listed in the order they must be deleted within the group."""
    from app.models.agency import AgencyJobAssignment, AgencyMember, RecruitmentAgency
    from app.models.core_hr import Department, Employee, EmploymentRecord, Location
    from app.models.metadata import MasterValue
    from app.models.onboarding import OnboardingPlan, OnboardingTask, PreboardingCase, PreboardingDocument
    from app.models.performance import GOAL_LEVELS, Goal, GoalCheckin, Review, ReviewCycle
    from app.models.service_desk import Asset, AssetAllocation, ClearanceItem, Separation, Ticket, TicketComment
    from app.models.workflow import WorkflowInstance, WorkflowStep, WorkflowTimer

    tid = tenant.tenant_id
    like = f"{PREFIX}%"

    def ids(model, *conds) -> list:
        return [r[0] for r in db.query(model.id).filter(model.tenant_id == tid, *conds).all()]

    groups: list[dict] = []
    employees = db.query(Employee).filter(Employee.tenant_id == tid, Employee.first_name.like(like)).all()
    emp_ids = [e.id for e in employees]

    for t in db.query(Ticket).filter(Ticket.tenant_id == tid, Ticket.subject.like(like)).all():
        groups.append({"kind": "tickets", "label": t.subject, "rows": [(TicketComment, ids(TicketComment, TicketComment.ticket_id == t.id)), (Ticket, [t.id])]})

    for s in db.query(Separation).filter(Separation.tenant_id == tid, Separation.employee_id.in_(emp_ids)).all() if emp_ids else []:
        inst = ids(WorkflowInstance, WorkflowInstance.entity_type == "separation", WorkflowInstance.entity_id == s.id)
        groups.append({"kind": "separations", "label": f"exit of {s.employee_id}", "rows": [
            (ClearanceItem, ids(ClearanceItem, ClearanceItem.separation_id == s.id)), (Separation, [s.id]),
            (WorkflowTimer, ids(WorkflowTimer, WorkflowTimer.instance_id.in_(inst)) if inst else []),
            (WorkflowStep, ids(WorkflowStep, WorkflowStep.instance_id.in_(inst)) if inst else []),
            (WorkflowInstance, inst)]})

    for a in db.query(Asset).filter(Asset.tenant_id == tid, Asset.name.like(like)).all():
        groups.append({"kind": "assets", "label": a.name, "rows": [(AssetAllocation, ids(AssetAllocation, AssetAllocation.asset_id == a.id)), (Asset, [a.id])]})

    order = {lvl: i for i, lvl in enumerate(GOAL_LEVELS)}
    goals = db.query(Goal).filter(Goal.tenant_id == tid, Goal.title.like(like)).all()
    for g in sorted(goals, key=lambda g: -order.get(g.level, 0)):  # personal goals before the goals they roll up to
        groups.append({"kind": "goals", "label": g.title, "rows": [(GoalCheckin, ids(GoalCheckin, GoalCheckin.goal_id == g.id)), (Goal, [g.id])]})

    for c in db.query(ReviewCycle).filter(ReviewCycle.tenant_id == tid, ReviewCycle.name.like(like)).all():
        groups.append({"kind": "review_cycles", "label": c.name, "rows": [(Review, ids(Review, Review.cycle_id == c.id)), (ReviewCycle, [c.id])]})

    for ag in db.query(RecruitmentAgency).filter(RecruitmentAgency.tenant_id == tid, RecruitmentAgency.name.like(like)).all():
        groups.append({"kind": "agencies", "label": ag.name, "rows": [
            (AgencyJobAssignment, ids(AgencyJobAssignment, AgencyJobAssignment.agency_id == ag.id)),
            (AgencyMember, ids(AgencyMember, AgencyMember.agency_id == ag.id)), (RecruitmentAgency, [ag.id])]})

    # Employment records first as their own groups: they point at OTHER demo employees
    # (manager), so every one must go before any employee does.
    for e in employees:
        groups.append({"kind": "employment_records", "label": f"{e.first_name} {e.last_name or ''}".strip(),
                       "rows": [(EmploymentRecord, ids(EmploymentRecord, EmploymentRecord.employee_id == e.id))], "root_of": e.id})
    for e in employees:
        cases = ids(PreboardingCase, PreboardingCase.employee_id == e.id)
        plans = ids(OnboardingPlan, OnboardingPlan.case_id.in_(cases)) if cases else []
        groups.append({"kind": "employees", "label": f"{e.first_name} {e.last_name or ''}".strip(), "rows": [
            (OnboardingTask, ids(OnboardingTask, OnboardingTask.plan_id.in_(plans)) if plans else []),
            (OnboardingPlan, plans),
            (PreboardingDocument, ids(PreboardingDocument, PreboardingDocument.case_id.in_(cases)) if cases else []),
            (PreboardingCase, cases), (Employee, [e.id])]})

    for type_code, (code, _label) in DEMO_CATEGORIES.items():
        mv = ids(MasterValue, MasterValue.type_code == type_code, MasterValue.code == code, MasterValue.label_i18n["en"].astext.like(like))
        if mv:
            groups.append({"kind": "demo_categories", "label": f"{type_code}:{code}", "rows": [(MasterValue, mv)], "category": (type_code, code)})
    for d in db.query(Department).filter(Department.tenant_id == tid, Department.name.like(like)).all():
        groups.append({"kind": "departments", "label": d.name, "rows": [(Department, [d.id])]})
    for loc in db.query(Location).filter(Location.tenant_id == tid, Location.name.like(like)).all():
        groups.append({"kind": "locations", "label": loc.name, "rows": [(Location, [loc.id])]})

    for g in groups:
        g["rows"] = [(m, list(i)) for m, i in g["rows"] if i]
    return [g for g in groups if g["rows"]]


def _plan(db, tenant) -> tuple[list[dict], list[dict]]:
    """Split the demo groups into (delete, keep). A group is kept when a non-demo row
    points at any of its rows, or when a kept row points at it (it's still needed)."""
    from sqlalchemy import select

    from app.core.database import Base
    from app.models.metadata import MasterValue
    from app.models.service_desk import Asset, Ticket

    groups = _groups(db, tenant)
    owner: dict[tuple[str, object], int] = {}
    for gi, g in enumerate(groups):
        for model, ids in g["rows"]:
            for i in ids:
                owner[(model.__tablename__, i)] = gi
    # Employee rows belong to their "employees" group; their records group is part of the same root.
    root_of = {}
    for gi, g in enumerate(groups):
        if g["kind"] == "employees":
            emp_id = g["rows"][-1][1][0]
            for gj, h in enumerate(groups):
                if h.get("root_of") == emp_id:
                    root_of[gj] = gi
                    root_of[gi] = gj

    demo_tables: dict[str, list] = {}
    for (table, i) in owner:
        demo_tables.setdefault(table, []).append(i)

    keep: dict[int, str] = {}
    # 1) real rows pointing at demo rows
    for table in Base.metadata.sorted_tables:
        pk = table.c.get("id")
        for fk in table.foreign_keys:
            target = fk.column.table.name
            if target not in demo_tables:
                continue
            col = fk.parent
            stmt = select(pk if pk is not None else col, col).where(col.in_(demo_tables[target]))
            if "tenant_id" in table.c:
                stmt = stmt.where(table.c.tenant_id == tenant.tenant_id)
            for row_id, ref in db.execute(stmt).all():
                if pk is not None and (table.name, row_id) in owner:
                    continue
                gi = owner.get((target, ref))
                if gi is not None:
                    keep.setdefault(gi, f"in use by real data ({table.name}.{col.name})")
    # demo categories are referenced by code, not by a foreign key
    for gi, g in enumerate(groups):
        if "category" in g:
            type_code, code = g["category"]
            model, col, demo_ids = (Ticket, Ticket.category_code, [i for (t, i) in owner if t == "tickets"]) if type_code == "ticket_category" else \
                                   (Asset, Asset.category_code, [i for (t, i) in owner if t == "assets"])
            q = db.query(model.id).filter(model.tenant_id == tenant.tenant_id, col == code)
            if demo_ids:
                q = q.filter(~model.id.in_(demo_ids))
            if q.first() is not None:
                keep.setdefault(gi, f"in use by real data ({model.__tablename__}.category_code)")
    _ = MasterValue

    # 2) whatever a kept group points at is kept too (and an employee with its records)
    changed = True
    while changed:
        changed = False
        for gi in list(keep):
            partner = root_of.get(gi)
            if partner is not None and partner not in keep:
                keep[partner] = "kept with its employee"
                changed = True
            for model, ids in groups[gi]["rows"]:
                table = model.__table__
                for fk in table.foreign_keys:
                    target = fk.column.table.name
                    if target not in demo_tables:
                        continue
                    for (ref,) in db.execute(select(fk.parent).where(table.c.id.in_(ids))).all():
                        gj = owner.get((target, ref))
                        if gj is not None and gj != gi and gj not in keep:
                            keep[gj] = f"needed by kept demo record ({groups[gi]['label']})"
                            changed = True
    delete = [g for gi, g in enumerate(groups) if gi not in keep]
    kept = [{**groups[gi], "reason": why} for gi, why in keep.items()]
    return delete, kept


def _count(groups: list[dict]) -> dict:
    out: dict[str, int] = {}
    for g in groups:
        for model, ids in g["rows"]:
            out[model.__tablename__] = out.get(model.__tablename__, 0) + len(ids)
    return dict(sorted(out.items()))


def clear(db, tenant, *, apply: bool) -> dict:
    from sqlalchemy.exc import SQLAlchemyError

    delete, kept = _plan(db, tenant)
    report = {
        "dry_run": not apply,
        "would_remove" if not apply else "removed": _count(delete),
        "kept_in_use_by_real_data": [{"record": k["label"], "kind": k["kind"], "reason": k["reason"]} for k in kept],
    }
    if not apply:
        return report
    failed = []
    for g in delete:
        savepoint = db.begin_nested()
        try:
            for model, ids in g["rows"]:
                db.query(model).filter(model.tenant_id == tenant.tenant_id, model.id.in_(ids)).delete(synchronize_session=False)
            savepoint.commit()
        except SQLAlchemyError as exc:
            savepoint.rollback()
            failed.append({"record": g["label"], "kind": g["kind"], "error": str(exc.orig if hasattr(exc, "orig") else exc).splitlines()[0][:200]})
    db.commit()
    if failed:
        report["skipped_on_error"] = failed
        report["removed"] = _count([g for g in delete if g["label"] not in {f["record"] for f in failed}])
    return report


# ------------------------------------------------------------------ entry points

def _run(slug: str, fn):
    import app.main  # noqa: F401 -- settings registry + comms purposes the services read
    from app.platform.tenancy.context import TenantContext, tenant_context
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
    from app.platform.tenancy.models_cp import Tenant
    from app.platform.tenancy.provisioning import tenant_session

    cp_db = ControlPlaneSessionLocal()
    try:
        tenant = cp_db.query(Tenant).filter(Tenant.slug == slug).first()
    finally:
        cp_db.close()
    if tenant is None:
        raise SystemExit(f"no tenant with slug {slug!r}")
    ctx = TenantContext(tenant_id=tenant.id, slug=tenant.slug, isolation=tenant.isolation)
    with tenant_context(tenant.id, tenant.slug, tenant.isolation):
        db = tenant_session(tenant)
        try:
            return {"tenant": slug, **fn(db, ctx)}
        finally:
            db.close()


def run_seed(slug: str, demo_categories: bool) -> dict:
    return _run(slug, lambda db, ctx: seed(db, ctx, demo_categories=demo_categories))


def run_clear(slug: str, apply: bool) -> dict:
    return _run(slug, lambda db, ctx: clear(db, ctx, apply=apply))
