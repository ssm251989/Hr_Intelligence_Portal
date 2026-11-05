"""Automatic hiring agents: Screening, Sourcing, Salary, Documents, BGV and Offer.

Each handler takes (db, tenant, application, run) and is safe to call again: it looks at the
application's CURRENT state, does nothing when the step is already done, and records what it did.
Decisions happen only inside a company rule (autopilot.rules.*); otherwise a card is raised.
"""

import json
import re
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.hr_agents.autopilot.core import ACTOR, Run, card, enabled, job_people, names, notify, record, recently, rule

# ---------------------------------------------------------------- Screening agent


def screen(db: Session, tenant, application, run: Run) -> Optional[str]:
    """New application -> screened now (if its resume is read); a screened one -> the shortlist rule."""
    if not enabled(db, tenant, "screening", "screening"):
        return None
    from app.screening.service import attempt_auto_screen, is_eligible_for_screening

    n = names(db, application)
    if is_eligible_for_screening(application):
        result = attempt_auto_screen(db, application, actor=ACTOR)
        if result is None:
            return None  # resume not read yet / job has no JD: the next event or sweep tries again
        db.refresh(application)
        record(db, tenant, run, agent="screening", action="screen", outcome="done", entity_type="application", entity_id=application.id,
               summary=f"Screened {n['candidate']} for {n['job']}: score {round(float(application.composite_score or 0))}.",
               details={"score": application.composite_score, "status": application.status})
    return shortlist_rule(db, tenant, application, run)


def shortlist_rule(db: Session, tenant, application, run: Run) -> Optional[str]:
    from app.models.job_role import JobRole
    from app.recruitment.scoring.autoshortlist import maybe_auto_shortlist

    threshold = int(rule(db, tenant, "shortlist_min_score") or 0)
    if threshold <= 0 or application.status != "screened":
        return None
    job = db.get(JobRole, application.job_role_id)
    knocked = bool((application.score_breakdown or {}).get("knocked_out")) if isinstance(application.score_breakdown, dict) else False
    if job is None or not maybe_auto_shortlist(db, tenant, application, job=job, threshold=threshold, knocked_out=knocked, actor=ACTOR,
                                               override={"auto_shortlist": True, "threshold": threshold}):
        return None
    n = names(db, application)
    record(db, tenant, run, agent="screening", action="auto_shortlist", outcome="decided", rule_key="autopilot.rules.shortlist_min_score",
           entity_type="application", entity_id=application.id,
           summary=f"Shortlisted {n['candidate']} for {n['job']} (score {round(float(application.composite_score or 0))} >= {threshold}); "
                   "the recruiter can undo it during the undo window.")
    return "decided"


# ---------------------------------------------------------------- Sourcing agent


def source_thin_jobs(db: Session, tenant, run: Run) -> int:
    """Daily: open jobs (live 3+ days) with fewer strong candidates than autopilot.sourcing.min_strong get a
    proposal of matching people already in the talent pool (the existing suitability matches)."""
    if not enabled(db, tenant, "sourcing", "candidates"):
        return 0
    from datetime import datetime, timezone

    from sqlalchemy import func

    from app.agents.service import recruiter_sourcing_shortlist
    from app.models.application import Application
    from app.models.job_role import JobRole

    need = int(_setting(db, tenant, "autopilot.sourcing.min_strong") or 0)
    if need <= 0:
        return 0
    strong_at = int(rule(db, tenant, "shortlist_min_score") or 0) or 70
    cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    done = 0
    for job in db.query(JobRole).filter(JobRole.tenant_id == tenant.tenant_id, JobRole.status == "published", JobRole.created_at <= cutoff).all():
        strong = db.query(func.count(Application.id)).filter(Application.job_role_id == job.id, Application.removed_at.is_(None),
                                                             Application.composite_score >= strong_at).scalar() or 0
        if strong >= need or recently(db, tenant, agent="sourcing", action="propose_pool", entity_id=job.id, hours=24 * 7):
            continue
        sug = recruiter_sourcing_shortlist(db, tenant, job.id, limit=10)
        if sug is None:
            record(db, tenant, run, agent="sourcing", action="propose_pool", outcome="skipped", entity_type="job_role", entity_id=job.id,
                   summary=f"{job.title}: only {strong} strong candidate(s) and nobody matching in the talent pool - consider more job boards.")
            continue
        notify(db, tenant, job_people(db, tenant, job), f"{job.title}: {len(sug.payload_json.get('candidates', []))} people from your talent pool may fit - see My approvals.",
               "/approvals", entity_type="job_role", entity_id=job.id)
        record(db, tenant, run, agent="sourcing", action="propose_pool", outcome="proposed", entity_type="job_role", entity_id=job.id,
               summary=f"{job.title} has only {strong} strong candidate(s); proposed {len(sug.payload_json.get('candidates', []))} from the talent pool.",
               details={"card_id": str(sug.id)})
        done += 1
    return done


