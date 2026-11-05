"""What happens when HR approves an agent's approval card (My approvals).

`agent_shortlist` (Screening agent): each candidate still waiting for a decision is
shortlisted exactly as the Shortlisting screen does it (same function), which also starts
interview scheduling and the salary step. Candidates whose status changed in the meantime
are skipped and listed on the card.
"""

from app.agents.service import applier


@applier("agent_shortlist")
def _apply_agent_shortlist(db, tenant, suggestion, payload, reviewer):
    from uuid import UUID

    from app.models.user import User
    from app.schemas.application import ShortlistDecisionRequest
    from app.shortlisting.router import make_shortlist_decision

    user = db.query(User).filter(User.email == reviewer).first()
    if user is None:
        raise PermissionError("reviewer not found")
    done, skipped = [], []
    for row in payload.get("candidates") or []:
        try:
            make_shortlist_decision(UUID(row["application_id"]),
                                    ShortlistDecisionRequest(decision="select", notes=f"Approved from the Screening agent's card. {payload.get('reason') or ''}".strip(),
                                                             decided_by=reviewer), db, user)
            done.append(row.get("name"))
        except Exception as exc:  # noqa: BLE001 -- one candidate's state must not block the others
            db.rollback()
            skipped.append({"name": row.get("name"), "why": getattr(exc, "detail", None) or str(exc)[:120]})
    payload["result"] = {"shortlisted": done, "skipped": skipped}


# ---------------------------------------------------------------- hiring-to-exit cards
# Each runs the same service function the screen uses. A ValueError from the service (state
# changed, budget short, vendor gone, ...) becomes an AgentError, so the card stays pending and
# HR sees the reason (400) instead of a server error.


def _service_call(db, fn):
    from app.agents.service import AgentError

    try:
        return fn()
    except ValueError as exc:
        db.rollback()
        raise AgentError(str(exc)) from exc


def _app(db, tenant, payload):
    from uuid import UUID

    from app.agents.service import AgentError
    from app.models.application import Application

    app = db.get(Application, UUID(payload["application_id"]))
    if app is None or app.tenant_id != tenant.tenant_id:
        raise AgentError("the candidate's application no longer exists")
    return app


def _result(payload, out):
    payload["result"] = {k: v for k, v in (out or {}).items() if isinstance(v, (str, int, float, bool, type(None)))}


@applier("agent_salary_decision")
def _apply_salary(db, tenant, suggestion, payload, reviewer):
    from app.recruitment import salary_auto

    app = _app(db, tenant, payload)
    amount = payload.get("amount")
    out = _service_call(db, lambda: salary_auto.decide(db, tenant, app, decision=payload["decision"], actor=reviewer,
                                                       amount=float(amount) if amount not in (None, "") else None, reason=payload.get("reason")))
    _result(payload, out)


@applier("agent_documents_approve")
def _apply_documents(db, tenant, suggestion, payload, reviewer):
    from app.recruitment import joining_docs

    app = _app(db, tenant, payload)
    _result(payload, _service_call(db, lambda: joining_docs.approve(db, tenant, app, actor=reviewer)))


@applier("agent_bgv_assign")
def _apply_bgv_assign(db, tenant, suggestion, payload, reviewer):
    from datetime import date
    from uuid import UUID

    from app.bgv import vendors

    app = _app(db, tenant, payload)
    due = date.fromisoformat(payload["due_date"]) if payload.get("due_date") else None
    _result(payload, _service_call(db, lambda: vendors.assign(db, tenant, app, agency_id=UUID(payload["agency_id"]), checks=list(payload.get("checks") or []),
                                                               due_date=due, actor=reviewer)))


@applier("agent_bgv_decision")
def _apply_bgv_decision(db, tenant, suggestion, payload, reviewer):
    from app.recruitment import bgv_decision

    app = _app(db, tenant, payload)
    _result(payload, _service_call(db, lambda: bgv_decision.decide(db, tenant, app, decision=payload["decision"], actor=reviewer,
                                                                    note=payload.get("note"), reason=payload.get("reason"))))


@applier("agent_joining_dates")
def _apply_joining_dates(db, tenant, suggestion, payload, reviewer):
    from app.recruitment import joining_dates

    app = _app(db, tenant, payload)
    _result(payload, _service_call(db, lambda: joining_dates.propose(db, tenant, app, list(payload["dates"]), actor=reviewer, note=payload.get("note"))))


@applier("agent_mark_joined")
def _apply_mark_joined(db, tenant, suggestion, payload, reviewer):
    from uuid import UUID

    from app.agents.service import AgentError
    from app.models.onboarding import PreboardingCase
    from app.onboarding import joiner_actions

    case = db.get(PreboardingCase, UUID(payload["case_id"]))
    if case is None or case.tenant_id != tenant.tenant_id:
        raise AgentError("the joiner no longer exists")
    _result(payload, _service_call(db, lambda: joiner_actions.mark_joined(db, tenant, case, actor=reviewer)))


@applier("agent_exit_letters")
def _apply_exit_letters(db, tenant, suggestion, payload, reviewer):
    from uuid import UUID

    from app.agents.service import AgentError
    from app.employees import exit_checklist
    from app.models.service_desk import Separation

    s = db.get(Separation, UUID(payload["separation_id"]))
    if s is None or s.tenant_id != tenant.tenant_id:
        raise AgentError("the exit no longer exists")
    _result(payload, _service_call(db, lambda: exit_checklist.generate_letters(db, tenant, s, actor=reviewer)))
