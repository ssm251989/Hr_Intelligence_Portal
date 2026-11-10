"""Automatic people agents: Onboarding (joining day) and Exit (letters when nothing blocks them)."""

from datetime import date

from sqlalchemy.orm import Session

from app.hr_agents.autopilot.core import ACTOR, Run, admins, card, enabled, notify, record, recently, rule


def joining_day(db: Session, tenant, run: Run, today: date | None = None) -> int:
    """Hourly: joiners whose joining date has come. 100% ready + rule on -> recorded as joined
    (employee record created); otherwise a 'confirm joined' card for HR, once a day."""
    if not enabled(db, tenant, "onboarding", "onboarding"):
        return 0
    from app.models.onboarding import PreboardingCase
    from app.onboarding import joiner_actions, joiner_stage
    from app.onboarding.portal import PreboardingPortal

    today = today or date.today()
    portal = PreboardingPortal(db, tenant)
    acted = 0
    for case in db.query(PreboardingCase).filter(PreboardingCase.tenant_id == tenant.tenant_id, PreboardingCase.joining_date <= today,
                                                 PreboardingCase.status.notin_(("joined", "revoked", "declined", "no_show", "exited"))).all():
        if "mark_joined" not in joiner_stage.allowed_actions(db, case, today):
            continue
        try:
            ready = portal.readiness(case).get("percent", 0)
        except Exception:  # noqa: BLE001
            ready = 0
        who = case.email
        if ready == 100 and rule(db, tenant, "mark_joined_when_ready"):
            try:
                out = joiner_actions.mark_joined(db, tenant, case, actor=ACTOR)
            except ValueError as exc:
                db.rollback()
                record(db, tenant, run, agent="onboarding", action="joined_rule", outcome="failed", entity_type="preboarding_case", entity_id=case.id,
                       summary=f"Could not record {who} as joined: {exc}")
                continue
            record(db, tenant, run, agent="onboarding", action="joined_rule", outcome="decided", rule_key="autopilot.rules.mark_joined_when_ready",
                   entity_type="preboarding_case", entity_id=case.id,
                   summary=f"Recorded {who} as joined on {case.joining_date.isoformat()} (pre-boarding 100% ready); employee {out.get('employee_code') or 'record'} created.")
            acted += 1
            continue
        if recently(db, tenant, agent="onboarding", action="propose_joined", entity_id=case.id):
            continue
        c = card(db, tenant, kind="agent_mark_joined", by_agent="onboarding", title=f"Confirm {who} joined on {case.joining_date.isoformat()}",
                 payload={"case_id": str(case.id), "email": who, "joining_date": case.joining_date.isoformat(), "readiness_percent": ready},
                 permission="onboarding.preboarding.approve", entity_type="preboarding_case", entity_id=case.id, agent_column="onboarding")
        record(db, tenant, run, agent="onboarding", action="propose_joined", outcome="proposed", entity_type="preboarding_case", entity_id=case.id,
               summary=f"{who} is due to join ({case.joining_date.isoformat()}, pre-boarding {ready}% ready) - asked HR to confirm.",
               details={"card_id": str(c.id)})
        acted += 1
    return acted


def resignations(db: Session, tenant, run: Run, today: date | None = None) -> int:
    """Part 29 ("agent prepares, HR approves"): a resignation waiting for HR (the manager step, if the company
    uses it, is done) gets an approval card with the last working day worked out from the notice period
    (the employee's own later date wins). Approving it runs the same approval as the Exits screen."""
    if not enabled(db, tenant, "exit"):
        return 0
    from app.employees.self_service import needs_manager
    from app.models.service_desk import Separation
    from app.service_desk.separations import standard_lwd

    acted = 0
    for s in db.query(Separation).filter(Separation.tenant_id == tenant.tenant_id, Separation.separation_type == "resignation",
                                         Separation.status == "submitted", Separation.approved_lwd.is_(None)).all():
        if needs_manager(db, tenant, s) is not None or recently(db, tenant, agent="exit", action="propose_resignation", entity_id=s.id, hours=24 * 30):
            continue
        name = _employee(db, s.employee_id)
        standard = standard_lwd(s)
        lwd = max(standard, s.requested_lwd) if s.requested_lwd else standard
        note = None
        if s.requested_lwd and s.requested_lwd < standard:
            note = f"{name} asked for {s.requested_lwd.isoformat()}, {(standard - s.requested_lwd).days} day(s) short of the notice period; edit the date and waive or buy out days if you agree."
        c = card(db, tenant, kind="agent_resignation_approve", by_agent="exit", title=f"Approve {name}'s resignation - last working day {lwd.isoformat()}",
                 payload={"separation_id": str(s.id), "employee": name, "last_working_day": lwd.isoformat(), "notice_period_days": s.notice_period_days,
                          "requested_lwd": s.requested_lwd.isoformat() if s.requested_lwd else None, "waived_days": 0, "buyout_days": 0, "note": note},
                 permission="separation.case.approve", entity_type="separation", entity_id=s.id, agent_column="onboarding")
        record(db, tenant, run, agent="exit", action="propose_resignation", outcome="proposed", entity_type="separation", entity_id=s.id,
               summary=f"{name} resigned on {s.submitted_on.isoformat()}; prepared the approval with last working day {lwd.isoformat()} "
                       f"({s.notice_period_days} days' notice) for HR.", details={"card_id": str(c.id)})
        acted += 1
    return acted