def _setting(db, tenant, key):
    from app.hr_agents.autopilot.core import setting

    return setting(db, tenant, key)


# ---------------------------------------------------------------- Salary agent


def salary(db: Session, tenant, application, run: Run) -> Optional[str]:
    """Figures arrived and the existing check put the candidate above the band -> the over-band rule, else a card."""
    if not enabled(db, tenant, "salary", "salary") or application.status != "salary_above_band":
        return None
    from app.recruitment import salary_auto

    chk = dict(application.salary_check or {})
    expected, band_max = _f(chk.get("expected") or application.expected_salary), _f(chk.get("band_max"))
    n = names(db, application)
    limit = int(rule(db, tenant, "salary_max_over_band_pct") or 0)
    over = round((expected - band_max) / band_max * 100, 1) if expected and band_max else None
    if limit > 0 and over is not None and over <= limit:
        try:
            salary_auto.decide(db, tenant, application, decision="approve", actor=ACTOR, amount=expected,
                               reason=f"Autopilot rule: {over}% above the band (limit {limit}%)")
        except ValueError as exc:  # e.g. the department budget would be exceeded -> HR decides
            db.rollback()
            return _salary_card(db, tenant, application, run, n, expected, band_max, over, why=str(exc))
        record(db, tenant, run, agent="salary", action="salary_rule_approve", outcome="decided", rule_key="autopilot.rules.salary_max_over_band_pct",
               entity_type="application", entity_id=application.id,
               summary=f"Approved {n['candidate']}'s salary of {expected:,.0f} for {n['job']} ({over}% above the band, rule allows {limit}%).")
        return "decided"
    return _salary_card(db, tenant, application, run, n, expected, band_max, over,
                        why=f"{over}% above the band" + (f" (rule allows {limit}%)" if limit else "") if over is not None else "figures incomplete")


def _salary_card(db, tenant, application, run, n, expected, band_max, over, *, why: str) -> str:
    if band_max and expected and expected > band_max:
        decision, amount, reason = "counter", band_max, f"Expected {expected:,.0f} is {over}% above the band maximum {band_max:,.0f}."
    else:
        decision, amount, reason = "approve", expected, "Check the figures before approving."
    c = card(db, tenant, kind="agent_salary_decision", by_agent="salary", title=f"Salary {decision} for {n['candidate']}",
             payload={**n, "decision": decision, "amount": amount, "reason": reason, "salary_check": application.salary_check or {}},
             permission="recruitment.salary.edit", entity_type="application", entity_id=application.id)
    record(db, tenant, run, agent="salary", action="propose_salary", outcome="proposed", entity_type="application", entity_id=application.id,
           summary=f"{n['candidate']} ({n['job']}): proposed a {decision}{f' at {amount:,.0f}' if amount else ''} for HR - {why}.",
           details={"card_id": str(c.id)})
    return "proposed"


# ---------------------------------------------------------------- Documents agent


