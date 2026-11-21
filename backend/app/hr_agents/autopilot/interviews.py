"""Part 30.3: the interview-outcome card (step 5 of the flow).

The interviewers still give their view on their own scorecard (ratings, notes, a recommendation); the Scheduling agent
prepares the hiring manager's decision. When every interviewer of the round has submitted (the event is each scorecard,
audit `interview_feedback_recorded`), the agent summarises the scorecards with the AI (feature agents.interview_summary,
names left out, the company's masking applied) - strengths, concerns, where the interviewers disagree, a suggested next
step - and raises "Interview result for <name>: <one line>" for the job's hiring manager (fallback: the job owner).

Approving applies the decision the hiring manager picks - Move forward / Reject (with a reason) / Another round - through
the same code as the feedback screen's decision (scheduling.router.record_decision, incl. the salary / documents stage
that follows). The default option is the interviewers' majority; a tie has none. A decision made on the screen first
closes the card (leftovers.py). No AI for the company -> the card still comes, with the scores only.

A round = the application's interviews not already covered by an earlier outcome card, so "Another round" leads to a new
card once the next interviews are in.
"""

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.hr_agents.autopilot.core import Run, card, enabled, names, notify, record, waiting_card

log = logging.getLogger(__name__)

KIND = "agent_interview_outcome"
# Deliberately NOT a registered permission: registering it would give it to every Hiring Manager through the role template
# (recruitment approve). So only the card's named reviewer decides - the job's hiring manager, or the job owner when none is set.
PERMISSION = "recruitment.interview.approve"
OPTIONS = ("move_forward", "reject", "another_round")
FROM_RECOMMENDATION = {"selected": "move_forward", "rejected": "reject", "another_round": "another_round"}
MISSING_AFTER = timedelta(hours=24)


def submitted(iv) -> bool:
    return any(v not in (None, "") for v in (iv.overall_rating, iv.technical_rating, iv.communication_rating, iv.comments, iv.recommendation))


def _covered(db: Session, tenant, application_id) -> set[str]:
    """Interview ids already put before the hiring manager on an earlier outcome card (any status)."""
    from app.models.intelligence import AgentSuggestion

    out: set[str] = set()
    for (payload,) in db.query(AgentSuggestion.payload_json).filter(AgentSuggestion.tenant_id == tenant.tenant_id, AgentSuggestion.kind == KIND,
                                                                    AgentSuggestion.entity_id == application_id).all():
        out.update((payload or {}).get("interview_ids") or [])
    return out


def round_interviews(db: Session, tenant, application) -> list:
    from app.models.interview import Interview

    covered = _covered(db, tenant, application.id)
    rows = (db.query(Interview).filter(Interview.tenant_id == tenant.tenant_id, Interview.application_id == application.id)
            .order_by(Interview.scheduled_at.asc().nullslast(), Interview.created_at.asc()).all())
    return [i for i in rows if str(i.id) not in covered and i.decision is None]


def majority(recommendations: list[Optional[str]]) -> Optional[str]:
    """The option most interviewers recommended; None for a tie or no recommendation at all."""
    counts = Counter(FROM_RECOMMENDATION[r] for r in recommendations if r in FROM_RECOMMENDATION)
    if not counts:
        return None
    top = counts.most_common()
    if len(top) > 1 and top[0][1] == top[1][1]:
        return None
    return top[0][0]


def _scorecards(rounds: list) -> list[dict]:
    return [{"interview_id": str(i.id), "interviewer": i.interviewer_name or i.interviewer_email or f"Interviewer {n}",
             "label": f"Interviewer {n}", "technical": i.technical_rating, "communication": i.communication_rating, "overall": i.overall_rating,
             "recommendation": i.recommendation, "comments": i.comments or ""} for n, i in enumerate(rounds, start=1)]


