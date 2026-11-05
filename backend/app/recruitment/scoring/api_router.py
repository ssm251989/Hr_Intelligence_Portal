"""Part 17.4-17.6 API: scoring rules (company default + per-job override), live preview,
versions + revert, recalculation progress, export/import, "Why this score", and the
per-job shortlisting rules.

- GET  /api/v1/scoring/catalog                     factors, knock-out types, presets
- GET  /api/v1/scoring/rules?job_id=               rules in use (+ where from, threshold, versions)
- PUT  /api/v1/scoring/rules?job_id=               save a new version -> recalculation run
- POST /api/v1/scoring/rules/revert                save an old version again (new version)
- DELETE /api/v1/scoring/rules?job_id=             job goes back to the company rules
- POST /api/v1/scoring/balance                     auto-balance weights to 100
- POST /api/v1/scoring/preview                     score up to 3 candidates with unsaved rules
- GET  /api/v1/scoring/runs/{id}                   recalculation progress
- GET  /api/v1/scoring/export?job_id=&format=json|xlsx
- POST /api/v1/scoring/import                      json body or .json/.xlsx upload -> rules (not saved)
- GET  /api/v1/scoring/applications/{id}/why       "Why this score"
- GET|PUT /api/v1/scoring/shortlisting?job_id=     shortlisting rules (company defaults or a job's)

Company rules need recruitment.pipeline.configure; a job's rules need recruitment.job.edit.
Every query filters on the current company's tenant_id explicitly.
"""

import io
import json
from typing import Any, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.scoring import ScoreRecalcRun, ScoringRuleSet
from app.models.user import User
from app.platform.iam.authz import has_permission
from app.platform.tenancy.context import require_current_tenant
from app.recruitment.scoring import engine
from app.recruitment.scoring.factors import FACTORS
from app.recruitment.scoring.rules import KNOCKOUT_TYPES, PRESET_NAMES, PRESETS, RulesError, auto_balance, normalise, validate

router = APIRouter(prefix="/api/v1/scoring", tags=["scoring"])


def _need(db, tenant, user, permission: str) -> None:
    if not has_permission(db, tenant, user, permission):
        raise HTTPException(status_code=403, detail=f"Missing permission: {permission}")