def documents(db: Session, tenant, application, run: Run) -> Optional[str]:
    if not enabled(db, tenant, "documents", "bgv") or application.status != "salary_approved":
        return None
    from app.recruitment import joining_docs

    st = joining_docs.status(db, tenant, application)
    if not st["all_received"] or st["all_approved"]:
        return None
    n = names(db, application)
    mismatches = joining_docs.cross_check(db, tenant, application)
    clean = st["reds"] == 0 and st["ambers"] == 0 and not mismatches
    if clean and rule(db, tenant, "documents_auto_approve"):
        out = joining_docs.approve(db, tenant, application, actor=ACTOR)
        record(db, tenant, run, agent="documents", action="documents_rule_approve", outcome="decided",
               rule_key="autopilot.rules.documents_auto_approve", entity_type="application", entity_id=application.id,
               summary=f"Approved {n['candidate']}'s {out['approved']} joining document(s) - all in, no AI flag, name and date of birth match"
                       f"{'; BGV started' if out.get('moved_to_bgv') else ''}.")
        return "decided"
    flags = [f"{i['label']}: {i['level']}" for i in st["items"] if i.get("level") in ("red", "amber")] + [m["code"] for m in mismatches]
    c = card(db, tenant, kind="agent_documents_approve", by_agent="documents", title=f"Approve documents of {n['candidate']} and start BGV",
             payload={**n, "note": "; ".join(flags) or None, "red_flags": st["reds"], "amber_flags": st["ambers"]},
             permission="recruitment.bgv.edit", entity_type="application", entity_id=application.id)
    record(db, tenant, run, agent="documents", action="propose_documents", outcome="proposed", entity_type="application", entity_id=application.id,
           summary=f"All documents of {n['candidate']} are in" + (f"; check: {', '.join(flags)}." if flags else "; nothing flagged.") + " Waiting for HR.",
           details={"card_id": str(c.id), "flags": flags})
    return "proposed"


# ---------------------------------------------------------------- BGV agent


def bgv_assign(db: Session, tenant, application, run: Run) -> Optional[str]:
    if not enabled(db, tenant, "bgv", "bgv") or application.status not in ("bgv_requested", "bgv_pending"):
        return None
    from app.bgv import vendors

    if vendors.current(db, application.id) is not None:
        return None
    options = [v for v in vendors.vendors(db, tenant) if v.get("checks")]
    n = names(db, application)
    if not options:
        if not recently(db, tenant, agent="bgv", action="no_vendor", entity_id=application.id):
            notify(db, tenant, job_people(db, tenant, _job(db, application)), f"BGV for {n['candidate']} can't start: no BGV vendor is set up.",
                   "/agencies", entity_type="application", entity_id=application.id)
            record(db, tenant, run, agent="bgv", action="no_vendor", outcome="escalated", entity_type="application", entity_id=application.id,
                   summary=f"No active BGV vendor for {n['candidate']} - told HR to add one under Agencies.")
        return "escalated"
    best = sorted(options, key=lambda v: (v.get("turnaround_days") or 99, v["name"]))[0]
    due = date.today() + timedelta(days=int(best.get("turnaround_days") or 7))
    checks = list(best.get("checks") or [])
    if rule(db, tenant, "bgv_auto_assign_vendor"):
        from uuid import UUID

        try:
            vendors.assign(db, tenant, application, agency_id=UUID(best["id"]), checks=checks, due_date=due, actor=ACTOR)
        except ValueError as exc:
            db.rollback()
            record(db, tenant, run, agent="bgv", action="assign_vendor", outcome="failed", entity_type="application", entity_id=application.id,
                   summary=f"Could not send {n['candidate']}'s BGV to {best['name']}: {exc}")
            return "failed"
        record(db, tenant, run, agent="bgv", action="assign_vendor", outcome="decided", rule_key="autopilot.rules.bgv_auto_assign_vendor",
               entity_type="application", entity_id=application.id,
               summary=f"Sent {n['candidate']}'s BGV to {best['name']} (fastest vendor, due {due.isoformat()}).")
        return "decided"
    c = card(db, tenant, kind="agent_bgv_assign", by_agent="bgv", title=f"Send {n['candidate']}'s BGV to {best['name']}",
             payload={**n, "agency_id": best["id"], "vendor": best["name"], "checks": checks, "due_date": due.isoformat()},
             permission="recruitment.bgv.edit", entity_type="application", entity_id=application.id)
    record(db, tenant, run, agent="bgv", action="propose_vendor", outcome="proposed", entity_type="application", entity_id=application.id,
           summary=f"Proposed sending {n['candidate']}'s BGV to {best['name']} (due {due.isoformat()}).", details={"card_id": str(c.id)})
    return "proposed"


