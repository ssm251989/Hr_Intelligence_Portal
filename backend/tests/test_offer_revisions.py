"""Fix 2026-10-05: names, resend / revised offers, and the welcome portal's per-step state."""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.candidates.names import given_name, names_of
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.offer import Offer, OfferVersion
from app.models.user import User
from app.offers import esign, revisions
from app.platform.tenancy.context import get_current_tenant


def _setup(db_session, *, band_max=500000, ctc=300000, name="Gunda Kishore"):
    job = JobRole(title="Junior AI Developer", location="Chennai", salary_band_min=200000, salary_band_max=band_max)
    db_session.add(job)
    db_session.flush()
    cand = Candidate(full_name=name, email="kishore@example.com")
    db_session.add(cand)
    db_session.flush()
    app = Application(job_role_id=job.id, candidate_id=cand.id, status="offer_sent", approved_salary=ctc)
    db_session.add(app)
    db_session.flush()
    offer = Offer(application_id=app.id, offer_letter_text="<p>Dear Gunda Kishore,</p><p>Warm regards</p>", joining_date=date.today() + timedelta(days=10),
                  expiry_date=date.today() + timedelta(days=7), sent_at=datetime.now(timezone.utc) - timedelta(hours=1))
    db_session.add(offer)
    db_session.flush()
    esign.ensure_token(offer)
    db_session.commit()
    return job, cand, app, offer


def _admin(db_session) -> User:
    u = User(email="approver@example.com", hashed_password="x", role="admin", full_name="Approver")
    db_session.add(u)
    db_session.commit()
    return u


def test_names_only_from_trusted_sources():
    c = Candidate(full_name="Gunda Kishore", email="gkishore1433@gmail.com")
    assert names_of(c)["source"] == "none"
    assert given_name(c) == "Gunda Kishore"  # never the first word (often the surname), never a guess
    c.parsed_fields = {"given_name": "Kishore", "family_name": "Gunda"}
    assert names_of(c)["source"] == "resume" and given_name(c) == "Kishore"
    c.parsed_fields = {"given_name": "Someone Else"}  # not part of the full name -> ignored
    assert names_of(c)["source"] == "none"
    c.first_name, c.last_name, c.preferred_name = "Kishore", "Gunda", None
    assert names_of(c) == {"first_name": "Kishore", "last_name": "Gunda", "preferred_name": "", "source": "hr"}
    c.preferred_name = "Kish"
    assert given_name(c) == "Kish"


def test_revised_offer_creates_v2_and_retires_the_old_link(db_session, anonymous_client):
    _job, _cand, app, offer = _setup(db_session)
    old_token = offer.sign_token
    out = revisions.revise(db_session, get_current_tenant(), offer, {"ctc_total": 350000, "reason_code": "salary"}, actor="hr@example.com")
    assert out["state"] == "sent" and out["version_no"] == 2
    assert out["changes"][0] == {"field": "ctc_total", "label": "CTC", "old": "3.0 LPA", "new": "3.5 LPA"}
    db_session.refresh(offer)
    assert offer.version_no == 2 and offer.sign_token != old_token and not offer.signed
    rows = {r.version_no: r for r in db_session.query(OfferVersion).filter(OfferVersion.offer_id == offer.id)}
    assert rows[1].status == "replaced" and rows[1].sign_token == old_token
    assert rows[2].status == "current" and rows[2].reason_code == "salary"
    assert float(db_session.get(Application, app.id).approved_salary) == 350000
    # the old link says it was replaced and can't be signed
    page = anonymous_client.get(f"/offer/sign/{old_token}")
    assert "replaced by a newer version" in page.text and offer.sign_token in page.text
    anonymous_client.post(f"/offer/sign/{old_token}", data={"full_name": "Gunda Kishore", "accept": "yes"})
    db_session.refresh(offer)
    assert not offer.signed
    summary = revisions.summary(db_session, get_current_tenant(), offer)
    assert [(h["version_no"], h["status"]) for h in summary["history"]] == [(2, "sent"), (1, "replaced")]


def test_revision_above_the_band_waits_for_approval(db_session):
    _job, _cand, _app, offer = _setup(db_session, band_max=400000)
    out = revisions.revise(db_session, get_current_tenant(), offer, {"ctc_total": 450000, "reason_code": "salary"}, actor="hr@example.com")
    assert out["state"] == "pending_approval"
    db_session.refresh(offer)
    assert offer.version_no == 1  # nothing sent yet
    pending = revisions.pending(db_session, offer)
    assert pending.approval_json["needed"][0]["code"] == "above_band"
    res = revisions.decide(db_session, get_current_tenant(), offer, pending.id, approve=True, user=_admin(db_session))
    assert res["state"] == "sent"
    db_session.refresh(offer)
    assert offer.version_no == 2


def test_revision_needs_a_reason_and_a_change(db_session):
    _job, _cand, _app, offer = _setup(db_session)
    with pytest.raises(ValueError):
        revisions.revise(db_session, get_current_tenant(), offer, {"ctc_total": 350000, "reason_code": ""}, actor="hr")
    with pytest.raises(ValueError):
        revisions.revise(db_session, get_current_tenant(), offer, {"ctc_total": 350000, "reason_code": "other"}, actor="hr")  # note needed
    with pytest.raises(ValueError):
        revisions.revise(db_session, get_current_tenant(), offer, {"reason_code": "salary"}, actor="hr")  # nothing changed


def test_resend_has_a_15_minute_cooldown(db_session):
    _job, _cand, _app, offer = _setup(db_session)
    offer.sent_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db_session.commit()
    with pytest.raises(revisions.CooldownError):
        revisions.resend(db_session, get_current_tenant(), offer, actor="hr")
    offer.sent_at = datetime.now(timezone.utc) - timedelta(minutes=20)
    db_session.commit()
    out = revisions.resend(db_session, get_current_tenant(), offer, actor="hr")
    assert out["sent_count"] == 2
    with pytest.raises(revisions.CooldownError):
        revisions.resend(db_session, get_current_tenant(), offer, actor="hr")


def test_locked_portal_steps_are_never_done(db_session):
    from app.onboarding import welcome_steps
    from app.onboarding.portal import PreboardingPortal

    _job, _cand, _app, offer = _setup(db_session)
    case = PreboardingPortal(db_session, get_current_tenant()).create_case_from_offer(offer.id)
    steps = welcome_steps.builtin_steps(db_session, get_current_tenant(), case)
    assert [(s["kind"], s["state"]) for s in steps] == [
        ("offer", "not_started"), ("joining_details", "locked"), ("joining_documents", "locked"), ("day_one", "locked")]
    assert all(s["label"] and s["description"] and not s["done"] for s in steps)
    offer.signed, offer.signed_at = True, datetime.now(timezone.utc)
    db_session.commit()
    steps = welcome_steps.builtin_steps(db_session, get_current_tenant(), case)
    assert steps[0]["state"] == "done" and all(s["state"] != "locked" for s in steps)
