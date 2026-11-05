"""Analytics / report builder / HR Copilot / agents / AI governance API
(docs/HRMS_COMPLETE_SPEC.txt Part 12). One router file for the whole part so the
AI-disabled behaviour (403 with a plain-language reason, never a raw 500) is uniform.
"""

from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents import service as agents
from app.analytics import datasets, metrics, predictive, schedules
from app.analytics.report_builder import ReportBuilder, ReportError, ReportPermissionError, export
from app.copilot import retrieval
from app.copilot.service import CopilotError, CopilotService
from app.core.database import get_db
from app.models.intelligence import AgentSuggestion, AiDecisionLog, AiUsageBudget, Dashboard, KnowledgeDocument, PromptEvalFixture, ReportSchedule, SavedReport
from app.models.user import User
from app.platform.ai import governance, prompt_eval
from app.platform.iam.authz import has_permission, require
from app.platform.iam.org_scope import employee_ids_in_scope
from app.platform.iam.roles import role_names_for
from app.platform.tenancy.context import require_current_tenant

router = APIRouter(prefix="/api/v1/intelligence", tags=["analytics", "copilot", "ai"])


def _get(db: Session, model, row_id: UUID, label: str):
    tenant = require_current_tenant()
    row = db.query(model).filter(model.tenant_id == tenant.tenant_id, model.id == row_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return row


def _ai_error(exc: Exception) -> HTTPException:
    if isinstance(exc, governance.AIDisabledError):
        return HTTPException(status_code=403, detail={"code": "AI_DISABLED", "message": str(exc), "fix_path": "/settings#ai"})
    if isinstance(exc, governance.BudgetExceededError):
        return HTTPException(status_code=429, detail={"code": "AI_BUDGET_EXCEEDED", "message": str(exc), "fix_path": "/settings#ai"})
    return HTTPException(status_code=502, detail={"code": "AI_UNAVAILABLE", "message": "The AI service couldn't complete this request. Try again, or check the AI connection.", "fix_path": "/settings#connections"})


# ---- datasets + report builder ----


@router.get("/datasets")
def list_datasets(db: Session = Depends(get_db), current_user: User = Depends(require("analytics.report.view"))):
    tenant = require_current_tenant()
    return [datasets.describe(db, tenant, code) for code, d in datasets.DATASETS.items() if has_permission(db, tenant, current_user, d.permission)]


class ReportRun(BaseModel):
    dataset: str
    definition: dict
    offset: int = 0


@router.post("/reports/run")
def run_report(payload: ReportRun, db: Session = Depends(get_db), current_user: User = Depends(require("analytics.report.view"))):
    try:
        return ReportBuilder(db, require_current_tenant(), current_user).run(payload.dataset, payload.definition, offset=payload.offset)
    except ReportPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ReportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class ReportSave(BaseModel):
    name: str
    dataset: str
    definition: dict
    shared_role_names: list[str] = []


def _visible_reports(db: Session, user: User) -> list[SavedReport]:
    tenant = require_current_tenant()
    my_roles = set(role_names_for(db, tenant, user))
    rows = db.query(SavedReport).filter(SavedReport.tenant_id == tenant.tenant_id).order_by(SavedReport.name).all()
    return [r for r in rows if r.owner_user_id == user.id or set(r.shared_role_names or []) & my_roles]


@router.post("/reports", status_code=201)
def save_report(payload: ReportSave, db: Session = Depends(get_db), current_user: User = Depends(require("analytics.report.create"))):
    tenant = require_current_tenant()
    try:
        ReportBuilder(db, tenant, current_user).run(payload.dataset, {**payload.definition, "limit": 1})  # validate before saving
    except (ReportError, ReportPermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    row = SavedReport(tenant_id=tenant.tenant_id, name=payload.name, dataset_code=payload.dataset, definition_json=payload.definition,
                      owner_user_id=current_user.id, shared_role_names=payload.shared_role_names)
    db.add(row)
    db.commit()
    return {"id": str(row.id)}


@router.get("/reports")
def list_reports(db: Session = Depends(get_db), current_user: User = Depends(require("analytics.report.view"))):
    return [{"id": str(r.id), "name": r.name, "dataset": r.dataset_code, "owner_user_id": str(r.owner_user_id), "shared_role_names": r.shared_role_names}
            for r in _visible_reports(db, current_user)]


@router.get("/reports/{report_id}/run")
def run_saved(report_id: UUID, offset: int = 0, db: Session = Depends(get_db), current_user: User = Depends(require("analytics.report.view"))):
    report = next((r for r in _visible_reports(db, current_user) if r.id == report_id), None)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    try:  # a shared report runs with the VIEWER's scope, never the owner's
        return ReportBuilder(db, require_current_tenant(), current_user).run(report.dataset_code, report.definition_json, offset=offset)
    except ReportPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ReportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/reports/{report_id}/export")
def export_saved(report_id: UUID, format: str = "csv", db: Session = Depends(get_db), current_user: User = Depends(require("analytics.report.export"))):
    report = next((r for r in _visible_reports(db, current_user) if r.id == report_id), None)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    try:
        result = ReportBuilder(db, require_current_tenant(), current_user).run(report.dataset_code, {**report.definition_json, "limit": 10_000})
        content, media_type, ext = export(result, format, title=report.name)
    except ReportPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ReportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{report.name}.{ext}"'})


class ScheduleCreate(BaseModel):
    frequency: str
    hour: int = 8
    recipients: list[str]
    template_key: str
    format: str = "csv"
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None


@router.post("/reports/{report_id}/schedules", status_code=201)
def schedule_report(report_id: UUID, payload: ScheduleCreate, db: Session = Depends(get_db), current_user: User = Depends(require("analytics.report.export"))):
    report = _get(db, SavedReport, report_id, "Report")
    if report.owner_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the report's owner can schedule it (it runs with the owner's access)")
    try:
        row = schedules.create_schedule(db, require_current_tenant(), report, frequency=payload.frequency, hour=payload.hour, recipients=payload.recipients,
                                        template_key=payload.template_key, fmt=payload.format, day_of_week=payload.day_of_week, day_of_month=payload.day_of_month)
    except schedules.ScheduleError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": str(row.id), "next_run_at": row.next_run_at.isoformat()}


@router.post("/reports/schedules/run-due")
def run_due(db: Session = Depends(get_db), current_user: User = Depends(require("analytics.dashboard.configure"))):
    deliveries = schedules.run_due_schedules(db, require_current_tenant())
    return [{"schedule_id": str(d.schedule_id), "status": d.status, "rows": d.row_count, "error": d.error} for d in deliveries]


@router.get("/warehouse-export/{dataset_code}")
def warehouse_export(dataset_code: str, db: Session = Depends(get_db), current_user: User = Depends(require("analytics.report.export"))):
    """BI pull endpoint (CSV of a whole dataset, caller's scope). A push connector on the
    `analytics.warehouse_push` purpose is registered but has no adapter yet."""
    try:
        builder = ReportBuilder(db, require_current_tenant(), current_user)
        described = datasets.describe(db, require_current_tenant(), dataset_code)
        result = builder.run(dataset_code, {"columns": [f["key"] for f in described["fields"]], "limit": 10_000})
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown dataset")
    except ReportPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    content, media_type, _ = export(result, "csv")
    return Response(content=content, media_type=media_type)


# ---- metrics / dashboards / predictive ----


@router.get("/metrics/{metric}")
def get_metric(metric: str, as_of: Optional[date] = None, db: Session = Depends(get_db), current_user: User = Depends(require("analytics.metrics.view"))):
    tenant = require_current_tenant()
    scope = employee_ids_in_scope(db, tenant, current_user, "analytics.metrics.view")
    try:
        return metrics.compute(db, tenant, metric, scope=scope, as_of=as_of)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown metric. Available: {', '.join(metrics.METRICS)}")


class DashboardUpsert(BaseModel):
    code: str
    name: str
    audience_role: Optional[str] = None
    widgets: list[dict]


@router.put("/dashboards")
def upsert_dashboard(payload: DashboardUpsert, db: Session = Depends(get_db), current_user: User = Depends(require("analytics.dashboard.configure"))):
    for w in payload.widgets:
        if w.get("type") == "metric" and w.get("metric") not in metrics.METRICS:
            raise HTTPException(status_code=400, detail=f"Unknown metric {w.get('metric')!r}")
        if w.get("type") not in ("metric", "report"):
            raise HTTPException(status_code=400, detail="Widget type is metric or report")
    tenant = require_current_tenant()
    row = db.query(Dashboard).filter(Dashboard.tenant_id == tenant.tenant_id, Dashboard.code == payload.code).first()
    if row is None:
        row = Dashboard(tenant_id=tenant.tenant_id, code=payload.code, name=payload.name)
        db.add(row)
    row.name, row.audience_role, row.widgets_json = payload.name, payload.audience_role, payload.widgets
    db.commit()
    return {"id": str(row.id)}


@router.get("/dashboards/mine")
def my_dashboards(db: Session = Depends(get_db), current_user: User = Depends(require("analytics.dashboard.view"))):
    """Dashboards for the caller's roles, each widget already computed with the caller's scope."""
    tenant = require_current_tenant()
    roles = set(role_names_for(db, tenant, current_user))
    scope = employee_ids_in_scope(db, tenant, current_user, "analytics.metrics.view")
    out = []
    for board in db.query(Dashboard).filter(Dashboard.tenant_id == tenant.tenant_id).all():
        if board.audience_role and board.audience_role not in roles:
            continue
        widgets = []
        for w in board.widgets_json or []:
            if w.get("type") == "metric":
                widgets.append({**w, "data": metrics.compute(db, tenant, w["metric"], scope=scope)})
            else:
                widgets.append(w)
        out.append({"code": board.code, "name": board.name, "widgets": widgets})
    return out


@router.get("/predictive/attrition/{employee_id}")
def predictive_attrition(employee_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("analytics.predictive.view"))):
    from app.models.core_hr import Employee

    tenant = require_current_tenant()
    scope = employee_ids_in_scope(db, tenant, current_user, "analytics.predictive.view")
    if scope is not None and employee_id not in scope:
        raise HTTPException(status_code=404, detail="Employee not found")
    try:
        return predictive.attrition_risk(db, tenant, _get(db, Employee, employee_id, "Employee"))
    except governance.AIDisabledError as exc:
        raise _ai_error(exc)


