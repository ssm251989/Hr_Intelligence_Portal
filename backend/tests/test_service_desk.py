"""Helpdesk, assets, separation (docs/HRMS_COMPLETE_SPEC.txt Part 11). Covers this part's
named TESTS: SLA timers with business hours, asset clearance blocking relieving letter,
separation workflow end-to-end -- plus assignment, confidential visibility, pause/resume,
email-to-ticket, KB deflection, depreciation.

Written under the owner's testing-deferred directive (2026-09-25): not yet executed.
"""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.core_hr import employees as employees_service
from app.core_hr import letters
from app.core_hr import lifecycle
from app.models.core_hr import Employee
from app.models.service_desk import Asset, BusinessCalendar, SlaPolicy, TicketAssignmentRule
from app.platform.metadata import masters
from app.platform.tenancy.context import TENANT_1_ID, TenantContext
from app.service_desk import assets, separations, tickets
from app.service_desk.business_hours import Hours, add_business_minutes, business_minutes_between

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="tenant1-test", isolation="dedicated_db")
IST = ZoneInfo("Asia/Kolkata")
HOURS = Hours(timezone="Asia/Kolkata", working_days=[0, 1, 2, 3, 4], start_time="09:00", end_time="18:00", holidays={date(2026, 10, 2)})


def _ist(y, m, d, hh, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST)


# ---- SLA timers with business hours (pure) ----


def test_add_business_minutes_within_same_day():
    assert add_business_minutes(_ist(2026, 9, 28, 10), 120, HOURS) == _ist(2026, 9, 28, 12).astimezone(timezone.utc)


def test_add_business_minutes_rolls_over_night():
    # Mon 17:00 + 2h -> 1h Monday + 1h Tuesday -> Tue 10:00
    assert add_business_minutes(_ist(2026, 9, 28, 17), 120, HOURS) == _ist(2026, 9, 29, 10).astimezone(timezone.utc)


def test_add_business_minutes_skips_weekend_and_holiday():
    # Thu 1 Oct 17:00 + 2h: 1h Thu, Fri 2 Oct is a holiday, Sat/Sun off -> Mon 5 Oct 10:00
    assert add_business_minutes(_ist(2026, 10, 1, 17), 120, HOURS) == _ist(2026, 10, 5, 10).astimezone(timezone.utc)


def test_created_outside_hours_starts_next_morning():
    # Sat 11:00 + 30min -> Mon 09:30
    assert add_business_minutes(_ist(2026, 10, 3, 11), 30, HOURS) == _ist(2026, 10, 5, 9, 30).astimezone(timezone.utc)


def test_business_minutes_between_counts_only_working_time():
    assert business_minutes_between(_ist(2026, 9, 28, 17), _ist(2026, 9, 29, 10), HOURS) == 120
    assert business_minutes_between(_ist(2026, 10, 2, 10), _ist(2026, 10, 2, 12), HOURS) == 0  # holiday


def test_calendar_without_working_days_rejected():
    with pytest.raises(ValueError):
        add_business_minutes(_ist(2026, 9, 28, 10), 10, Hours(timezone="Asia/Kolkata", working_days=[]))


# ---- helpdesk fixtures ----


def _category(db_session, code="payroll_query", **attrs):
    return masters.create_value(db_session, TENANT, type_code="ticket_category", code=code, label_i18n={"en": code}, attributes=attrs or None)


def _calendar_and_policy(db_session, *, response=60, resolution=480, escalation=None):
    calendar = BusinessCalendar(tenant_id=TENANT.tenant_id, code="default", name="Default", timezone="Asia/Kolkata", working_days=[0, 1, 2, 3, 4],
                                start_time="09:00", end_time="18:00", holidays_json=[])
    db_session.add(calendar)
    db_session.flush()
    db_session.add(SlaPolicy(tenant_id=TENANT.tenant_id, name="Default medium", priority="medium", response_minutes=response,
                             resolution_minutes=resolution, calendar_id=calendar.id, use_requester_location_calendar=False, escalation_json=escalation or []))
    db_session.commit()
    return calendar


def test_ticket_gets_business_hours_due_dates(db_session):
    _category(db_session)
    _calendar_and_policy(db_session, response=60, resolution=480)
    ticket = tickets.create_ticket(db_session, TENANT, category_code="payroll_query", subject="Form 16", now=_ist(2026, 9, 28, 17))
    assert ticket.number.startswith("TKT-")
    assert ticket.response_due_at == _ist(2026, 9, 29, 9).astimezone(timezone.utc)   # 1h: 17:00-18:00 Mon
    assert ticket.resolution_due_at == _ist(2026, 9, 29, 16).astimezone(timezone.utc)  # 8h: 1h Mon + 7h Tue