def _summarise(db: Session, tenant, application, scorecards: list[dict]):
    """(summary dict, decision_log_id, why_not) - never raises; no AI is still a useful card."""
    from app.platform.ai import governance
    from app.platform.ai.tracked import ai_subject

    if not governance.feature_enabled(db, tenant, "agents.interview_summary"):
        return None, None, "AI is not switched on for interview summaries - the scores are below"
    lines = "\n".join(f"{c['label']}: technical {c['technical']}, communication {c['communication']}, overall {c['overall']}, "
                      f"recommends {c['recommendation'] or 'nothing'}. Notes: {c['comments'] or '-'}" for c in scorecards)
    try:
        with ai_subject("application", application.id):
            out, log_id = governance.governed_json(
                db, tenant, feature="agents.interview_summary", purpose="llm.judgment",
                system=("Summarise interview scorecards for the hiring manager. Use only what the scorecards say. Reply with JSON: "
                        '{"one_line": "<at most 12 words>", "strengths": [..], "concerns": [..], "disagreements": [..], '
                        '"suggested_next_step": "move_forward | reject | another_round", "why": "<one sentence>"}. '
                        "Never decide; never mention names, age, gender, religion or anything not job-related."),
                messages=[{"role": "user", "content": f"Scorecards (1-5 scale):\n{lines}"}],
                input_refs={"application_id": str(application.id)})
    except Exception as exc:  # noqa: BLE001 -- budget, provider, bad JSON: the card comes with the scores only
        log.warning("interview summary failed for %s: %s", application.id, exc)
        db.rollback()
        return None, None, f"the summary could not be written ({type(exc).__name__}) - the scores are below"
    if not isinstance(out, dict):
        return None, log_id, "the summary came back empty - the scores are below"
    clean = {k: [str(x)[:300] for x in (out.get(k) or [])][:6] for k in ("strengths", "concerns", "disagreements")}
    step = out.get("suggested_next_step") if out.get("suggested_next_step") in OPTIONS else None
    return {**clean, "one_line": str(out.get("one_line") or "")[:120], "suggested_next_step": step, "why": str(out.get("why") or "")[:300]}, log_id, None


def _scores_line(scorecards: list[dict]) -> str:
    overall = [c["overall"] for c in scorecards if c["overall"] is not None]
    recs = Counter(c["recommendation"] for c in scorecards if c["recommendation"])
    bits = [f"overall {sum(overall) / len(overall):.1f}/5" if overall else None,
            ", ".join(f"{n} {r.replace('_', ' ')}" for r, n in recs.most_common()) if recs else None]
    return "; ".join(b for b in bits if b) or "scorecards in"


def prepare_outcome(db: Session, tenant, application, run: Run):
    """A scorecard came in -> the card once the whole round has submitted (None while waiting / nothing to do)."""
    if application is None or application.status != "interview_scheduled" or not enabled(db, tenant, "scheduling", "interviews"):
        return None
    if waiting_card(db, tenant, KIND, application.id):
        return None
    rounds = round_interviews(db, tenant, application)
    if not rounds or not all(submitted(i) for i in rounds):
        return None  # still waiting for someone (the watchdog nudges after 24 h)
    from app.hr_agents.autopilot.jobs import hiring_manager
    from app.models.job_role import JobRole

    job = db.get(JobRole, application.job_role_id)
    manager, fallback = hiring_manager(db, tenant, job) if job is not None else (None, True)
    scorecards = _scorecards(rounds)
    summary, log_id, why_not = _summarise(db, tenant, application, scorecards)
    default = majority([c["recommendation"] for c in scorecards])
    n = names(db, application)
    one_line = (summary or {}).get("one_line") or _scores_line(scorecards)
    payload = {"application_id": str(application.id), "candidate": n["candidate"], "job": n["job"], "interview_ids": [c["interview_id"] for c in scorecards],
               "scorecards": scorecards, "summary": summary, "options": list(OPTIONS), "decision": default, "majority": default, "reason": "",
               "hiring_manager": getattr(manager, "email", None), "hiring_manager_is_job_owner": fallback}
    if why_not:
        payload["note"] = why_not
    c = card(db, tenant, kind=KIND, by_agent="scheduling", title=f"Interview result for {n['candidate']}: {one_line}", payload=payload,
             permission=PERMISSION, entity_type="application", entity_id=application.id, reviewer_user_id=getattr(manager, "id", None),
             decision_log_id=log_id)
    record(db, tenant, run, agent="scheduling", action="propose_interview_outcome", outcome="proposed", entity_type="application", entity_id=application.id,
           summary=(f"All {len(scorecards)} interviewer(s) sent their scorecards for {n['candidate']} ({n['job']}); prepared the interview result for "
                    f"{getattr(manager, 'email', None) or 'HR'}{' (job owner - no hiring manager set)' if fallback else ''}. "
                    f"Majority: {(default or 'none (tie)').replace('_', ' ')}."),
           details={"card_id": str(c.id), "majority": default, "interviews": len(scorecards)})
    return c


def on_feedback(db: Session, tenant, row, run: Run):
    """Runner hook: audit row (entity interview, interview_feedback_recorded). A decision recorded on the screen is the
    end of it (the leftover check closes any card); a scorecard without one may complete the round."""
    from app.models.application import Application
    from app.models.interview import Interview

    if (row.details or {}).get("decision"):
        return None
    iv = db.get(Interview, row.entity_id)
    app = db.get(Application, iv.application_id) if iv is not None and iv.application_id else None
    if app is None or app.tenant_id != tenant.tenant_id:
        return None
    return prepare_outcome(db, tenant, app, run)