@router.get("/predictive/time-to-fill")
def predictive_ttf(db: Session = Depends(get_db), current_user: User = Depends(require("analytics.predictive.view"))):
    try:
        return predictive.time_to_fill_forecast(db, require_current_tenant())
    except governance.AIDisabledError as exc:
        raise _ai_error(exc)


@router.get("/predictive/headcount-plan")
def predictive_plan(db: Session = Depends(get_db), current_user: User = Depends(require("analytics.predictive.view"))):
    try:
        return predictive.headcount_plan_vs_actual(db, require_current_tenant())
    except governance.AIDisabledError as exc:
        raise _ai_error(exc)


# ---- HR Copilot ----


class CopilotAsk(BaseModel):
    question: str
    language: str = "en"
    conversation_id: Optional[UUID] = None


@router.post("/copilot/ask")
def copilot_ask(payload: CopilotAsk, db: Session = Depends(get_db), current_user: User = Depends(require("copilot.chat.view"))):
    try:
        return CopilotService(db, require_current_tenant(), current_user).ask(payload.question, language=payload.language, conversation_id=payload.conversation_id)
    except CopilotError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except (governance.AIDisabledError, governance.BudgetExceededError) as exc:
        raise _ai_error(exc)
    except Exception as exc:
        raise _ai_error(exc)