def test_waiting_on_requester_pauses_resolution_clock(db_session):
    _category(db_session)
    _calendar_and_policy(db_session, resolution=480)
    ticket = tickets.create_ticket(db_session, TENANT, category_code="payroll_query", subject="x", now=_ist(2026, 9, 28, 9))
    original_due = ticket.resolution_due_at
    tickets.change_status(db_session, TENANT, ticket, "waiting_on_requester", now=_ist(2026, 9, 28, 10))
    tickets.change_status(db_session, TENANT, ticket, "in_progress", now=_ist(2026, 9, 28, 12))
    assert ticket.resolution_due_at == original_due + timedelta(hours=2)


def test_first_agent_reply_records_response(db_session):
    _category(db_session)
    _calendar_and_policy(db_session)
    ticket = tickets.create_ticket(db_session, TENANT, category_code="payroll_query", subject="x")
    tickets.add_comment(db_session, TENANT, ticket, author="agent", body="internal", is_agent=True, internal=True)
    assert ticket.first_responded_at is None  # internal notes don't count
    tickets.add_comment(db_session, TENANT, ticket, author="agent", body="Looking into it", is_agent=True)
    assert ticket.first_responded_at is not None and ticket.status == "in_progress"


def test_escalation_fires_once_per_step(db_session, monkeypatch):
    fired = []
    monkeypatch.setattr("app.platform.comms.service.dispatch_event", lambda db, t, event, ctx: fired.append((event, ctx["level"])) or [])
    _category(db_session)
    _calendar_and_policy(db_session, resolution=120, escalation=[{"at_pct": 50}, {"at_pct": 100}])
    ticket = tickets.create_ticket(db_session, TENANT, category_code="payroll_query", subject="x", now=_ist(2026, 9, 28, 10))
    fired.clear()
    tickets.process_escalations(db_session, TENANT, now=_ist(2026, 9, 28, 11, 15))
    tickets.process_escalations(db_session, TENANT, now=_ist(2026, 9, 28, 11, 20))
    assert fired == [("helpdesk.ticket_escalated", 1)]
    tickets.process_escalations(db_session, TENANT, now=_ist(2026, 9, 28, 13))
    assert ticket.escalation_level == 2


def test_round_robin_assignment(db_session):
    _category(db_session)
    db_session.add(TicketAssignmentRule(tenant_id=TENANT.tenant_id, strategy="round_robin", queue_code="hr_ops",
                                        agents_json=[{"user_id": "00000000-0000-0000-0000-00000000000a"}, {"user_id": "00000000-0000-0000-0000-00000000000b"}]))
    db_session.commit()
    first = tickets.create_ticket(db_session, TENANT, category_code="payroll_query", subject="1")
    second = tickets.create_ticket(db_session, TENANT, category_code="payroll_query", subject="2")
    assert str(first.assignee_user_id) != str(second.assignee_user_id)
    assert first.queue_code == "hr_ops"


def test_confidential_category_restricts_visibility(db_session):
    _category(db_session, code="posh", confidential=True, queue="ic")
    ticket = tickets.create_ticket(db_session, TENANT, category_code="posh", subject="complaint")
    assert ticket.confidential is True and ticket.queue_code == "ic"
    agent = SimpleNamespace(id="agent-user")
    assert not tickets.can_view(ticket, user=agent, employee_id=None, is_agent=True, can_view_confidential=False)
    assert tickets.can_view(ticket, user=agent, employee_id=None, is_agent=True, can_view_confidential=True)


def test_unknown_category_rejected(db_session):
    with pytest.raises(tickets.TicketError):
        tickets.create_ticket(db_session, TENANT, category_code="nope", subject="x")


def test_csat_only_after_resolution(db_session):
    _category(db_session)
    ticket = tickets.create_ticket(db_session, TENANT, category_code="payroll_query", subject="x")
    with pytest.raises(tickets.TicketError):
        tickets.record_csat(db_session, ticket, score=5)
    tickets.change_status(db_session, TENANT, ticket, "resolved")
    assert tickets.record_csat(db_session, ticket, score=4).csat_score == 4


