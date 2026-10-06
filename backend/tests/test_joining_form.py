"""Change 2026-10-05: joining details fields are configurable (all optional by default)."""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.offer import Offer
from app.onboarding import joining_form, welcome_steps
from app.onboarding.portal import PreboardingPortal
from app.platform.tenancy.context import get_current_tenant


@pytest.fixture
def case(db_session):
    # tests share the database with tenant 1's real data: start from the default rules inside this transaction
    joining_form.save(db_session, get_current_tenant(), {"fields": {}, "documents": {}}, actor="test")
    job = JobRole(title="Form Test Role", department="AI", positions_count=1, status="published")
    db_session.add(job)
    db_session.flush()
    cand = Candidate(full_name="Asha Form", email="asha.form@example.com", first_name="Asha", last_name="Form")
    db_session.add(cand)
    db_session.flush()
    app = Application(job_role_id=job.id, candidate_id=cand.id, status="onboarding_started")
    db_session.add(app)
    db_session.flush()
    offer = Offer(application_id=app.id, signed=True, signed_at=datetime.now(timezone.utc), joining_date=date.today() + timedelta(days=10))
    db_session.add(offer)
    db_session.commit()
    return PreboardingPortal(db_session, get_current_tenant()).create_case_from_offer(offer.id)


def _valid_aadhaar() -> str:
    for n in range(234123412340, 234123412400):
        if welcome_steps._aadhaar_ok(str(n)):
            return str(n)
    raise AssertionError


def _set(db, fields=None, documents=None):
    return joining_form.save(db, get_current_tenant(), {"fields": fields or {}, "documents": documents or {}}, actor="admin@example.com")


def test_all_optional_by_default_almost_empty_form_submits(db_session, case):
    t = get_current_tenant()
    view = welcome_steps.joining_details_view(db_session, t, case)
    assert view["fields"] and not any(f["required"] for f in view["fields"])
    out = welcome_steps.save_joining_details(db_session, t, case, {"first_name": "Asha"}, submit=True)
    assert out["errors"] == {} and out["status"] == "submitted"
    assert "aadhaar" in out["missing_optional"] and out["missing_required"] == []


def test_format_check_only_when_typed_with_plain_message(db_session, case):
    t = get_current_tenant()
    out = welcome_steps.save_joining_details(db_session, t, case, {"pan": "abc12"}, submit=True)
    assert out["errors"] == {"pan": "PAN looks like ABCDE1234F (5 letters, 4 digits, 1 letter)."}
    _set(db_session, {"pan": {"show": "optional", "check": False}})
    out = welcome_steps.save_joining_details(db_session, t, case, {"pan": "abc12"}, submit=True)
    assert out["errors"] == {}


def test_required_field_blocks_only_while_empty_and_version_applies_to_new_forms(db_session, case):
    t = get_current_tenant()
    opened_before = welcome_steps.joining_details_view(db_session, t, case)["form_version"]
    after = _set(db_session, {"aadhaar": {"show": "required"}})["version"]
    assert after == opened_before + 1
    # a form opened before the change keeps the old rules
    assert welcome_steps.save_joining_details(db_session, t, case, {"first_name": "Asha"}, submit=True, form_version=opened_before)["errors"] == {}
    view = welcome_steps.joining_details_view(db_session, t, case)
    assert next(f for f in view["fields"] if f["key"] == "aadhaar")["required"] and view["missing_required"] == ["aadhaar"]
    out = welcome_steps.save_joining_details(db_session, t, case, {"first_name": "Asha"}, submit=True, form_version=after)
    assert out["errors"] == {"aadhaar": "Aadhaar number is needed."}
    out = welcome_steps.save_joining_details(db_session, t, case, {"aadhaar": _valid_aadhaar()}, submit=True, form_version=after)
    assert out["errors"] == {} and out["saved"]["aadhaar"].startswith("XXXX XXXX ")  # stays masked


