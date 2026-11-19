"""B1 / S3 (Part 27): every "sent" message follows the real send result, the candidate's form link is always
available to share, HR can upload a document for the candidate (same checks), and a salary approval only
claims a budget reservation when the department has a budget."""

import uuid

import pytest

from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.platform.tenancy.context import TENANT_1_ID, TenantContext
from app.recruitment import joining_docs, salary_auto


def _tenant():
    return TenantContext(tenant_id=TENANT_1_ID, slug="tenant1-test", isolation="dedicated_db")


def _app(db, status, **cand):
    job = JobRole(title=f"B1 Role {uuid.uuid4().hex[:4]}", status="published", jd_text="JD", salary_band_min=800000, salary_band_max=1200000,
                  department=f"Dept {uuid.uuid4().hex[:4]}")
    db.add(job)
    db.commit()
    c = Candidate(full_name="Ravi Kumar", email=f"b1-{uuid.uuid4().hex[:6]}@example.com", **cand)
    db.add(c)
    db.commit()
    a = Application(job_role_id=job.id, candidate_id=c.id, status=status, expected_salary=cand.get("expected_ctc"))
    db.add(a)
    db.commit()
    return a


class _Msg:
    def __init__(self, status):
        self.status = status


@pytest.fixture()
def no_mailbox(monkeypatch):
    monkeypatch.setattr("app.platform.comms.defaults.send_default", lambda *a, **k: _Msg("failed"))


def test_documents_link_not_sent_says_so_and_still_gives_the_link(client, db_session, no_mailbox):
    a = _app(db_session, "salary_approved")
    r = client.post(f"/api/v1/ui/documents/{a.id}/send-form").json()
    assert r["sent"] is False and r["link"].startswith("http")
    assert client.get(f"/api/v1/ui/documents/{a.id}/link").json()["link"] == r["link"]  # [Copy link], same open link


def test_hr_upload_for_the_candidate_runs_the_same_checks(client, db_session, monkeypatch):
    seen = []
    monkeypatch.setattr(joining_docs, "check_document", lambda db, tenant, doc: seen.append(doc.doc_code))
    monkeypatch.setattr(joining_docs, "UPLOAD_DIR", __import__("pathlib").Path(__import__("tempfile").mkdtemp()))
    a = _app(db_session, "salary_approved")
    code = joining_docs.required_for(db_session, _tenant(), db_session.get(JobRole, a.job_role_id))[0]["code"]
    r = client.post(f"/api/v1/ui/documents/{a.id}/files/{code}", files={"file": ("pan.pdf", b"%PDF-1.4 test", "application/pdf")})
    assert r.status_code == 200, r.text
    assert seen == [code]
    log = db_session.query(AuditLog).filter(AuditLog.entity_id == a.id, AuditLog.action == "document_uploaded").one()
    assert log.actor != "candidate"  # HR's own name in the history
    bad = client.post(f"/api/v1/ui/documents/{a.id}/files/{code}", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert bad.status_code == 400


def test_salary_approve_without_a_department_budget_reserves_nothing(db_session):
    a = _app(db_session, "salary_above_band", expected_ctc=1300000, current_ctc=1200000)
    out = salary_auto.decide(db_session, _tenant(), a, decision="approve", actor="hr@example.com", amount=1250000)
    assert out["status"] == "salary_approved" and out["budget_reserved"] is False


def test_counter_offer_without_a_mailbox_is_not_called_emailed(db_session, no_mailbox):
    a = _app(db_session, "salary_above_band", expected_ctc=1300000, current_ctc=1200000)
    out = salary_auto.decide(db_session, _tenant(), a, decision="counter", actor="hr@example.com", amount=1200000)
    assert out["email_sent"] is False