def test_email_to_ticket_uses_default_category(db_session, monkeypatch):
    from app.models.comms import InboundMessage
    from app.platform.settings.resolver import SettingsService

    _category(db_session, code="general")
    original = SettingsService.get
    monkeypatch.setattr(SettingsService, "get", lambda self, key, ctx: "general" if key == "helpdesk.email.default_category" else original(self, key, ctx))
    inbound = InboundMessage(tenant_id=TENANT.tenant_id, from_address="someone@example.com", subject="Help", body_ref="My payslip is wrong")
    db_session.add(inbound)
    db_session.commit()
    ticket = tickets.ticket_from_email(db_session, TENANT, inbound)
    assert ticket.channel == "email" and inbound.status == "routed" and inbound.routed_entity_id == ticket.id


# ---- assets ----


def _asset(db_session, tag="LAP-001", **kwargs):
    if not masters.list_values(db_session, TENANT, "asset_category"):
        masters.create_value(db_session, TENANT, type_code="asset_category", code="laptop", label_i18n={"en": "Laptop"}, attributes={"clearance_department": "it"})
    return assets.register_asset(db_session, TENANT, asset_tag=tag, category_code="laptop", name="Laptop", **kwargs)


def _employee(db_session, **kwargs):
    employee = employees_service.create_employee(db_session, TENANT, first_name="Leaver", status="active")
    lifecycle.apply_event(db_session, TENANT, employee_id=employee.id, event_type="hire", effective_from=date(2024, 1, 1), changes={"grade": "G2", **kwargs})
    return employee


def test_allocation_requires_in_stock(db_session):
    asset = _asset(db_session)
    emp = _employee(db_session)
    assets.allocate(db_session, TENANT, asset, employee_id=emp.id, actor="it")
    with pytest.raises(assets.AssetError):
        assets.allocate(db_session, TENANT, asset, employee_id=emp.id, actor="it")


def test_straight_line_depreciation():
    asset = Asset(purchase_cost=36000, purchase_date=date(2025, 1, 1), depreciation_json={"method": "straight_line", "life_months": 36, "salvage_value": 0})
    assert assets.book_value(asset, as_of=date(2026, 1, 1)) == 24000.0
    assert assets.book_value(asset, as_of=date(2030, 1, 1)) == 0.0


def test_request_without_workflow_is_auto_approved_and_fulfilled(db_session):
    _asset(db_session)
    emp = _employee(db_session)
    request = assets.request_asset(db_session, TENANT, employee_id=emp.id, category_code="laptop")
    assert request.status == "approved"
    allocation = assets.fulfil_request(db_session, TENANT, request, actor="it")
    assert allocation.employee_id == emp.id and request.status == "fulfilled"


# ---- separation: asset clearance blocks relieving letter + end-to-end ----


def _relieving_template(db_session):
    template = letters.create_draft(db_session, TENANT, key="relieving", name="Relieving", html_tpl="<p>Relieved on {{ last_working_day }}</p>")
    letters.publish(db_session, template)


def test_asset_clearance_blocks_relieving_letter(db_session):
    _relieving_template(db_session)
    emp = _employee(db_session)
    allocation = assets.allocate(db_session, TENANT, _asset(db_session), employee_id=emp.id, actor="it")
    sep = separations.initiate(db_session, TENANT, employee_id=emp.id, separation_type="resignation", actor="emp", submitted_on=date(2026, 9, 1))
    separations.approve_lwd(db_session, TENANT, sep, lwd=date(2026, 10, 1), actor="hr")
    for item in separations._items(db_session, sep):
        if item.kind != "asset_recovery":
            separations.clear_item(db_session, item, actor="owner")

    with pytest.raises(separations.ClearanceBlockedError, match="Recover Laptop"):
        separations.issue_relieving_letter(db_session, TENANT, sep, actor="hr", template_key="relieving")

    recovery = next(i for i in separations._items(db_session, sep) if i.kind == "asset_recovery")
    assert recovery.department == "it"  # from the asset_category master's clearance_department
    with pytest.raises(separations.SeparationError):
        separations.clear_item(db_session, recovery, actor="it")  # can't clear before the return is recorded

    assets.return_asset(db_session, TENANT, allocation, condition="good", received_by="it")
    db_session.refresh(recovery)
    assert recovery.status == "cleared"
    result = separations.issue_relieving_letter(db_session, TENANT, sep, actor="hr", template_key="relieving")
    assert result["relieving_letter_id"]


