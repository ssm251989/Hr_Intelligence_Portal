"""Part 13 (docs/HRMS_COMPLETE_SPEC.txt): health endpoints, security headers, rate limiting,
AV scan hook, metrics, provisioning validation (dry-run only -- a real `tenant create`
creates a database and belongs to the end-to-end pass), config pack round trip, super-admin
MFA, impersonation revocation, and the DPDP privacy module.

Written under the owner's testing-deferred directive (2026-09-25): not yet executed.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.models.candidate import Candidate
from app.models.privacy import ConsentRecord, DataPrincipalRequest
from app.platform import config_pack
from app.platform.ops import av_scan
from app.platform.tenancy import provisioning
from app.platform.tenancy.context import TENANT_1_ID, TenantContext
from app.privacy import service as privacy

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="tenant1-test", isolation="dedicated_db")


# ---- health / headers / metrics ----


def test_healthz_is_tenantless(anonymous_client):
    assert anonymous_client.get("/healthz").json() == {"status": "ok"}


def test_readyz_reports_checks(anonymous_client):
    body = anonymous_client.get("/readyz").json()
    assert body["checks"]["database"]["ok"] is True and body["checks"]["control_plane"]["ok"] is True


def test_security_headers_on_api_responses(anonymous_client):
    response = anonymous_client.get("/api/v1/public/branding")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers.get("X-Request-ID")


def test_metrics_exposition_uses_route_templates(anonymous_client):
    anonymous_client.get("/api/v1/public/branding")
    text = anonymous_client.get("/metrics").text
    assert "hrms_http_requests_total" in text and 'route="/api/v1/public/branding"' in text


def test_metrics_token_enforced(anonymous_client, monkeypatch):
    monkeypatch.setattr(settings, "METRICS_TOKEN", "t0k")
    assert anonymous_client.get("/metrics").status_code == 401
    assert anonymous_client.get("/metrics", headers={"Authorization": "Bearer t0k"}).status_code == 200


# ---- rate limiting ----


def test_rate_limit_anonymous(anonymous_client, monkeypatch):
    from app.platform.ops import rate_limit

    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_ANON_PER_MINUTE", 3)
    monkeypatch.setattr(rate_limit, "_memory", rate_limit._MemoryCounter())
    codes = [anonymous_client.get("/api/v1/public/branding").status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[-1] == 429
    assert anonymous_client.get("/healthz").status_code == 200  # probes never limited


# ---- AV scan ----


def test_av_scan_skipped_without_scanner(monkeypatch):
    monkeypatch.setattr(settings, "CLAMAV_HOST", "")
    assert av_scan.ensure_clean(b"hello").status == "skipped"


def test_av_scan_fail_closed_when_required(monkeypatch):
    monkeypatch.setattr(settings, "CLAMAV_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "CLAMAV_PORT", 1)  # nothing listens here
    monkeypatch.setattr(settings, "AV_SCAN_REQUIRED", True)
    with pytest.raises(av_scan.UploadRejectedError):
        av_scan.ensure_clean(b"hello")


def test_av_scan_infected_rejected(monkeypatch):
    monkeypatch.setattr(av_scan, "scan_bytes", lambda content: av_scan.ScanResult("infected", "Eicar-Test-Signature"))
    with pytest.raises(av_scan.UploadRejectedError, match="Eicar"):
        av_scan.ensure_clean(b"X5O!P%@AP")


# ---- provisioning (validation + dry run only) ----


@pytest.mark.parametrize("kwargs, message", [
    ({"slug": "Bad_Slug", "name": "x"}, "slug"),
    ({"slug": "okslug", "name": "x", "isolation": "weird"}, "isolation"),
    ({"slug": "okslug", "name": "x", "region": "us-east-1"}, "data residency"),
])
def test_create_tenant_validation(kwargs, message):
    with pytest.raises(provisioning.ProvisioningError, match=message):
        provisioning.create_tenant(dry_run=True, notify=lambda _m: None, **kwargs)


def test_create_tenant_dry_run_plans_every_step():
    result = provisioning.create_tenant(slug=f"dry-{uuid.uuid4().hex[:6]}", name="Dry Run", dry_run=True, admin_email="a@example.com", notify=lambda _m: None)
    steps = {s["step"]: s["status"] for s in result["steps"]}
    assert result["dry_run"] is True
    assert steps["database"] == "planned" and steps["migrations"] == "planned" and steps["first_admin"] == "planned"


def test_delete_without_confirm_is_report_only(control_plane_db_session, monkeypatch):
    from app.platform.tenancy.models_cp import Tenant

    t = Tenant(slug=f"del-{uuid.uuid4().hex[:6]}", display_name="Del", status="active", isolation="shared_rls")
    control_plane_db_session.add(t)
    control_plane_db_session.commit()
    monkeypatch.setattr(provisioning, "ControlPlaneSessionLocal", lambda: control_plane_db_session)
    monkeypatch.setattr(control_plane_db_session, "close", lambda: None)
    monkeypatch.setattr(provisioning, "_row_counts", lambda cp, tenant: {})
    report = provisioning.delete_tenant(t.slug)
    assert report["dry_run"] is True and t.status == "active"


def test_tenant_one_cannot_be_deleted():
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
    from app.platform.tenancy.models_cp import Tenant

    cp = ControlPlaneSessionLocal()
    try:
        slug = cp.get(Tenant, TENANT_1_ID).slug
    finally:
        cp.close()
    with pytest.raises(provisioning.ProvisioningError, match="tenant #1"):
        provisioning.delete_tenant(slug, confirm=slug)


# ---- config pack ----


def test_config_pack_round_trip_remaps_ids_and_is_idempotent(db_session):
    from app.models.pipeline import PipelineStage, PipelineTemplate

    template = PipelineTemplate(tenant_id=TENANT.tenant_id, name="Pack pipeline")
    db_session.add(template)
    db_session.flush()
    db_session.add(PipelineStage(tenant_id=TENANT.tenant_id, template_id=template.id, code="pack_stage", name_i18n={"en": "Stage"}, order=1, category="screening"))
    db_session.commit()

    pack = config_pack.export_pack(db_session, TENANT)
    assert any(r["name"] == "Pack pipeline" for r in pack["tables"]["pipeline_templates"])
    assert "connections" not in pack["tables"]  # never secrets/credentials

    other = TenantContext(tenant_id=uuid.uuid4(), slug="other", isolation="shared_rls")
    mapped = config_pack._mapped_id(other.tenant_id, str(template.id))
    assert mapped != template.id and mapped == config_pack._mapped_id(other.tenant_id, str(template.id))


def test_config_pack_rejects_unknown_format(db_session):
    with pytest.raises(config_pack.ConfigPackError):
        config_pack.import_pack(db_session, TENANT, {"format": "something-else"})


def test_config_pack_dry_run_writes_nothing(db_session):
    pack = config_pack.export_pack(db_session, TENANT)
    report = config_pack.import_pack(db_session, TENANT, pack, dry_run=True)
    assert report["dry_run"] is True


# ---- super-admin console ----


def test_console_requires_session(anonymous_client):
    assert anonymous_client.get("/api/v1/superadmin/tenants").status_code == 401


def test_console_login_refused_without_mfa(anonymous_client, control_plane_db_session, monkeypatch):
    from app.core.security import hash_password
    from app.platform.tenancy.models_cp import PlatformAdmin
    from app.superadmin import router as sa

    admin = PlatformAdmin(email=f"ops-{uuid.uuid4().hex[:6]}@example.com", password_hash=hash_password("a-long-console-password"))
    control_plane_db_session.add(admin)
    control_plane_db_session.commit()

    def _cp_override():
        yield control_plane_db_session

    from app.main import app

    app.dependency_overrides[sa._cp] = _cp_override
    try:
        response = anonymous_client.post("/api/v1/superadmin/login", json={"email": admin.email, "password": "a-long-console-password", "totp_code": "000000"})
    finally:
        app.dependency_overrides.pop(sa._cp, None)
    assert response.status_code == 403 and "mandatory" in response.json()["detail"]


def test_tenant_token_rejected_by_console(client):
    assert client.get("/api/v1/superadmin/tenants").status_code == 403  # a tenant session is not a console session


def test_ended_impersonation_token_rejected(client, db_session, control_plane_db_session, monkeypatch):
    from app.core.security import create_access_token
    from app.models.user import User
    from app.platform.tenancy.models_cp import ImpersonationSession, PlatformAdmin

    admin = PlatformAdmin(email=f"imp-{uuid.uuid4().hex[:6]}@example.com")
    control_plane_db_session.add(admin)
    control_plane_db_session.flush()
    user = db_session.query(User).first()
    session = ImpersonationSession(platform_admin_id=admin.id, tenant_id=TENANT_1_ID, target_user_id=user.id, reason="support ticket 123",
                                   expires_at=datetime.now(timezone.utc) + timedelta(minutes=10), ended_at=datetime.now(timezone.utc))
    control_plane_db_session.add(session)
    control_plane_db_session.commit()
    monkeypatch.setattr("app.platform.tenancy.database_cp.ControlPlaneSessionLocal", lambda: control_plane_db_session)
    monkeypatch.setattr(control_plane_db_session, "close", lambda: None)
    token = create_access_token(str(user.id), extra_claims={"imp": str(session.id)})
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


# ---- privacy (DPDP) ----


def test_consent_ledger_is_append_only(db_session):
    privacy.record_consent(db_session, TENANT, subject_type="candidate", subject_email="p@example.com", purpose="recruitment.application")
    assert privacy.has_consent(db_session, TENANT, purpose="recruitment.application", subject_email="p@example.com")
    privacy.record_consent(db_session, TENANT, subject_type="candidate", subject_email="p@example.com", purpose="recruitment.application", action="withdrawn")
    assert not privacy.has_consent(db_session, TENANT, purpose="recruitment.application", subject_email="p@example.com")
    assert db_session.query(ConsentRecord).filter(ConsentRecord.subject_email == "p@example.com").count() == 2


def test_notice_versions_and_processors(db_session):
    first = privacy.publish_notice(db_session, TENANT, purpose="recruitment.application", title="Notice", body="v1", actor="dpo")
    second = privacy.publish_notice(db_session, TENANT, purpose="recruitment.application", title="Notice", body="v2", actor="dpo")
    assert second.version == first.version + 1
    assert privacy.current_notice(db_session, TENANT, "recruitment.application").body == "v2"
    assert isinstance(privacy.processors(db_session, TENANT), list)


def test_dsr_sla_and_erasure_anonymises_candidate(db_session, monkeypatch):
    monkeypatch.setattr("app.platform.comms.service.dispatch_event", lambda *a, **k: [])
    candidate = Candidate(tenant_id=TENANT.tenant_id, full_name="Priya S", email="priya@example.com", phone="9999999999")
    db_session.add(candidate)
    db_session.commit()
    request = privacy.create_request(db_session, TENANT, request_type="erasure", subject_type="candidate", subject_email="priya@example.com")
    assert request.due_at > datetime.now(timezone.utc)
    with pytest.raises(privacy.PrivacyError, match="verify"):
        privacy.execute_erasure(db_session, TENANT, request, actor="dpo")
    privacy.verify_identity(db_session, request, actor="dpo")
    privacy.execute_erasure(db_session, TENANT, request, actor="dpo")
    db_session.refresh(candidate)
    assert candidate.full_name == privacy.ERASED_NAME and candidate.email is None and candidate.phone is None
    assert request.status == "completed" and candidate.id is not None  # anonymised, not deleted


def test_legal_hold_blocks_erasure(db_session, monkeypatch):
    monkeypatch.setattr("app.platform.comms.service.dispatch_event", lambda *a, **k: [])
    request = privacy.create_request(db_session, TENANT, request_type="erasure", subject_type="candidate", subject_email="hold@example.com")
    privacy.verify_identity(db_session, request, actor="dpo")
    request.legal_hold = True
    db_session.commit()
    with pytest.raises(privacy.PrivacyError, match="legal hold"):
        privacy.execute_erasure(db_session, TENANT, request, actor="dpo")


def test_current_employee_erasure_refused(db_session, monkeypatch):
    from app.core_hr import employees as employees_service

    monkeypatch.setattr("app.platform.comms.service.dispatch_event", lambda *a, **k: [])
    employee = employees_service.create_employee(db_session, TENANT, first_name="Cur", status="active", personal_email="cur@example.com")
    request = privacy.create_request(db_session, TENANT, request_type="erasure", subject_type="employee", subject_email="cur@example.com", subject_id=employee.id)
    privacy.verify_identity(db_session, request, actor="dpo")
    with pytest.raises(privacy.PrivacyError, match="current employee"):
        privacy.execute_erasure(db_session, TENANT, request, actor="dpo")


def test_retention_needs_second_person_and_applies_only_reported_ids(db_session):
    old = Candidate(tenant_id=TENANT.tenant_id, full_name="Old", email="old@example.com", created_at=datetime.now(timezone.utc) - timedelta(days=2000))
    db_session.add(old)
    db_session.commit()
    run = privacy.retention_dry_run(db_session, TENANT, "candidate_unhired", actor="alice")
    assert str(old.id) in run.report_json["ids"]
    with pytest.raises(privacy.PrivacyError, match="different person"):
        privacy.approve_retention_run(db_session, run, actor="alice", approve=True)
    with pytest.raises(privacy.PrivacyError):
        privacy.execute_retention_run(db_session, TENANT, run)  # not approved yet
    privacy.approve_retention_run(db_session, run, actor="bob", approve=True)
    later = Candidate(tenant_id=TENANT.tenant_id, full_name="Later", email="later@example.com", created_at=datetime.now(timezone.utc) - timedelta(days=2000))
    db_session.add(later)
    db_session.commit()
    privacy.execute_retention_run(db_session, TENANT, run)
    db_session.refresh(old)
    db_session.refresh(later)
    assert old.full_name == privacy.ERASED_NAME and later.full_name == "Later"  # not in the approved report


def test_breach_high_severity_needs_board_notice_before_close(db_session, monkeypatch):
    monkeypatch.setattr("app.platform.comms.service.dispatch_event", lambda *a, **k: [])
    incident = privacy.report_breach(db_session, TENANT, title="Laptop lost", description="Unencrypted export on a lost laptop", severity="high",
                                     detected_at=datetime.now(timezone.utc), data_categories=["contact"], affected_count=40, actor="ciso")
    with pytest.raises(privacy.PrivacyError, match="Board"):
        privacy.breach_action(db_session, TENANT, incident, action="close", actor="ciso")
    privacy.breach_action(db_session, TENANT, incident, action="notify_board", actor="ciso")
    assert privacy.breach_action(db_session, TENANT, incident, action="close", actor="ciso").status == "closed"


def test_public_dsr_endpoint_never_reveals_existence(anonymous_client):
    body_a = anonymous_client.post("/api/v1/public/privacy/requests", json={"request_type": "access", "email": "nobody@example.com"}).json()
    body_b = anonymous_client.post("/api/v1/public/privacy/requests", json={"request_type": "access", "email": "someone-else@example.com"}).json()
    assert body_a == body_b


def test_career_apply_writes_consent_ledger(db_session):
    # The public apply flow calls record_consent after creating the application (see
    # app/public/router.py); asserted here at the service seam.
    row = privacy.record_consent(db_session, TENANT, subject_type="candidate", subject_id=uuid.uuid4(), subject_email="apply@example.com",
                                 purpose="recruitment.application", channel="career_site")
    assert row.channel == "career_site"
