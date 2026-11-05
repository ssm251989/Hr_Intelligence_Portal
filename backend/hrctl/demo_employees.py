"""hrctl demo employees / demo clear (Part 20.2b) -- 8 clearly labelled DEMO employees for trying the
Employees list. Removable; never touches real records.

    python -m hrctl.demo employees --tenant ctd-techs --count 8
    python -m hrctl.demo clear --tenant ctd-techs [--yes]     # dry run unless --yes (also clears the Part 15.8 demo data)

Every record is marked: names start with "Demo - ", employees carry custom_fields.demo = true, Employee IDs
are CTD-9001.. (OUTSIDE the running number, so real IDs are not used up -- decision logged in
build_log.md), company emails are TEST-provider dummy mailboxes demo.<first>.<last>@<domain>, app accounts
are created but NO invite is sent. Departments / locations this command had to create are "Demo - ..."
and recorded in the audit log (action demo_employees_master_created) so `clear` removes exactly those.
"""

import random
from datetime import date, datetime, timedelta, timezone

ACTOR = "hrctl demo employees"
PEOPLE = (
    # first, last, designation, department, location, roles, status
    ("Aarav", "Sharma", "Junior AI Developer", "AI", "Hyderabad", [], "active"),
    ("Diya", "Nair", "Senior AI Developer", "AI", "Bengaluru", ["Interviewer"], "active"),
    ("Kabir", "Reddy", "RPA Developer", "RPA", "Hyderabad", [], "active"),
    ("Meera", "Iyer", "QA Engineer", "QA", "Chennai", [], "on_notice"),
    ("Rohan", "Kulkarni", "HR Executive", "Demo - HR", "Pune", [], "active"),
    ("Sneha", "Menon", "Project Manager", "Demo - Delivery", "Bengaluru", [], "active"),
    ("Vikram", "Joshi", "Data Analyst", "Demo - Analytics", "Pune", [], "exited"),
    ("Ananya", "Rao", "Interviewer Lead", "AI", "Chennai", ["Interviewer"], "active"),
)
CODE_START = 9001


def seed(db, tenant, *, count: int = 8) -> dict:
    from app.audit.service import log_action
    from app.core.security import hash_password
    from app.core_hr.employees import create_employee
    from app.employees import mailboxes, test_provider
    from app.employees.roles import add_roles
    from app.models.core_hr import Department, Employee, EmploymentRecord, Location
    from app.models.test_mailbox import TestMailbox
    from app.models.user import User
    from app.platform.iam.roles import bridge_single_user

    import secrets

    rnd = random.Random(20261006)
    if mailboxes.active_provider(db, tenant) not in ("test",) and mailboxes.active_provider(db, tenant) is None:
        test_provider.switch(db, tenant, on=True, actor=ACTOR)  # dummy mailboxes; never a real one
    dom = mailboxes.domain(db, tenant)

    def dept(name):
        row = db.query(Department).filter(Department.tenant_id == tenant.tenant_id, Department.name == name).first()
        if row is None:
            row = Department(tenant_id=tenant.tenant_id, name=name if name.startswith("Demo - ") else f"Demo - {name}")
            db.add(row)
            db.commit()
            log_action(db, "department", row.id, "demo_employees_master_created", ACTOR, {"name": row.name})
        return row

    def loc(city):
        name = f"Demo - {city}"
        row = db.query(Location).filter(Location.tenant_id == tenant.tenant_id, Location.name == name).first()
        if row is None:
            row = Location(tenant_id=tenant.tenant_id, name=name, address=f"{city} (demo)")
            db.add(row)
            db.commit()
            log_action(db, "location", row.id, "demo_employees_master_created", ACTOR, {"name": name})
        return row

    created, skipped = [], []
    by_code = {}
    for i, (first, last, designation, department, city, roles, status) in enumerate(PEOPLE[:max(1, min(count, len(PEOPLE)))]):
        code = f"CTD-{CODE_START + i}"
        if db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id, Employee.employee_code == code).first() is not None:
            skipped.append(code)
            by_code[code] = db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id, Employee.employee_code == code).first()
            continue
        joined = date.today() - timedelta(days=rnd.randint(40, 3 * 365))
        e = create_employee(db, tenant, first_name=f"Demo - {first}", last_name=last, employee_code=code, status=status,
                            personal_email=f"demo.{first.lower()}.{last.lower()}@example.com", personal_phone=f"+91 9{rnd.randint(1000, 9999)} {rnd.randint(10000, 99999)}",
                            custom_fields={"demo": True})
        e.joined_on, e.previous_experience_months = joined, rnd.randint(0, 120)
        if status == "exited":
            e.exited_on, e.rehire_eligible = date.today() - timedelta(days=rnd.randint(10, 60)), True
        address = f"demo.{first.lower()}.{last.lower()}@{dom}"
        e.company_email, e.company_email_provider = address, "test"
        db.add(TestMailbox(tenant_id=tenant.tenant_id, address=address, display_name=f"Demo - {first} {last}", employee_id=e.id, employee_code=code,
                           status="active" if status != "exited" else "suspended", created_by=ACTOR))
        d, lo = dept(department), loc(city)
        db.add(EmploymentRecord(tenant_id=tenant.tenant_id, employee_id=e.id, effective_from=joined, event_type="hire", designation=designation,
                                department_id=d.id, location_id=lo.id, employment_type="full_time", notice_period_days=60, created_by=ACTOR))
        user = User(tenant_id=tenant.tenant_id, email=address, full_name=f"Demo - {first} {last}", role="employee",
                    hashed_password=hash_password(secrets.token_urlsafe(32)))
        if status == "exited":
            user.deactivated_at = datetime.now(timezone.utc)
        db.add(user)
        db.commit()
        bridge_single_user(db, tenant, user)
        e.user_id = user.id
        db.commit()
        add_roles(db, tenant, user, ["Employee", *roles])
        log_action(db, "employee", e.id, "demo_employee_created", ACTOR, {"code": code})
        by_code[code] = e
        created.append({"code": code, "name": f"Demo - {first} {last}", "designation": designation, "status": status, "email": address, "roles": ["Employee", *roles]})
    # managers: the Project Manager leads the developers / QA / analyst; the Senior AI Developer leads the Junior
    pm, senior = by_code.get(f"CTD-{CODE_START + 5}"), by_code.get(f"CTD-{CODE_START + 1}")
    from app.employees.directory import current_record

    for i, code in enumerate(by_code):
        e = by_code[code]
        r = current_record(db, e.id)
        if r is None:
            continue
        boss = senior if i == 0 else (pm if i in (1, 2, 3, 6, 7) else None)
        if boss is not None and boss.id != e.id:
            r.manager_employee_id = boss.id
    db.commit()
    return {"created": created, "already_there": skipped, "test_provider": mailboxes.active_provider(db, tenant), "domain": dom}