class DraftConfirm(BaseModel):
    overrides: dict = {}


@router.post("/copilot/drafts/{draft_id}/confirm")
def copilot_confirm(draft_id: UUID, payload: DraftConfirm, db: Session = Depends(get_db), current_user: User = Depends(require("copilot.chat.view"))):
    from app.copilot.tools import ToolPermissionError

    try:
        draft = CopilotService(db, require_current_tenant(), current_user).confirm_draft(draft_id, overrides=payload.overrides)
    except CopilotError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ToolPermissionError as exc:
        raise HTTPException(status_code=403, detail=f"Missing permission: {exc}")
    return {"id": str(draft.id), "status": draft.status, "result": draft.result_ref, "error": draft.error}


@router.post("/copilot/drafts/{draft_id}/discard")
def copilot_discard(draft_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("copilot.chat.view"))):
    CopilotService(db, require_current_tenant(), current_user).discard_draft(draft_id)
    return {"ok": True}


class KnowledgeUpload(BaseModel):
    title: str
    body: str
    language: str = "en"
    audience_role_names: list[str] = []


@router.post("/copilot/knowledge", status_code=201)
def upload_knowledge(payload: KnowledgeUpload, db: Session = Depends(get_db), current_user: User = Depends(require("copilot.knowledge.configure"))):
    try:
        document = retrieval.ingest(db, require_current_tenant(), title=payload.title, body=payload.body, language=payload.language,
                                    audience_role_names=payload.audience_role_names, uploaded_by=current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": str(document.id)}


@router.get("/copilot/knowledge")
def list_knowledge(db: Session = Depends(get_db), current_user: User = Depends(require("copilot.knowledge.view"))):
    tenant = require_current_tenant()
    rows = db.query(KnowledgeDocument).filter(KnowledgeDocument.tenant_id == tenant.tenant_id, KnowledgeDocument.status == "active").order_by(KnowledgeDocument.created_at.desc()).all()
    return [{"id": str(d.id), "title": d.title, "language": d.language, "source": d.source, "audience_role_names": d.audience_role_names} for d in rows]


@router.post("/copilot/knowledge/{document_id}/retire")
def retire_knowledge(document_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require("copilot.knowledge.configure"))):
    document = _get(db, KnowledgeDocument, document_id, "Document")
    document.status = "retired"  # kept for the audit trail of answers that cited it
    db.commit()
    return {"ok": True}


