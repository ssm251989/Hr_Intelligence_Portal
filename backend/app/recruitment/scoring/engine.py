"""Part 17.4/17.5: compute the one Match score (0-100) for an application.

Rules in use for a job = the job's latest rule version, else the company's latest, else
the built-in "Balanced" preset. Shortlist threshold = the job's own (shortlisting_json
.threshold, else its rules' shortlist_threshold), else the company setting
`recruitment.scoring.shortlist_threshold`.

score = sum(weight x factor score) / 100 over the switched-on factors (weights add up to
100). The breakdown ("Why this score") is stored on the application.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.scoring import ScoreRecalcRun, ScoringRuleSet
from app.recruitment.scoring.factors import FACTORS, Facts
from app.recruitment.scoring.rules import DEFAULT_PRESET, PRESETS, evaluate_knockouts, normalise, validate

OPEN_STATUSES = ("received", "screened", "hr_selected", "on_hold")  # still being decided -> rescored


def _tid(tenant):
    return tenant.tenant_id


def latest_rule_set(db: Session, tenant, job_id: Optional[UUID]) -> Optional[ScoringRuleSet]:
    q = db.query(ScoringRuleSet).filter(ScoringRuleSet.tenant_id == _tid(tenant))
    q = q.filter(ScoringRuleSet.job_role_id == job_id) if job_id else q.filter(ScoringRuleSet.job_role_id.is_(None))
    return q.order_by(ScoringRuleSet.version.desc()).first()


def rules_for_job(db: Session, tenant, job: Optional[JobRole]) -> tuple[dict, Optional[ScoringRuleSet], str]:
    """-> (rules, rule set row or None, where from: job | company | preset)."""
    if job is not None:
        row = latest_rule_set(db, tenant, job.id)
        if row is not None:
            return normalise(row.rules_json), row, "job"
    row = latest_rule_set(db, tenant, None)
    if row is not None:
        return normalise(row.rules_json), row, "company"
    return normalise(PRESETS[DEFAULT_PRESET]), None, "preset"


def company_threshold(db: Session, tenant) -> int:
    from app.platform.settings.resolver import SettingContext, SettingsService

    return int(SettingsService(db).get("recruitment.scoring.shortlist_threshold", SettingContext(tenant=tenant)))


def threshold_for_job(db: Session, tenant, job: Optional[JobRole], rules: Optional[dict] = None) -> tuple[int, str]:
    own = (job.shortlisting_json or {}).get("threshold") if job is not None else None
    if own is not None:
        return int(own), "job"
    if rules and rules.get("shortlist_threshold") is not None:
        return int(rules["shortlist_threshold"]), "job" if job is not None else "company"
    return company_threshold(db, tenant), "company"


def save_rules(db: Session, tenant, job_id: Optional[UUID], rules: dict, *, actor: str, note: Optional[str] = None) -> ScoringRuleSet:
    rules = validate(rules)
    last = latest_rule_set(db, tenant, job_id)
    row = ScoringRuleSet(tenant_id=_tid(tenant), job_role_id=job_id, version=(last.version + 1) if last else 1,
                         rules_json=rules, note=note, created_by=actor)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def gather(db: Session, tenant, application: Application, job: JobRole, candidate: Candidate) -> Facts:
    from app.platform.geo.service import resolve

    job_place = resolve(db, tenant, job.location)[0] if job.location else None
    cand_place = resolve(db, tenant, candidate.location)[0] if candidate.location else None
    ai = float(application.match_score) if application.match_score is not None else None
    return Facts(job=job, parsed=candidate.parsed_fields or {}, candidate=candidate, application=application,
                 ai_match=ai, job_place=job_place, candidate_place=cand_place)


def compute(facts: Facts, rules: dict) -> dict:
    """-> {"score", "factors": [...], "knockouts": [...], "knocked_out"} (nothing saved)."""
    rows, total = [], 0.0
    for key, (fn, name) in FACTORS.items():
        cfg = rules["factors"][key]
        if not cfg["enabled"]:
            continue
        try:
            res = fn(facts, cfg["params"])
        except Exception as exc:  # one broken factor must never break scoring
            from app.recruitment.scoring.factors import NEUTRAL, FactorResult

            res = FactorResult(NEUTRAL, f"could not be checked ({type(exc).__name__})", known=False)
        points = cfg["weight"] * max(0.0, min(100.0, res.score)) / 100
        total += points
        rows.append({"key": key, "name": name, "weight": cfg["weight"], "score": round(res.score), "value": res.value,
                     "points": round(points, 1), "evidence": res.evidence, "known": res.known})
    knockouts = evaluate_knockouts(rules.get("knockouts"), facts)
    return {"score": round(total, 1), "factors": rows, "knockouts": knockouts, "knocked_out": any(not k["passed"] for k in knockouts)}


def score_application(db: Session, tenant, application: Application, *, job: Optional[JobRole] = None,
                      candidate: Optional[Candidate] = None, rules: Optional[dict] = None,
                      rule_set: Optional[ScoringRuleSet] = None, save: bool = True) -> dict:
    job = job or db.get(JobRole, application.job_role_id)
    candidate = candidate or db.get(Candidate, application.candidate_id)
    if rules is None:
        rules, rule_set, _src = rules_for_job(db, tenant, job)
    result = compute(gather(db, tenant, application, job, candidate), rules)
    threshold, _ = threshold_for_job(db, tenant, job, rules)
    result["threshold"] = threshold
    result["rules_version"] = rule_set.version if rule_set else None
    result["rules_scope"] = ("job" if rule_set.job_role_id else "company") if rule_set else "preset"
    if save:
        application.composite_score = result["score"]
        application.score_breakdown = result
        application.knocked_out = result["knocked_out"]
        application.scored_at = datetime.now(timezone.utc)
        application.scoring_rule_set_id = rule_set.id if rule_set else None
        db.commit()
    return result


# ---------------------------------------------------------------- recalculation

def start_recalc(db: Session, tenant, job_id: Optional[UUID], rule_set: Optional[ScoringRuleSet], actor: str) -> ScoreRecalcRun:
    q = db.query(func.count(Application.id)).filter(Application.tenant_id == _tid(tenant), Application.status.in_(OPEN_STATUSES))
    if job_id:
        q = q.filter(Application.job_role_id == job_id)
    else:  # company rules only affect jobs without their own rules
        own = db.query(ScoringRuleSet.job_role_id).filter(ScoringRuleSet.tenant_id == _tid(tenant), ScoringRuleSet.job_role_id.isnot(None))
        q = q.filter(Application.job_role_id.notin_(own))
    run = ScoreRecalcRun(tenant_id=_tid(tenant), job_role_id=job_id, rule_set_id=rule_set.id if rule_set else None,
                         total=q.scalar() or 0, started_by=actor)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def run_recalc(tenant_id, slug: str, isolation: str, run_id: UUID) -> None:
    """Background task: rescore every open application in scope with the saved rules, and
    record old -> new per application in the audit log."""
    from app.audit.service import log_action
    from app.platform.tenancy.context import TenantContext, tenant_context
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
    from app.platform.tenancy.models_cp import Tenant
    from app.platform.tenancy.provisioning import tenant_session

    cp = ControlPlaneSessionLocal()
    try:
        tenant_row = cp.get(Tenant, tenant_id)
    finally:
        cp.close()
    ctx = TenantContext(tenant_id=tenant_id, slug=slug, isolation=isolation)
    with tenant_context(tenant_id, slug, isolation):
        db = tenant_session(tenant_row)
        try:
            run = db.get(ScoreRecalcRun, run_id)
            run.status = "running"
            db.commit()
            q = db.query(Application).filter(Application.tenant_id == tenant_id, Application.status.in_(OPEN_STATUSES))
            if run.job_role_id:
                q = q.filter(Application.job_role_id == run.job_role_id)
            else:
                own = db.query(ScoringRuleSet.job_role_id).filter(ScoringRuleSet.tenant_id == tenant_id, ScoringRuleSet.job_role_id.isnot(None))
                q = q.filter(Application.job_role_id.notin_(own))
            jobs: dict = {}
            for app in q.order_by(Application.created_at).all():
                job = jobs.get(app.job_role_id) or db.get(JobRole, app.job_role_id)
                jobs[app.job_role_id] = job
                old = float(app.composite_score) if app.composite_score is not None else None
                try:
                    new = score_application(db, ctx, app, job=job)["score"]
                except Exception as exc:  # keep going; report at the end
                    run.error = f"{type(exc).__name__}: {exc}"[:500]
                    run.done += 1
                    db.commit()
                    continue
                if old is None or abs(old - new) >= 0.1:
                    run.changed += 1
                    log_action(db, "application", app.id, "score_recalculated", run.started_by or "system",
                               {"old_score": old, "new_score": new, "rules_version": run.rule_set_id and str(run.rule_set_id), "run_id": str(run.id)})
                # Part 17.6: an updated score above the threshold may shortlist automatically
                try:
                    from app.recruitment.scoring.autoshortlist import maybe_auto_shortlist

                    rules = rules_for_job(db, ctx, job)[0]
                    maybe_auto_shortlist(db, ctx, app, job=job, threshold=threshold_for_job(db, ctx, job, rules)[0],
                                         knocked_out=bool(app.knocked_out), actor=(run.started_by or "system"))
                except Exception as exc:  # noqa: BLE001 -- never stops the recalculation
                    log_action(db, "application", app.id, "auto_shortlist_failed", "system", {"error": str(exc)[:300]})
                run.done += 1
                db.commit()
            run.status = "done"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
        except Exception as exc:
            db.rollback()
            run = db.get(ScoreRecalcRun, run_id)
            if run is not None:
                run.status, run.error, run.finished_at = "failed", f"{type(exc).__name__}: {exc}"[:500], datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()


def run_to_dict(run: ScoreRecalcRun) -> dict:
    return {"id": str(run.id), "status": run.status, "total": run.total, "done": run.done, "changed": run.changed,
            "error": run.error, "job_id": str(run.job_role_id) if run.job_role_id else None,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None}