def clear(db, tenant, *, apply: bool) -> dict:
    """Only demo employees (custom_fields.demo) + their test mailboxes, app accounts and what this command created."""
    from sqlalchemy import text

    from app.models.audit_log import AuditLog
    from app.models.core_hr import Employee

    emps = [e for e in db.query(Employee).filter(Employee.tenant_id == tenant.tenant_id).all() if (e.custom_fields or {}).get("demo") is True]
    ids = [str(e.id) for e in emps]
    users = [str(e.user_id) for e in emps if e.user_id]
    masters = db.query(AuditLog).filter(AuditLog.action == "demo_employees_master_created").all()
    report = {"employees": [e.employee_code for e in emps], "app_accounts": len(users),
              "demo_departments_locations": [(m.details or {}).get("name") for m in masters]}
    if not apply:
        return {"dry_run": True, **report}
    q = lambda sql, **k: db.execute(text(sql), k)  # noqa: E731
    if ids:
        q("delete from test_mailbox_messages where mailbox_id in (select id from test_mailboxes where employee_id::text = any(:i))", i=ids)
        q("delete from test_mailboxes where employee_id::text = any(:i)", i=ids)
        for t, col in (("asset_allocations", "employee_id"), ("employment_records", "manager_employee_id"), ("employment_records", "employee_id"),
                       ("employee_documents", "employee_id"), ("letter_records", "employee_id"), ("clearance_items", "separation_id")):
            if t == "clearance_items":
                q("delete from clearance_items where separation_id in (select id from separations where employee_id::text = any(:i))", i=ids)
            elif col == "manager_employee_id":
                q("update employment_records set manager_employee_id = null where manager_employee_id::text = any(:i)", i=ids)
            else:
                q(f"delete from {t} where {col}::text = any(:i)", i=ids)
        q("delete from separations where employee_id::text = any(:i)", i=ids)
        q("update interviewer_availability set employee_id = null where employee_id::text = any(:i)", i=ids)
        q("delete from agent_suggestions where entity_id::text = any(:i)", i=ids)
        q("delete from audit_log where entity_id::text = any(:i)", i=ids)
    if users:
        cols = [r[0] for r in q("select table_name from information_schema.columns where table_schema='public' and column_name='user_id' and table_name not in ('employees')")]
        for t in cols:
            q(f"delete from {t} where user_id::text = any(:u)", u=users)
        q("update employees set user_id = null where user_id::text = any(:u)", u=users)
    if ids:
        q("delete from employees where id::text = any(:i)", i=ids)
    if users:
        q("delete from users where id::text = any(:u)", u=users)
    for m in masters:
        table = "departments" if m.entity_type == "department" else "locations"
        in_use = q(f"select count(*) from employment_records where {'department_id' if table == 'departments' else 'location_id'} = :x", x=m.entity_id).scalar()
        if not in_use:
            q(f"delete from {table} where id = :x", x=m.entity_id)
            q("delete from audit_log where id = :x", x=m.id)
    db.commit()
    return {"dry_run": False, "removed": report}


def run_seed(slug: str, count: int) -> dict:
    from hrctl.demo_data import _run

    return _run(slug, lambda db, ctx: seed(db, ctx, count=count))


def run_clear(slug: str, apply: bool) -> dict:
    from hrctl.demo_data import _run

    return _run(slug, lambda db, ctx: clear(db, ctx, apply=apply))
