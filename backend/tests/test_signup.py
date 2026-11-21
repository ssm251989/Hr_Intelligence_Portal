"""Part 28.5: cloud sign-up ("Create your company") - rules, captcha, rate limit, single-use 30-minute link, the
first admin with the chosen password, <slug>.<PLATFORM_DOMAIN>, activation request, welcome on approval.
Control-plane rows are real (not rolled back), so every test removes what it made."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.platform import signup
from app.platform.install.validate import InvalidInput
from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
from app.platform.tenancy.models_cp import SignupRequest


@pytest.fixture()
def mails(monkeypatch):
    sent = []
    monkeypatch.setattr(signup, "_mail", lambda to, subject, body: sent.append((to, subject, body)))
    return sent


@pytest.fixture()
def cleanup():
    slugs = []
    yield slugs
    cp = ControlPlaneSessionLocal()
    try:
        cp.query(SignupRequest).filter(SignupRequest.slug.in_(slugs)).delete(synchronize_session=False)
        cp.commit()
    finally:
        cp.close()


def _form(slug, **kw):
    cap = signup.new_captcha()
    a, b = [int(x) for x in cap["question"].replace("What is ", "").rstrip("?").split(" + ")]
    base = dict(company_name="Acme India", company_slug=slug, admin_name="Asha Rao", admin_email=f"{slug}@example.com",
                password="Strong pass 123", password2="Strong pass 123", modules=["jobs"], captcha_token=cap["token"],
                captcha_answer=str(a + b), ip=f"10.9.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}")
    base.update(kw)
    return base


def _slug():
    return f"t28-{uuid.uuid4().hex[:8]}"


def test_rules_come_from_the_installer_and_every_problem_is_listed(cleanup):
    with pytest.raises(InvalidInput) as exc:
        signup.start(**_form("admin", password="short", password2="short", captcha_answer="999"))
    assert set(exc.value.problems) >= {"company_slug", "password", "captcha"}
    assert "reserved" in exc.value.problems["company_slug"]


def test_start_keeps_only_a_hash_and_emails_a_30_minute_link(mails, cleanup):
    slug = _slug()
    cleanup.append(slug)
    out = signup.start(**_form(slug))
    assert out["ok"] is True and "30 minutes" in out["message"]
    cp = ControlPlaneSessionLocal()
    row = cp.query(SignupRequest).filter(SignupRequest.slug == slug).one()
    cp.close()
    assert row.password_hash.startswith("$2") and "Strong pass" not in row.password_hash
    assert row.status == "pending_email" and timedelta(minutes=29) < row.token_expires_at - datetime.now(timezone.utc) <= timedelta(minutes=30)
    (to, subject, body), = mails
    assert to == [f"{slug}@example.com"] and "/signup/confirm?token=" in body and f"{slug}.localhost" in body


def test_confirm_is_single_use_and_starts_the_company(mails, cleanup, monkeypatch):
    slug = _slug()
    cleanup.append(slug)
    started = []
    monkeypatch.setattr(signup, "provision", lambda rid: started.append(rid))
    out = signup.start(**_form(slug))
    token = out["link_for_tests"].split("token=")[1]
    first = signup.confirm(token, background=False)
    assert first["status"] == "confirmed" and len(started) == 1
    again = signup.confirm(token, background=False)  # the link again just shows progress, never a second company
    assert again["status"] == "confirmed" and len(started) == 1


def test_expired_link_is_refused(mails, cleanup):
    slug = _slug()
    cleanup.append(slug)
    token = signup.start(**_form(slug))["link_for_tests"].split("token=")[1]
    cp = ControlPlaneSessionLocal()
    cp.query(SignupRequest).filter(SignupRequest.slug == slug).update({"token_expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)})
    cp.commit()
    cp.close()
    with pytest.raises(signup.SignupError) as exc:
        signup.confirm(token, background=False)
    assert exc.value.status == 410


def test_sign_ups_are_rate_limited(mails, cleanup):
    ip = f"10.250.{uuid.uuid4().int % 250}.1"
    codes = []
    for _ in range(7):
        slug = _slug()
        cleanup.append(slug)
        try:
            signup.start(**_form(slug, ip=ip))
            codes.append(200)
        except signup.SignupError as exc:
            codes.append(exc.status)
    assert codes[:5] == [200] * 5 and 429 in codes[5:]


def test_api_is_reachable_without_a_company(anonymous_client):
    r = anonymous_client.get("/api/v1/platform/signup/captcha")
    assert r.status_code == 200 and r.json()["question"].startswith("What is")
    bad = anonymous_client.post("/api/v1/platform/signup", json={"company_slug": "www"})
    assert bad.status_code == 422 and "company_slug" in bad.json()["detail"]["problems"]


def test_real_company_on_local_postgres_with_the_chosen_password(mails, cleanup, monkeypatch):
    """Integration: provisioning.create_tenant on the local PostgreSQL, <slug>.localhost, the first admin can sign
    in with the password chosen at sign-up, the modules wait for CTD Techs; then everything is dropped again."""
    from app.core.security import verify_password
    from app.models.user import User
    from app.platform.tenancy import provisioning
    from app.platform.tenancy.models_cp import ActivationRequest, Tenant, TenantDomain

    slug = _slug()
    cleanup.append(slug)
    token = signup.start(**_form(slug))["link_for_tests"].split("token=")[1]
    try:
        out = signup.confirm(token, background=False)
        status = signup.status_by_token(token)
        assert status["status"] == "waiting_approval", status
        assert status["host"] == f"{slug}.localhost"
        cp = ControlPlaneSessionLocal()
        tenant = cp.query(Tenant).filter(Tenant.slug == slug).one()
        assert cp.query(TenantDomain).filter(TenantDomain.host == f"{slug}.localhost").count() == 1
        assert cp.query(ActivationRequest).filter(ActivationRequest.tenant_id == tenant.id).count() == 1
        cp.expunge(tenant)
        cp.close()
        from app.platform.tenancy.context import tenant_context

        with tenant_context(tenant.id, slug=slug):
            db = provisioning.tenant_session(tenant)
            admin = db.query(User).filter(User.email == f"{slug}@example.com").one()
            assert admin.role == "admin" and verify_password("Strong pass 123", admin.hashed_password)
            bind = db.get_bind()
            db.close()
            bind.dispose()
        assert signup.welcome(tenant.id) is True  # CTD Techs approved -> "ready" email
        assert any("is ready" in s for _, s, _ in mails)
        assert out["status"] == "confirmed"
    finally:
        cp = ControlPlaneSessionLocal()
        tenant = cp.query(Tenant).filter(Tenant.slug == slug).first()
        if tenant is not None:
            cp.expunge(tenant)
            cp.query(SignupRequest).filter(SignupRequest.tenant_id == tenant.id).update({"tenant_id": None})
            cp.commit()
        cp.close()
        if tenant is not None:
            provisioning.delete_tenant(slug, confirm=slug, drop_database=True)
            cp = ControlPlaneSessionLocal()
            from app.platform.tenancy.models_cp import ActivationEvent, ControlPlaneSecret, TenantProvisioningJob

            ids = [r.id for r in cp.query(ActivationRequest).filter(ActivationRequest.tenant_id == tenant.id)]
            if ids:
                cp.query(ActivationEvent).filter(ActivationEvent.request_id.in_(ids)).delete(synchronize_session=False)
                cp.query(ActivationRequest).filter(ActivationRequest.id.in_(ids)).delete(synchronize_session=False)
            cp.query(TenantProvisioningJob).filter(TenantProvisioningJob.tenant_id == tenant.id).delete(synchronize_session=False)
            cp.query(ControlPlaneSecret).filter(ControlPlaneSecret.ref.in_([f"tenant-{tenant.id}-db-dsn", f"tenant-{tenant.id}-admin-dsn"])).delete(synchronize_session=False)
            cp.query(Tenant).filter(Tenant.id == tenant.id).delete(synchronize_session=False)
            cp.commit()
            cp.close()
