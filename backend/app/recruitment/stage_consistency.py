"""Part 18.28: an application's stage may only say "interviewed" / "passed" (or a salary
step, which comes after the interview) when a real interview record proves it.

check(db, tenant) -> rows whose status is ahead of their interview records, with the stage
the records actually support. fix(db, tenant, actor) moves each back to that stage (audit
logged, nothing deleted). Removed (Recycle bin) candidates are included, so a restore can't
bring back a wrong stage.
"""

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.recruitment.removal import INCLUDE_REMOVED

# statuses that claim a finished interview with a "selected" decision
NEEDS_SELECTED = ("interview_selected", "salary_ok", "salary_above_band", "salary_approved", "salary_rejected")


def check(db: Session, tenant) -> list[dict]:
    out = []
    apps = (db.query(Application).execution_options(**{INCLUDE_REMOVED: True})
            .filter(Application.tenant_id == tenant.tenant_id,
                    Application.status.in_(NEEDS_SELECTED + ("interview_scheduled", "interview_rejected"))).all())
    for a in apps:
        ivs = db.query(Interview).execution_options(**{INCLUDE_REMOVED: True}).filter(Interview.application_id == a.id).all()
        decisions = {i.decision for i in ivs}
        if a.status in NEEDS_SELECTED:
            ok = "selected" in decisions
        elif a.status == "interview_rejected":
            ok = "rejected" in decisions
        else:  # interview_scheduled
            ok = bool(ivs)
        if ok:
            continue
        should = "interview_scheduled" if ivs else "hr_selected"
        cand = db.query(Candidate).execution_options(**{INCLUDE_REMOVED: True}).filter(Candidate.id == a.candidate_id).first()
        out.append({"application_id": str(a.id), "candidate": cand.full_name if cand else None, "status": a.status,
                    "interviews": len(ivs), "decisions": sorted(d for d in decisions if d), "should_be": should,
                    "removed": a.removed_at is not None})
    return out


def fix(db: Session, tenant, actor: str = "system") -> list[dict]:
    rows = check(db, tenant)
    for r in rows:
        a = db.query(Application).execution_options(**{INCLUDE_REMOVED: True}).filter(Application.id == r["application_id"]).first()
        a.status = r["should_be"]
        log_action(db, "application", a.id, "stage_corrected_to_records", actor,
                   {"from": r["status"], "to": r["should_be"], "reason": "no interview record with a decision behind this stage"})
    db.commit()
    return rows