def exit_letters(db: Session, tenant, run: Run, today: date | None = None) -> int:
    """Hourly: exits past their last working day with no letters yet. Nothing blocking + rule on ->
    letters issued; nothing blocking, rule off -> card; still blocked 3+ days after the LWD -> HR told."""
    if not enabled(db, tenant, "exit"):
        return 0
    from app.employees import exit_checklist
    from app.models.service_desk import Separation
    from app.service_desk import separations

    today = today or date.today()
    acted = 0
    for s in db.query(Separation).filter(Separation.tenant_id == tenant.tenant_id, Separation.status.in_(("approved", "clearance", "completed")),
                                         Separation.approved_lwd.isnot(None), Separation.approved_lwd <= today).all():
        if s.relieving_letter_id is not None and s.experience_letter_id is not None:
            continue
        name = _employee(db, s.employee_id)
        blockers = separations.relieving_blockers(db, s)
        if blockers:
            if (today - s.approved_lwd).days >= 3 and not recently(db, tenant, agent="exit", action="escalate_blocked", entity_id=s.id):
                notify(db, tenant, admins(db, tenant), f"{name} left on {s.approved_lwd.isoformat()} but the letters wait for: {'; '.join(blockers)[:300]}",
                       "/exits", entity_type="separation", entity_id=s.id)
                record(db, tenant, run, agent="exit", action="escalate_blocked", outcome="escalated", entity_type="separation", entity_id=s.id,
                       summary=f"{name}'s letters are blocked by: {'; '.join(blockers)[:300]} - told HR.", details={"blockers": blockers})
                acted += 1
            continue
        if rule(db, tenant, "exit_letters_auto"):
            try:
                exit_checklist.generate_letters(db, tenant, s, actor=ACTOR)
            except ValueError as exc:
                db.rollback()
                record(db, tenant, run, agent="exit", action="letters_rule", outcome="failed", entity_type="separation", entity_id=s.id,
                       summary=f"Could not issue {name}'s letters: {exc}")
                continue
            record(db, tenant, run, agent="exit", action="letters_rule", outcome="decided", rule_key="autopilot.rules.exit_letters_auto",
                   entity_type="separation", entity_id=s.id, summary=f"Issued {name}'s relieving and experience letters (clearance complete).")
            acted += 1
            continue
        if recently(db, tenant, agent="exit", action="propose_letters", entity_id=s.id):
            continue
        c = card(db, tenant, kind="agent_exit_letters", by_agent="exit", title=f"Issue relieving and experience letters to {name}",
                 payload={"separation_id": str(s.id), "employee": name, "last_working_day": s.approved_lwd.isoformat()},
                 permission="separation.case.approve", entity_type="separation", entity_id=s.id, agent_column="onboarding")
        record(db, tenant, run, agent="exit", action="propose_letters", outcome="proposed", entity_type="separation", entity_id=s.id,
               summary=f"{name}'s clearance is complete - asked HR to issue the letters.", details={"card_id": str(c.id)})
        acted += 1
    return acted


def _employee(db, employee_id) -> str:
    from app.models.core_hr import Employee

    e = db.get(Employee, employee_id)
    return " ".join(x for x in (getattr(e, "first_name", None), getattr(e, "last_name", None)) if x) or "An employee"