READER_SYSTEM = (
    "You read background verification (BGV) reports for an HR team. Classify the overall result and answer ONLY with JSON: "
    '{"verdict": "clear" | "discrepancy" | "adverse" | "unclear", "confidence": 0.0-1.0, "summary": "one or two plain sentences", '
    '"findings": ["each check and its result"]}. "clear" only when every check in the report is verified with no remark; '
    "a mismatch in dates, designation or salary is a discrepancy; criminal records, fake documents or refused verification are adverse; "
    "if the text is missing, unreadable or does not look like a BGV report, answer unclear. Never guess."
)


def read_report(db: Session, tenant, assignment) -> dict:
    """AI reading of the vendor's report (feature agents.bgv_reader). Never raises: unclear on any problem."""
    from app.bgv import vendors
    from app.bgv.document_extraction import extract_bgv_text
    from app.platform.ai import governance

    path = vendors.report_file(assignment)
    if path is None:
        return {"verdict": "unclear", "confidence": 0, "summary": "The report file is missing.", "findings": []}
    try:
        text = extract_bgv_text(path.read_bytes(), assignment.report_name or path.name)
    except Exception as exc:  # noqa: BLE001
        return {"verdict": "unclear", "confidence": 0, "summary": f"The report could not be read ({type(exc).__name__}).", "findings": []}
    note = f"\n\nVendor's note: {assignment.report_note}" if assignment.report_note else ""
    try:
        res = governance.governed_complete(db, tenant, feature="agents.bgv_reader", purpose="llm.judgment", system=READER_SYSTEM,
                                           messages=[{"role": "user", "content": f"BGV report text:\n{(text or '')[:15000]}{note}"}],
                                           input_refs={"bgv_assignment_id": str(assignment.id)}, max_tokens=700)
    except Exception as exc:  # noqa: BLE001 -- AI off / budget / provider error -> HR reads it
        return {"verdict": "unclear", "confidence": 0, "summary": f"AI reading not available ({type(exc).__name__}).", "findings": []}
    return parse_verdict(res.text)