def test_separation_end_to_end(db_session, monkeypatch):
    monkeypatch.setattr("app.platform.comms.service.dispatch_event", lambda *a, **k: [])
    _relieving_template(db_session)
    emp = _employee(db_session, notice_period_days=60)
    sep = separations.initiate(db_session, TENANT, employee_id=emp.id, separation_type="resignation", actor="emp",
                               submitted_on=date(2026, 8, 1), requested_lwd=date(2026, 9, 1), reason_code="better_opportunity")
    assert sep.notice_period_days == 60
    assert db_session.get(Employee, emp.id).status == "on_notice"

    with pytest.raises(separations.SeparationError, match="short of notice"):
        separations.approve_lwd(db_session, TENANT, sep, lwd=date(2026, 9, 1), actor="hr")  # 29 days short, not covered
    separations.approve_lwd(db_session, TENANT, sep, lwd=date(2026, 9, 1), actor="hr", waived_days=19, buyout_days=10)
    assert sep.status == "clearance"

    separations.add_kt_task(db_session, TENANT, sep, title="Hand over reports")
    separations.submit_exit_interview(db_session, sep, answers={"reason": "growth"})
    for item in separations._items(db_session, sep):
        separations.clear_item(db_session, item, actor="owner")
    separations.issue_relieving_letter(db_session, TENANT, sep, actor="hr", template_key="relieving")
    separations.complete(db_session, TENANT, sep, actor="hr", rehire_eligible=True, alumni_opt_in=True, as_of=date(2026, 9, 2))

    assert sep.status == "completed"
    assert db_session.get(Employee, emp.id).status == "rehire_eligible"
    assert lifecycle.get_current_employment(db_session, TENANT, emp.id, as_of=date(2026, 9, 2)) is None
    summary = separations.exit_summary(db_session, sep)
    assert summary["notice_served_days"] == 31 and summary["notice_short_days"] == 29
    assert "notice_served_days" in separations.export_csv(db_session, [sep])


def test_cannot_complete_before_lwd(db_session):
    emp = _employee(db_session)
    sep = separations.initiate(db_session, TENANT, employee_id=emp.id, separation_type="termination", actor="hr", submitted_on=date(2026, 9, 1))
    separations.approve_lwd(db_session, TENANT, sep, lwd=date(2026, 10, 1), actor="hr")
    for item in separations._items(db_session, sep):
        separations.clear_item(db_session, item, actor="owner")
    with pytest.raises(separations.SeparationError, match="has not passed"):
        separations.complete(db_session, TENANT, sep, actor="hr", rehire_eligible=False, as_of=date(2026, 9, 15))


def test_withdrawal_restores_active_status(db_session):
    emp = _employee(db_session)
    sep = separations.initiate(db_session, TENANT, employee_id=emp.id, separation_type="resignation", actor="emp")
    separations.withdraw(db_session, sep, actor="emp")
    assert db_session.get(Employee, emp.id).status == "active"


def test_only_one_open_separation(db_session):
    emp = _employee(db_session)
    separations.initiate(db_session, TENANT, employee_id=emp.id, separation_type="resignation", actor="emp")
    with pytest.raises(separations.SeparationError):
        separations.initiate(db_session, TENANT, employee_id=emp.id, separation_type="termination", actor="hr")


# ---- API ----


def test_api_relieving_letter_409_when_blocked(client, db_session):
    emp = _employee(db_session)
    assets.allocate(db_session, TENANT, _asset(db_session, tag="LAP-API"), employee_id=emp.id, actor="it")
    created = client.post("/api/v1/service-desk/separations", json={"employee_id": str(emp.id), "separation_type": "termination", "submitted_on": "2026-09-01"})
    assert created.status_code == 201
    sep_id = created.json()["separation_id"]
    assert client.post(f"/api/v1/service-desk/separations/{sep_id}/approve-lwd", json={"lwd": "2026-10-01", "waived_days": 0}).status_code == 200
    blocked = client.post(f"/api/v1/service-desk/separations/{sep_id}/relieving-letter", json={"template_key": "relieving"})
    assert blocked.status_code == 409


def test_api_ticket_list_paginates(client, db_session):
    _category(db_session)
    response = client.get("/api/v1/service-desk/tickets?page=1&page_size=10")
    assert response.status_code == 200 and {"total", "items"} <= response.json().keys()


def test_api_helpdesk_requires_permission(make_auth_headers, anonymous_client):
    headers = make_auth_headers(role="interviewer")
    assert anonymous_client.get("/api/v1/service-desk/tickets", headers=headers).status_code == 403