# ---- agents ----


@router.get("/agents/inbox")
def agent_inbox(db: Session = Depends(get_db), current_user: User = Depends(require("agents.suggestion.view"))):
    return [agents.suggestion_to_dict(s) for s in agents.inbox(db, require_current_tenant(), current_user)]


class SuggestionDecision(BaseModel):
    action: str
    edited_payload: Optional[dict] = None


@router.post("/agents/suggestions/{suggestion_id}/decision")
def agent_decide(suggestion_id: UUID, payload: SuggestionDecision, db: Session = Depends(get_db), current_user: User = Depends(require("agents.suggestion.view"))):
    try:
        row = agents.decide(db, require_current_tenant(), _get(db, AgentSuggestion, suggestion_id, "Suggestion"), user=current_user, **payload.model_dump())
    except agents.AgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=f"Missing permission: {exc}")
    return agents.suggestion_to_dict(row)


class AgentRun(BaseModel):
    agent: str
    task: str
    entity_id: Optional[UUID] = None
    title: Optional[str] = None
    text: Optional[str] = None


@router.post("/agents/run", status_code=201)
def agent_run(payload: AgentRun, db: Session = Depends(get_db), current_user: User = Depends(require("agents.run.create"))):
    tenant = require_current_tenant()
    tasks = {
        ("recruiter", "jd_draft"): lambda: [agents.recruiter_jd_draft(db, tenant, payload.entity_id)],
        ("recruiter", "interview_kit"): lambda: [agents.recruiter_interview_kit(db, tenant, payload.entity_id)],
        ("recruiter", "sourcing_shortlist"): lambda: [s for s in [agents.recruiter_sourcing_shortlist(db, tenant, payload.entity_id)] if s],
        ("onboarding", "chase_documents"): lambda: agents.onboarding_chase_documents(db, tenant),
        ("helpdesk_triage", "triage"): lambda: [agents.helpdesk_triage(db, tenant, payload.entity_id)],
        ("policy_checker", "review"): lambda: [agents.policy_check(db, tenant, title=payload.title or "Draft policy", text_body=payload.text or "")],
    }
    task = tasks.get((payload.agent, payload.task))
    if task is None:
        raise HTTPException(status_code=400, detail=f"Unknown agent task. Available: {sorted(f'{a}.{t}' for a, t in tasks)}")
    try:
        created = task()
    except agents.AgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except (governance.AIDisabledError, governance.BudgetExceededError) as exc:
        raise _ai_error(exc)
    except Exception as exc:
        raise _ai_error(exc)
    return [agents.suggestion_to_dict(s) for s in created]


