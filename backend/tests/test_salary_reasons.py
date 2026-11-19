"""S1 (Part 27): an in-band expected salary with no current CTC still needs a person's approval (safety kept),
but it is never called "above the band": the note / approver message say why, and the salary stage's
"Above range" count holds only applications that really are above the band."""

import uuid

from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.comms import OutboundMessage
from app.models.job_role import JobRole
from app.platform.tenancy.context import TENANT_1_ID, TenantContext
from app.recruitment import salary_auto


def _tenant():
    return TenantContext(tenant_id=TENANT_1_ID, slug="tenant1-test", isolation="dedicated_db")


def _app(db, *, expected, current):
    job = JobRole(title=f"S1 Role {uuid.uuid4().hex[:4]}", status="published", jd_text="JD", salary_band_min=800000, salary_band_max=1200000)
    db.add(job)
    db.commit()
    cand = Candidate(full_name="Nila S1", email=f"s1-{uuid.uuid4().hex[:6]}@example.com", expected_ctc=expected, current_ctc=current,
                     notice_period_days=30)
    db.add(cand)
    db.commit()
    app = Application(job_role_id=job.id, candidate_id=cand.id, status=salary_auto.SALARY_STAGE)
    db.add(app)
    db.commit()
    return app, job


def test_in_band_without_current_salary_needs_approval_but_is_not_above_the_band(client, db_session):
    app, job = _app(db_session, expected=1000000, current=None)
    result = salary_auto.check(db_session, _tenant(), app, job=job)
    assert "no_current" in [r["code"] for r in result["reasons"]]
    assert "above_band" not in [r["code"] for r in result["reasons"]]
    assert app.status == "salary_above_band"  # check() moved it on: a person approves (safety kept)

    log = db_session.query(AuditLog).filter(AuditLog.entity_id == app.id, AuditLog.action == "salary_auto_decided").one()
    assert "current salary not known" in log.details["note"] and "above the band" not in log.details["note"]
    msgs = db_session.query(OutboundMessage).filter(OutboundMessage.related_entity_id == app.id).all()
    assert all("above the band" not in m.subject for m in msgs)

    page = client.get("/api/v1/ui/stage-table/salary", params={"job_role_id": str(job.id)}).json()
    assert page["status_counts"].get("salary_above_band") == 1
    assert page["above_range"] == 0


def test_really_above_the_band_is_counted_as_above_range(client, db_session):
    app, job = _app(db_session, expected=1300000, current=1200000)
    salary_auto.check(db_session, _tenant(), app, job=job)
    page = client.get("/api/v1/ui/stage-table/salary", params={"job_role_id": str(job.id)}).json()
    assert page["above_range"] == 1


def test_reasons_text_words():
    assert salary_auto.reasons_text([{"code": "no_current"}]) == "current salary not known"
    assert salary_auto.reasons_text([{"code": "above_band", "over_pct": 8.3}]) == "8.3% above the band"