def parse_verdict(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except ValueError:
        data = {}
    verdict = data.get("verdict") if data.get("verdict") in ("clear", "discrepancy", "adverse", "unclear") else "unclear"
    try:
        conf = max(0.0, min(1.0, float(data.get("confidence") or 0)))
    except (TypeError, ValueError):
        conf = 0.0
    return {"verdict": verdict, "confidence": conf, "summary": str(data.get("summary") or "")[:600],
            "findings": [str(f)[:200] for f in (data.get("findings") or [])][:12]}


def bgv_report(db: Session, tenant, application, run: Run) -> Optional[str]:
    if not enabled(db, tenant, "bgv", "bgv") or application.status not in ("bgv_requested", "bgv_pending"):
        return None
    from app.bgv import vendors
    from app.recruitment import bgv_decision

    a = vendors.current(db, application.id)
    if a is None or a.status != "report_received" or recently(db, tenant, agent="bgv", action="read_report", entity_id=application.id, hours=12):
        return None
    n = names(db, application)
    v = read_report(db, tenant, a)
    record(db, tenant, run, agent="bgv", action="read_report", outcome="done", entity_type="application", entity_id=application.id,
           summary=f"Read {n['candidate']}'s BGV report: {v['verdict']} ({round(v['confidence'] * 100)}% sure). {v['summary']}", details=v)
    if v["verdict"] == "clear" and v["confidence"] >= 0.9 and rule(db, tenant, "bgv_auto_pass_clear_report"):
        try:
            bgv_decision.decide(db, tenant, application, decision="passed", actor=ACTOR, note=f"Autopilot: report read as clear. {v['summary']}"[:1000])
        except ValueError as exc:
            db.rollback()
            record(db, tenant, run, agent="bgv", action="bgv_rule_pass", outcome="failed", entity_type="application", entity_id=application.id,
                   summary=f"Could not mark {n['candidate']}'s BGV passed: {exc}")
            return "failed"
        record(db, tenant, run, agent="bgv", action="bgv_rule_pass", outcome="decided", rule_key="autopilot.rules.bgv_auto_pass_clear_report",
               entity_type="application", entity_id=application.id, summary=f"Marked {n['candidate']}'s BGV passed - the report is fully clear.")
        offer(db, tenant, application, Run("event", "bgv_passed"))
        return "decided"
    decision = {"clear": "passed", "discrepancy": "discrepancy", "adverse": "failed"}.get(v["verdict"])
    payload = {**n, "decision": decision or "passed", "ai_reading": v,
               "note": v["summary"] if decision == "discrepancy" else None, "reason": v["summary"] if decision == "failed" else None}
    c = card(db, tenant, kind="agent_bgv_decision", by_agent="bgv",
             title=f"BGV result for {n['candidate']}: AI reads it as {v['verdict']} - please confirm",
             payload=payload, permission="recruitment.bgv.edit", entity_type="application", entity_id=application.id)
    record(db, tenant, run, agent="bgv", action="propose_bgv_result", outcome="proposed", entity_type="application", entity_id=application.id,
           summary=f"Asked HR to decide {n['candidate']}'s BGV (AI reading: {v['verdict']}).", details={"card_id": str(c.id)})
    return "proposed"


# ---------------------------------------------------------------- Offer agent


def joining_dates_for(db: Session, tenant, application, today: Optional[date] = None) -> list[str]:
    """Three working days (Mon-Fri), starting after the rule's lead time or the candidate's notice period, whichever is longer."""
    from app.models.candidate import Candidate

    today = today or date.today()
    cand = db.get(Candidate, application.candidate_id)
    lead = max(int(rule(db, tenant, "joining_dates_after_days") or 14), int(getattr(cand, "notice_period_days", 0) or 0))
    d, out = today + timedelta(days=lead), []
    while len(out) < 3:  # e.g. Mon, Wed, Fri -- two days apart, weekends skipped
        if d.weekday() < 5:
            out.append(d.isoformat())
            d += timedelta(days=2)
        else:
            d += timedelta(days=1)
    return out


def offer(db: Session, tenant, application, run: Run) -> Optional[str]:
    if not enabled(db, tenant, "offer", "offers") or application.status != "bgv_cleared":
        return None
    from app.recruitment import joining_dates

    if joining_dates.info(application).get("proposed"):
        return None
    n = names(db, application)
    dates = joining_dates_for(db, tenant, application)
    if rule(db, tenant, "joining_dates_auto"):
        try:
            joining_dates.propose(db, tenant, application, dates, actor=ACTOR, note=None)
        except ValueError as exc:
            db.rollback()
            record(db, tenant, run, agent="offer", action="joining_dates_rule", outcome="failed", entity_type="application", entity_id=application.id,
                   summary=f"Could not send joining dates to {n['candidate']}: {exc}")
            return "failed"
        record(db, tenant, run, agent="offer", action="joining_dates_rule", outcome="decided", rule_key="autopilot.rules.joining_dates_auto",
               entity_type="application", entity_id=application.id, summary=f"Emailed {n['candidate']} three joining dates: {', '.join(dates)}.")
        return "decided"
    c = card(db, tenant, kind="agent_joining_dates", by_agent="offer", title=f"Offer joining dates to {n['candidate']}",
             payload={**n, "dates": dates, "note": None}, permission="recruitment.offer.edit", entity_type="application", entity_id=application.id)
    record(db, tenant, run, agent="offer", action="propose_joining_dates", outcome="proposed", entity_type="application", entity_id=application.id,
           summary=f"BGV passed for {n['candidate']}; proposed joining dates {', '.join(dates)} for HR to send.", details={"card_id": str(c.id)})
    return "proposed"


def _f(v) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _job(db, application):
    from app.models.job_role import JobRole

    return db.get(JobRole, application.job_role_id)