def test_hidden_field_disappears_and_is_not_taken(db_session, case):
    t = get_current_tenant()
    _set(db_session, {"aadhaar": {"show": "hidden"}})
    view = welcome_steps.joining_details_view(db_session, t, case)
    assert "aadhaar" not in {f["key"] for f in view["fields"]}
    welcome_steps.save_joining_details(db_session, t, case, {"aadhaar": "1"}, submit=True)
    assert "aadhaar" not in welcome_steps._plain(case)


def test_help_text_history_and_revert(db_session, case):
    t = get_current_tenant()
    v1 = _set(db_session, {"pan": {"show": "required", "help": {"en": "As on your PAN card", "hi": "PAN कार्ड के अनुसार"}}})["version"]
    _set(db_session, {})
    view = joining_form.admin_view(db_session, t)
    assert view["history"][0]["changes"] == ["PAN: required -> optional", "PAN: help text"]
    joining_form.revert(db_session, t, v1, actor="admin@example.com")
    pan = next(f for f in welcome_steps.joining_details_view(db_session, t, case)["fields"] if f["key"] == "pan")
    assert pan["required"] and pan["help"]["en"] == "As on your PAN card"


def test_documents_required_optional_hidden(db_session, case):
    t = get_current_tenant()
    base = welcome_steps.base_document_list(db_session, t)
    assert base
    first, *_ = base
    _set(db_session, documents={first["code"]: "hidden"})
    assert first["code"] not in {d["code"] for d in welcome_steps.document_list(db_session, t)}
    _set(db_session, documents={first["code"]: "optional"})
    assert next(d for d in welcome_steps.document_list(db_session, t) if d["code"] == first["code"])["required"] is False


def test_lock_and_hr_view_and_remind(client, db_session, case, monkeypatch):
    sent = []
    monkeypatch.setattr("app.platform.comms.defaults.send_default", lambda db, t, key, **kw: sent.append((key, kw)) or type("M", (), {"status": "sent"})())
    t = get_current_tenant()
    welcome_steps.save_joining_details(db_session, t, case, {"first_name": "Asha", "city": "Chennai"}, submit=False)
    detail = client.get(f"/api/v1/ui/onboarding/cases/{case.id}/detail").json()["joining_details"]
    assert "pan" in detail["missing_optional"] and next(f for f in detail["fields"] if f["key"] == "city")["value"] == "Chennai"
    r = client.post(f"/api/v1/ui/onboarding/cases/{case.id}/joining-details/remind")
    assert r.status_code == 200, r.text
    assert sent[0][0] == "onboarding.details_reminder" and "- PAN" in sent[0][1]["ctx"]["missing"] and "/welcome/" in sent[0][1]["ctx"]["portal_link"]
    assert client.post(f"/api/v1/ui/onboarding/cases/{case.id}/joining-details/remind").status_code == 429  # once an hour
    assert client.post(f"/api/v1/ui/onboarding/cases/{case.id}/joining-details/lock", json={"locked": True}).json()["locked"] is True
    r = client.put(f"/api/v1/public/ui/onboarding/portal/{case.portal_token}/joining-details", json={"data": {"city": "Pune"}, "submit": False})
    assert r.status_code == 423
    client.post(f"/api/v1/ui/onboarding/cases/{case.id}/joining-details/lock", json={"locked": False})
    r = client.put(f"/api/v1/public/ui/onboarding/portal/{case.portal_token}/joining-details", json={"data": {"city": "Pune"}, "submit": True})
    assert r.status_code == 200 and r.json()["status"] == "submitted"


def test_settings_api_round_trip(client):
    view = client.get("/api/v1/ui/onboarding/joining-form").json()
    assert {f["show"] for f in view["fields"]} == {"optional"} and {s["key"] for s in view["sections"]} == {"personal", "address", "emergency", "bank_id"}
    out = client.put("/api/v1/ui/onboarding/joining-form", json={"fields": {"aadhaar": {"show": "required", "check": True}}, "documents": {}}).json()
    assert next(f for f in out["fields"] if f["key"] == "aadhaar")["show"] == "required" and out["version"] >= 1
    assert client.post("/api/v1/ui/onboarding/joining-form/revert", json={"version": 99999}).status_code == 404