# ---------------------------------------------------------------- watchdog: missing scorecards


def missing_scorecards(db: Session, tenant, run: Run, now: Optional[datetime] = None) -> int:
    """24 h after an interview without its scorecard: the interviewer is reminded once; still missing 24 h after the
    reminder (or the others disagree in the meantime) -> the hiring manager is told."""
    from app.hr_agents.autopilot.jobs import hiring_manager
    from app.models.application import Application
    from app.models.autopilot import AgentActivity
    from app.models.interview import Interview
    from app.models.job_role import JobRole

    now = now or datetime.now(timezone.utc)
    done = 0
    rows = (db.query(Interview, Application).join(Application, Application.id == Interview.application_id)
            .filter(Interview.tenant_id == tenant.tenant_id, Application.status == "interview_scheduled", Interview.decision.is_(None),
                    Interview.scheduled_at.isnot(None), Interview.scheduled_at <= now - MISSING_AFTER).all())
    for iv, app in rows:
        if submitted(iv) or str(iv.id) in _covered(db, tenant, app.id):
            continue
        n = names(db, app)
        nudged = (db.query(AgentActivity).filter(AgentActivity.tenant_id == tenant.tenant_id, AgentActivity.entity_id == iv.id,
                                                 AgentActivity.action == "nudge_scorecard", AgentActivity.outcome == "done")
                  .order_by(AgentActivity.created_at.desc()).first())
        if nudged is None:
            done += _nudge(db, tenant, run, iv, app, n)
            continue
        told = db.query(AgentActivity.id).filter(AgentActivity.tenant_id == tenant.tenant_id, AgentActivity.entity_id == iv.id,
                                                 AgentActivity.action == "scorecard_missing_told").first()
        others = [o.recommendation for o in round_interviews(db, tenant, app) if o.id != iv.id and o.recommendation]
        disagree = len(set(others)) > 1
        if told is None and (nudged.created_at <= now - MISSING_AFTER or disagree):
            job = db.get(JobRole, app.job_role_id)
            manager, _ = hiring_manager(db, tenant, job) if job is not None else (None, True)
            to = [manager.email] if manager is not None and manager.email else []
            notify(db, tenant, to, f"{iv.interviewer_name or iv.interviewer_email or 'An interviewer'} has not sent the scorecard for "
                                   f"{n['candidate']} ({n['job']}), even after a reminder" + (" - and the others disagree" if disagree else ""),
                   f"/candidates/{app.id}", entity_type="application", entity_id=app.id)
            record(db, tenant, run, agent="watchdog", action="scorecard_missing_told", outcome="escalated", entity_type="interview", entity_id=iv.id,
                   summary=f"Scorecard for {n['candidate']} still missing after the reminder - told {', '.join(to) or 'nobody (no hiring manager / owner)'}.",
                   details={"to": to, "disagree": disagree, "application_id": str(app.id)})
            done += 1
    return done


def _nudge(db: Session, tenant, run: Run, iv, app, n: dict) -> int:
    from app.models.user import User
    from app.platform.links import public_base_url

    email = iv.interviewer_email
    if not email and iv.interviewer_id:
        u = db.get(User, iv.interviewer_id)
        email = u.email if u is not None else None
    if not email:
        return 0
    link = f"{public_base_url(db).rstrip('/')}/interviews"
    when = iv.scheduled_at.strftime("%d %b %Y") if iv.scheduled_at else "the interview day"
    try:
        from app.platform.comms.defaults import send_default

        send_default(db, tenant, "recruitment.interview_feedback_reminder", to=[email], related_entity_type="application", related_entity_id=app.id,
                     ctx={"interviewer_name": iv.interviewer_name or email, "candidate_name": n["candidate"], "job_title": n["job"],
                          "interview_date": when, "link": link})
    except Exception as exc:  # noqa: BLE001 -- the in-app notice still goes
        log.warning("scorecard reminder email to %s failed: %s", email, exc)
        db.rollback()
    notify(db, tenant, [email], f"Your scorecard for {n['candidate']} ({n['job']}) is still missing", "/interviews",
           entity_type="application", entity_id=app.id)
    record(db, tenant, run, agent="watchdog", action="nudge_scorecard", outcome="done", entity_type="interview", entity_id=iv.id,
           summary=f"Reminded {email} to send the scorecard for {n['candidate']} ({n['job']}).", details={"application_id": str(app.id)})
    return 1