# ---- AI governance ----


@router.get("/ai/features")
def ai_features(db: Session = Depends(get_db), current_user: User = Depends(require("ai.governance.view"))):
    tenant = require_current_tenant()
    flags = governance.feature_flags(db, tenant)
    return {"enabled": flags["enabled"], "features": [{"code": c, "module": m, "label": l, "enabled": flags["features"][c]} for c, (m, l) in governance.AI_FEATURES.items()]}


@router.get("/ai/usage")
def ai_usage(db: Session = Depends(get_db), current_user: User = Depends(require("ai.governance.view"))):
    tenant = require_current_tenant()
    usage = governance.usage_this_period(db, tenant)
    budget = governance.budget_for(db, tenant, usage["period"])
    return {**usage, "budget": {"token_limit": budget.token_limit, "cost_limit": float(budget.cost_limit) if budget.cost_limit is not None else None,
                                "alert_pct": budget.alert_pct, "exhausted": budget.exhausted_at is not None} if budget else None}


class BudgetUpsert(BaseModel):
    period: Optional[str] = None
    token_limit: Optional[int] = None
    cost_limit: Optional[float] = None
    alert_pct: int = 80


@router.put("/ai/budget")
def ai_budget(payload: BudgetUpsert, db: Session = Depends(get_db), current_user: User = Depends(require("ai.governance.configure"))):
    tenant = require_current_tenant()
    period = payload.period or governance.current_period()
    row = governance.budget_for(db, tenant, period)
    if row is None:
        row = AiUsageBudget(tenant_id=tenant.tenant_id, period=period)
        db.add(row)
    row.token_limit, row.cost_limit, row.alert_pct = payload.token_limit, payload.cost_limit, payload.alert_pct
    row.exhausted_at = None  # raising a limit re-opens the period
    db.commit()
    return {"period": period}


@router.get("/ai/decision-log")
def decision_log(feature: Optional[str] = None, limit: int = 100, db: Session = Depends(get_db), current_user: User = Depends(require("ai.decision_log.view"))):
    tenant = require_current_tenant()
    query = db.query(AiDecisionLog).filter(AiDecisionLog.tenant_id == tenant.tenant_id)
    if feature:
        query = query.filter(AiDecisionLog.feature == feature)
    rows = query.order_by(AiDecisionLog.created_at.desc()).limit(min(limit, 500)).all()
    return [{"id": str(r.id), "feature": r.feature, "purpose": r.purpose, "model": r.model, "prompt_key": r.prompt_key, "prompt_version": r.prompt_version,
             "input_refs": r.input_refs_json, "redactions": r.redactions_json, "status": r.status, "human_reviewer": r.human_reviewer,
             "final_decision": r.final_decision, "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]


class FixtureCreate(BaseModel):
    prompt_key: str
    name: str
    input_text: str
    expectations: dict


@router.post("/ai/prompt-fixtures", status_code=201)
def create_fixture(payload: FixtureCreate, db: Session = Depends(get_db), current_user: User = Depends(require("ai.governance.configure"))):
    row = PromptEvalFixture(tenant_id=require_current_tenant().tenant_id, prompt_key=payload.prompt_key, name=payload.name,
                            input_text=payload.input_text, expectations_json=payload.expectations)
    db.add(row)
    db.commit()
    return {"id": str(row.id)}


@router.post("/ai/prompt-fixtures/{prompt_key}/run")
def run_fixtures(prompt_key: str, version: Optional[int] = None, db: Session = Depends(get_db), current_user: User = Depends(require("ai.governance.configure"))):
    try:
        return prompt_eval.run(db, require_current_tenant(), prompt_key=prompt_key, version=version)
    except KeyError:
        raise HTTPException(status_code=404, detail="Prompt not found")
