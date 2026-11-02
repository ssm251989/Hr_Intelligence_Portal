"""Part 23.3c: the Finance dashboard's "money released" history said "Gunda Kishore - salary approved" for a
removed candidate - the release took the application's stage as its reason. Removal now says "removed", and an
unknown stage reads "dropped out"."""
import uuid

from app.models.application import Application
from app.models.candidate import Candidate
from app.models.department_budget import BudgetCommitment
from app.models.job_role import JobRole
from app.platform.tenancy.context import get_current_tenant
from app.recruitment import budgets, removal


def _hire(db, status):
    job = JobRole(title=f"Release test {uuid.uuid4().hex[:6]}", department="Release Dept", status="published")
    cand = Candidate(full_name="Rita Release", email=f"rita-{uuid.uuid4().hex[:6]}@example.com")
    db.add_all([job, cand])
    db.flush()
    app = Application(job_role_id=job.id, candidate_id=cand.id, status=status)
    db.add(app)
    db.flush()
    row = BudgetCommitment(application_id=app.id, department="Release Dept", fiscal_year="2026-27", amount=500000, state="committed")
    db.add(row)
    db.commit()
    return cand, app, row


def test_removed_candidate_release_says_removed_not_the_stage(db_session):
    cand, _app, row = _hire(db_session, "salary_approved")
    removal.remove(db_session, get_current_tenant(), cand, reason="test_data", note=None, actor="tester@example.com")
    db_session.refresh(row)
    assert row.state == "released"
    assert row.release_reason == "Rita Release - removed"


def test_unknown_stage_reads_dropped_out(db_session):
    _cand, app, row = _hire(db_session, "salary_approved")
    budgets.release(db_session, get_current_tenant(), app.id)
    db_session.refresh(row)
    assert row.release_reason == "Rita Release - dropped out"
    app2 = _hire(db_session, "offer_declined")[1]
    budgets.release(db_session, get_current_tenant(), app2.id)
    assert db_session.query(BudgetCommitment).filter(BudgetCommitment.application_id == app2.id).one().release_reason == "Rita Release - offer declined"