def _job(db, tenant, job_id: Optional[UUID]) -> Optional[JobRole]:
    if job_id is None:
        return None
    job = db.query(JobRole).filter(JobRole.tenant_id == tenant.tenant_id, JobRole.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _edit_permission(job_id: Optional[UUID]) -> str:
    return "recruitment.job.edit" if job_id else "recruitment.pipeline.configure"


def _version_row(r: ScoringRuleSet) -> dict:
    return {"id": str(r.id), "version": r.version, "note": r.note, "created_by": r.created_by,
            "created_at": r.created_at.isoformat() if r.created_at else None}


@router.get("/catalog")
def catalog(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    _need(db, tenant, current_user, "recruitment.job.view")
    return {
        "factors": [{"key": k, "name": name} for k, (_fn, name) in FACTORS.items()],
        "knockout_types": list(KNOCKOUT_TYPES),
        "presets": [{"key": k, "name": PRESET_NAMES[k], "rules": v} for k, v in PRESETS.items()],
        "company_threshold": engine.company_threshold(db, tenant),
    }


@router.get("/rules")
def get_rules(job_id: Optional[UUID] = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    _need(db, tenant, current_user, "recruitment.job.view")
    job = _job(db, tenant, job_id)
    rules, row, source = engine.rules_for_job(db, tenant, job)
    threshold, threshold_from = engine.threshold_for_job(db, tenant, job, rules)
    q = db.query(ScoringRuleSet).filter(ScoringRuleSet.tenant_id == tenant.tenant_id)
    q = q.filter(ScoringRuleSet.job_role_id == job_id) if job_id else q.filter(ScoringRuleSet.job_role_id.is_(None))
    return {"rules": rules, "source": source, "version": row.version if row else None, "threshold": threshold,
            "threshold_from": threshold_from, "versions": [_version_row(r) for r in q.order_by(ScoringRuleSet.version.desc()).limit(50)],
            "can_edit": has_permission(db, tenant, current_user, _edit_permission(job_id))}


class RulesIn(BaseModel):
    rules: dict
    note: Optional[str] = Field(None, max_length=300)


def _save_and_recalc(db, tenant, job_id, rules, *, actor: str, note: Optional[str], background: BackgroundTasks) -> dict:
    try:
        row = engine.save_rules(db, tenant, job_id, rules, actor=actor, note=note)
    except RulesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_action(db, "scoring_rules", row.id, "scoring_rules_saved", actor[:50],
               {"job_id": str(job_id) if job_id else None, "version": row.version, "note": note})
    run = engine.start_recalc(db, tenant, job_id, row, actor[:50])
    background.add_task(engine.run_recalc, tenant.tenant_id, tenant.slug, tenant.isolation, run.id)
    return {"version": row.version, "id": str(row.id), "run": engine.run_to_dict(run)}


@router.put("/rules")
def put_rules(payload: RulesIn, background: BackgroundTasks, job_id: Optional[UUID] = None, db: Session = Depends(get_db),
              current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    _need(db, tenant, current_user, _edit_permission(job_id))
    _job(db, tenant, job_id)
    return _save_and_recalc(db, tenant, job_id, payload.rules, actor=current_user.email, note=payload.note, background=background)


class RevertIn(BaseModel):
    job_id: Optional[UUID] = None
    version: int = Field(..., ge=1)


@router.post("/rules/revert")
def revert_rules(payload: RevertIn, background: BackgroundTasks, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    _need(db, tenant, current_user, _edit_permission(payload.job_id))
    q = db.query(ScoringRuleSet).filter(ScoringRuleSet.tenant_id == tenant.tenant_id, ScoringRuleSet.version == payload.version)
    q = q.filter(ScoringRuleSet.job_role_id == payload.job_id) if payload.job_id else q.filter(ScoringRuleSet.job_role_id.is_(None))
    old = q.first()
    if old is None:
        raise HTTPException(status_code=404, detail="That version doesn't exist")
    return _save_and_recalc(db, tenant, payload.job_id, old.rules_json, actor=current_user.email,
                            note=f"Went back to version {old.version}", background=background)


@router.delete("/rules")
def use_company_rules(background: BackgroundTasks, job_id: UUID = Query(...), db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    """The job stops using its own rules (its versions are removed) and is rescored with the company's."""
    tenant = require_current_tenant()
    _need(db, tenant, current_user, "recruitment.job.edit")
    _job(db, tenant, job_id)
    rows = db.query(ScoringRuleSet).filter(ScoringRuleSet.tenant_id == tenant.tenant_id, ScoringRuleSet.job_role_id == job_id).all()
    for r in rows:
        db.delete(r)
    db.commit()
    log_action(db, "job_role", job_id, "scoring_rules_cleared", current_user.email[:50], {"versions_removed": len(rows)})
    run = engine.start_recalc(db, tenant, job_id, None, current_user.email[:50])
    background.add_task(engine.run_recalc, tenant.tenant_id, tenant.slug, tenant.isolation, run.id)
    return {"removed": len(rows), "run": engine.run_to_dict(run)}


@router.post("/balance")
def balance(payload: RulesIn, current_user: User = Depends(get_current_user)):
    return {"rules": auto_balance(payload.rules)}


class PreviewIn(BaseModel):
    job_id: UUID
    rules: dict
    application_ids: list[UUID] = Field(default_factory=list, max_length=3)


@router.post("/preview")
def preview(payload: PreviewIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Score up to 3 applications of the job with the rules on screen (nothing saved). No
    ids -> the 3 most recent scored applications of that job."""
    tenant = require_current_tenant()
    _need(db, tenant, current_user, "recruitment.application.view")
    job = _job(db, tenant, payload.job_id)
    rules = normalise(payload.rules)
    q = db.query(Application).filter(Application.tenant_id == tenant.tenant_id, Application.job_role_id == job.id)
    apps = (q.filter(Application.id.in_(payload.application_ids)).all() if payload.application_ids
            else q.order_by(Application.scored_at.desc().nullslast(), Application.created_at.desc()).limit(3).all())
    threshold, _ = engine.threshold_for_job(db, tenant, job, rules)
    out = []
    for app in apps:
        cand = db.get(Candidate, app.candidate_id)
        res = engine.compute(engine.gather(db, tenant, app, job, cand), rules)
        out.append({"application_id": str(app.id), "candidate_name": cand.full_name if cand else None,
                    "current_score": float(app.composite_score) if app.composite_score is not None else None,
                    "new_score": res["score"], "knocked_out": res["knocked_out"], "factors": res["factors"],
                    "above_threshold": res["score"] >= threshold and not res["knocked_out"]})
    total = sum(f["weight"] for f in rules["factors"].values() if f["enabled"])
    return {"threshold": threshold, "weights_total": total, "candidates": out}


@router.get("/runs/{run_id}")
def run_progress(run_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    run = db.query(ScoreRecalcRun).filter(ScoreRecalcRun.tenant_id == tenant.tenant_id, ScoreRecalcRun.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Not found")
    return engine.run_to_dict(run)


# ---------------------------------------------------------------- export / import

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/export")
def export_rules(job_id: Optional[UUID] = None, format: Literal["json", "xlsx"] = "json", db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    _need(db, tenant, current_user, "recruitment.job.view")
    job = _job(db, tenant, job_id)
    rules, row, source = engine.rules_for_job(db, tenant, job)
    doc = {"format": "hrms.scoring_rules", "format_version": 1, "source": source, "version": row.version if row else None,
           "job_title": job.title if job else None, "rules": rules}
    name = f"scoring-rules-{(job.title if job else 'company').lower().replace(' ', '-')[:40]}"
    if format == "json":
        data = json.dumps(doc, indent=2, ensure_ascii=False).encode()
        return StreamingResponse(io.BytesIO(data), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{name}.json"'})
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Factors"
    ws.append(["key", "factor", "enabled", "weight", "params (json)"])
    for key, (_fn, fname) in FACTORS.items():
        f = rules["factors"][key]
        ws.append([key, fname, "yes" if f["enabled"] else "no", f["weight"], json.dumps(f["params"]) if f["params"] else ""])
    ko = wb.create_sheet("Knockouts")
    ko.append(["type", "settings (json)"])
    for k in rules["knockouts"]:
        ko.append([k.get("type"), json.dumps({x: y for x, y in k.items() if x != "type"})])
    meta = wb.create_sheet("About")
    meta.append(["format", "hrms.scoring_rules"])
    meta.append(["shortlist_threshold", rules.get("shortlist_threshold") if rules.get("shortlist_threshold") is not None else ""])
    meta.append(["how to use", "Change 'enabled' (yes/no) and 'weight' (0-100, switched-on weights add up to 100), then import it on the Scoring rules page."])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type=_XLSX, headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})


def _rules_from_xlsx(data: bytes) -> dict:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    if "Factors" not in wb.sheetnames:
        raise RulesError("This file has no 'Factors' sheet. Start from an exported file.")
    factors: dict[str, Any] = {}
    for i, row in enumerate(wb["Factors"].iter_rows(values_only=True)):
        if i == 0 or not row or not row[0]:
            continue
        key = str(row[0]).strip()
        if key not in FACTORS:
            raise RulesError(f"Unknown factor '{key}' in row {i + 1}.")
        params = json.loads(row[4]) if len(row) > 4 and row[4] else {}
        factors[key] = {"enabled": str(row[2] or "").strip().lower() in ("yes", "y", "true", "1"), "weight": int(float(row[3] or 0)), "params": params}
    knockouts = []
    if "Knockouts" in wb.sheetnames:
        for i, row in enumerate(wb["Knockouts"].iter_rows(values_only=True)):
            if i == 0 or not row or not row[0]:
                continue
            knockouts.append({"type": str(row[0]).strip(), **(json.loads(row[1]) if len(row) > 1 and row[1] else {})})
    threshold = None
    if "About" in wb.sheetnames:
        for row in wb["About"].iter_rows(values_only=True):
            if row and row[0] == "shortlist_threshold" and row[1] not in (None, ""):
                threshold = int(float(row[1]))
    return {"factors": factors, "knockouts": knockouts, "shortlist_threshold": threshold}


@router.post("/import")
async def import_rules(request: Request, file: Optional[UploadFile] = File(None), current_user: User = Depends(get_current_user)):
    """Reads rules from an exported .json/.xlsx file (or a JSON body) and returns them checked
    -- NOT saved, so the person can look at them on screen first and then press Save."""
    try:
        if file is not None:
            data = await file.read()
            if (file.filename or "").lower().endswith(".xlsx"):
                rules = _rules_from_xlsx(data)
            else:
                doc = json.loads(data.decode("utf-8-sig"))
                rules = doc.get("rules", doc)
        else:
            doc = await request.json()
            rules = doc.get("rules", doc)
        return {"rules": validate(rules)}
    except RulesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"That file couldn't be read: {exc}") from exc


# ---------------------------------------------------------------- why this score

@router.get("/applications/{application_id}/why")
def why_this_score(application_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = require_current_tenant()
    _need(db, tenant, current_user, "recruitment.application.view")
    app = db.query(Application).filter(Application.tenant_id == tenant.tenant_id, Application.id == application_id).first()
    if app is None:
        raise HTTPException(status_code=404, detail="Application not found")
    job = db.get(JobRole, app.job_role_id)
    saved = app.score_breakdown
    if not saved:  # scored before Part 17 -> explain with today's rules (not saved)
        saved = engine.score_application(db, tenant, app, job=job, save=False)
        saved["not_saved"] = True
    threshold, threshold_from = engine.threshold_for_job(db, tenant, job, engine.rules_for_job(db, tenant, job)[0])
    # before Part 17 the stored score was the old fixed average -> show today's breakdown with its own total
    score = saved.get("score") if saved.get("not_saved") or app.composite_score is None else float(app.composite_score)
    return {**saved, "score": score, "stored_score": float(app.composite_score) if app.composite_score is not None else None,
            "threshold": threshold, "threshold_from": threshold_from, "scored_at": app.scored_at.isoformat() if app.scored_at else None,
            "above_threshold": (score or 0) >= threshold and not saved.get("knocked_out")}


# ---------------------------------------------------------------- shortlisting rules (17.6)

class ShortlistingIn(BaseModel):
    auto_shortlist: Optional[bool] = None
    threshold: Optional[int] = Field(None, ge=0, le=100)
    max_size: Optional[int] = Field(None, ge=0, le=10000)
    undo_hours: Optional[int] = Field(None, ge=0, le=72)
    notify: Optional[list[str]] = None
    use_company: bool = False  # job only: forget the job's own settings


@router.get("/shortlisting")
def get_shortlisting(job_id: Optional[UUID] = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.recruitment.scoring.autoshortlist import config

    tenant = require_current_tenant()
    _need(db, tenant, current_user, "recruitment.job.view")
    job = _job(db, tenant, job_id)
    cfg = config(db, tenant, job)
    if cfg.get("threshold") is None:
        cfg["threshold"] = engine.threshold_for_job(db, tenant, job, engine.rules_for_job(db, tenant, job)[0])[0]
    return {**cfg, "own": dict(job.shortlisting_json or {}) if job else None, "company_threshold": engine.company_threshold(db, tenant)}


@router.put("/shortlisting")
def put_shortlisting(payload: ShortlistingIn, job_id: Optional[UUID] = None, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    from app.platform.settings.resolver import SettingsService

    tenant = require_current_tenant()
    _need(db, tenant, current_user, _edit_permission(job_id))
    job = _job(db, tenant, job_id)
    values = payload.model_dump(exclude_unset=True, exclude={"use_company"})
    if job is not None:
        job.shortlisting_json = {} if payload.use_company else {**(job.shortlisting_json or {}), **values}
        db.commit()
    else:
        service = SettingsService(db)
        keymap = {"auto_shortlist": "recruitment.shortlisting.auto_shortlist", "max_size": "recruitment.shortlisting.max_size",
                  "undo_hours": "recruitment.shortlisting.undo_hours", "notify": "recruitment.shortlisting.notify",
                  "threshold": "recruitment.scoring.shortlist_threshold"}
        for key, value in values.items():
            if value is not None:
                service.set(keymap[key], value, scope_type="tenant", scope_id=None, actor=current_user.email, tenant=tenant)
    log_action(db, "job_role" if job else "shortlisting_rules", job.id if job else None, "shortlisting_rules_saved",
               current_user.email[:50], {"values": values, "use_company": payload.use_company})
    return get_shortlisting(job_id, db, current_user)
