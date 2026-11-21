"""Part 32: one CTD approver + signed approvals. A throwaway Ed25519 key pair stands in for CTD Techs' key; the CTD
signing tool (tools/ctd_licence) makes the codes, so the tool and the app are checked against each other."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.platform import activation, module_status
from app.platform.licence import api as licence_api
from app.platform.licence import codes
from app.platform.licence import config as ctd_config
from app.platform.licence import state as licence
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from ctd_licence import core as tool  # noqa: E402

pytestmark = pytest.mark.licence


def _tenant():
    return TenantContext(tenant_id=TENANT_1_ID, slug="tenant1-test", isolation="dedicated_db")


@pytest.fixture()
def ctd_key(monkeypatch, tmp_path):
    """CTD's key pair for the test + a signed CTD file naming the one approver."""
    key = Ed25519PrivateKey.generate()
    codes.set_public_key_for_tests(key.public_key())
    monkeypatch.setattr(ctd_config, "CONFIG_PATH", tmp_path / "ctd_config.json")
    monkeypatch.setattr(ctd_config, "SIG_PATH", tmp_path / "ctd_config.json.sig")
    data = json.dumps({"approver_email": "licence@ctdtechs.com", "support": {"email": "support@ctdtechs.com"}}).encode()
    ctd_config.install(data, __import__("base64").b64encode(key.sign(data)).decode())
    licence.invalidate()
    licence_api.clear_cache()
    yield key
    codes.set_public_key_for_tests(None)
    ctd_config.clear_cache()
    licence.invalidate()
    licence_api.clear_cache()


@pytest.fixture(autouse=True)
def _clean_control_plane(monkeypatch):
    """The control plane is not rolled back per test: remove what this test made; never send through a real mailbox."""
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
    from app.platform.tenancy.models_cp import ActivationEvent, ActivationRequest, LicenceApproval

    sent = []
    monkeypatch.setattr(activation, "_send_company", lambda db, tenant, to, subject, body: sent.append((to, subject, body)))
    start = datetime.now(timezone.utc)
    yield sent
    cp = ControlPlaneSessionLocal()
    try:
        ids = [r.id for r in cp.query(ActivationRequest.id).filter(ActivationRequest.tenant_id == TENANT_1_ID, ActivationRequest.created_at >= start)]
        if ids:
            cp.query(ActivationEvent).filter(ActivationEvent.request_id.in_(ids)).delete(synchronize_session=False)
            cp.query(ActivationRequest).filter(ActivationRequest.id.in_(ids)).delete(synchronize_session=False)
        cp.query(LicenceApproval).filter(LicenceApproval.tenant_id == TENANT_1_ID, LicenceApproval.created_at >= start).delete(synchronize_session=False)
        cp.commit()
    finally:
        cp.close()
    licence.invalidate()


@pytest.fixture()
def admin(db_session):
    from tests.conftest import _create_user

    return _create_user(db_session, role="admin", email="lic-admin@example.com")


@pytest.fixture()
def no_grace(monkeypatch):
    monkeypatch.setattr(licence, "_in_grace", lambda tenant: None)
    licence.invalidate()


def _approve(key, request_text, **kw) -> str:
    request = tool.decode_request(request_text)
    return tool.sign_approval(tool.approval_payload(request, **kw), key)


def _ask(db, admin, modules=("jobs", "candidates")):
    return activation.request_access(db, _tenant(), list(modules), admin)


# ---------------------------------------------------------------- signature


def test_a_valid_signed_code_unlocks_and_switches_on_exactly_the_signed_modules(db_session, admin, ctd_key, no_grace, _clean_control_plane):
    assert licence.standing(_tenant())["state"] == "locked"
    info = _ask(db_session, admin)
    assert info["request_text"].startswith("CTDREQ1.") and info["approver"] == "licence@ctdtechs.com"
    assert _clean_control_plane[0][0] == ["licence@ctdtechs.com"]  # sent to the ONE approver, through the company's mailbox
    out = activation.activate_with_code(db_session, _tenant(), _approve(ctd_key, info["request_text"]), admin)
    assert out["kind"] == "access" and set(out["activated"]) >= {"jobs", "candidates"}
    s = licence.standing(_tenant())
    assert s["state"] == "approved" and {"jobs", "candidates"} <= set(s["modules"])
    assert module_status.is_active(db_session, _tenant(), "jobs") and not module_status.is_active(db_session, _tenant(), "salary")


@pytest.mark.parametrize("what", ["edited", "other_install", "other_key", "expired", "other_company"])
def test_a_code_that_is_not_right_is_refused(db_session, admin, ctd_key, no_grace, what):
    info = _ask(db_session, admin)
    request = tool.decode_request(info["request_text"])
    payload = tool.approval_payload(request)
    key = ctd_key
    if what == "other_install":
        payload["install_id"] = "someone-else"
    if what == "other_company":
        payload["slug"] = "another-co"
    if what == "expired":
        payload["valid_until"] = "2020-01-01"
    if what == "other_key":
        key = Ed25519PrivateKey.generate()
    code = tool.sign_approval(payload, key)
    if what == "edited":  # swap the signed body for one listing every module, keep CTD's signature
        _, body, sig = code.split(".")
        forged = json.loads(codes.b64d(body))
        forged["modules"] = ["jobs", "candidates", "salary", "offers", "bgv"]
        code = ".".join(["CTD1", codes.b64e(codes.canonical(forged)), sig])
    with pytest.raises(activation.ActivationError) as exc:
        activation.activate_with_code(db_session, _tenant(), code, admin)
    assert exc.value.code in ("WRONG_CODE", "CODE_EXPIRED")
    assert licence.standing(_tenant())["state"] == "locked"


def test_a_code_works_once_and_five_wrong_codes_lock_the_entry(db_session, admin, ctd_key, no_grace):
    info = _ask(db_session, admin)
    code = _approve(ctd_key, info["request_text"])
    activation.activate_with_code(db_session, _tenant(), code, admin)
    with pytest.raises(activation.ActivationError) as exc:
        activation.activate_with_code(db_session, _tenant(), code, admin)  # the same nonce again
    assert exc.value.code == "CODE_USED"

    _ask(db_session, admin, ("jobs",))
    for _ in range(4):
        with pytest.raises(activation.ActivationError) as exc:
            activation.activate_with_code(db_session, _tenant(), "CTD1.bad.code", admin)
        assert exc.value.code == "WRONG_CODE"
    with pytest.raises(activation.ActivationError) as exc:
        activation.activate_with_code(db_session, _tenant(), "CTD1.bad.code", admin)
    assert exc.value.code == "TOO_MANY_TRIES"


def test_a_module_change_needs_its_own_signed_code(db_session, admin, ctd_key, no_grace):
    info = _ask(db_session, admin, ("jobs",))
    activation.activate_with_code(db_session, _tenant(), _approve(ctd_key, info["request_text"]), admin)
    change = activation.request_activation(db_session, _tenant(), ["candidates"], admin)
    assert change["kind"] == "modules" and "candidates" in tool.decode_request(change["request_text"])["modules"]
    assert not module_status.is_active(db_session, _tenant(), "candidates")  # waiting for CTD
    activation.activate_with_code(db_session, _tenant(), _approve(ctd_key, change["request_text"]), admin)
    assert module_status.is_active(db_session, _tenant(), "candidates") and module_status.is_active(db_session, _tenant(), "jobs")


# ---------------------------------------------------------------- tamper


def test_a_module_switched_on_in_the_database_stays_off(db_session, admin, ctd_key, no_grace):
    from app.models.company_module import CompanyModule

    info = _ask(db_session, admin, ("jobs",))
    activation.activate_with_code(db_session, _tenant(), _approve(ctd_key, info["request_text"]), admin)
    row = db_session.query(CompanyModule).filter(CompanyModule.tenant_id == TENANT_1_ID, CompanyModule.module_key == "salary").first()
    if row is None:
        db_session.add(CompanyModule(tenant_id=TENANT_1_ID, module_key="salary", status="active"))
    else:
        row.status = "active"  # UPDATE company_modules SET status = 'active' WHERE module_key = 'salary'
    db_session.commit()
    module_status.invalidate(TENANT_1_ID)
    assert "salary" not in module_status.active_modules(db_session, _tenant())


def test_a_stored_approval_edited_in_the_database_counts_for_nothing(db_session, admin, ctd_key, no_grace):
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
    from app.platform.tenancy.models_cp import LicenceApproval

    info = _ask(db_session, admin, ("jobs",))
    activation.activate_with_code(db_session, _tenant(), _approve(ctd_key, info["request_text"]), admin)
    cp = ControlPlaneSessionLocal()
    row = cp.query(LicenceApproval).filter(LicenceApproval.tenant_id == TENANT_1_ID).order_by(LicenceApproval.created_at.desc()).first()
    _, body, sig = row.code.split(".")
    forged = json.loads(codes.b64d(body))
    forged["modules"] = ["jobs", "salary"]
    row.code = ".".join(["CTD1", codes.b64e(codes.canonical(forged)), sig])
    cp.commit()
    cp.close()
    licence.invalidate()
    assert licence.standing(_tenant())["state"] == "locked"


# ---------------------------------------------------------------- the CTD file


def test_without_a_signed_ctd_file_requests_are_refused(db_session, admin, monkeypatch, tmp_path, no_grace):
    key = Ed25519PrivateKey.generate()
    codes.set_public_key_for_tests(key.public_key())
    monkeypatch.setattr(ctd_config, "CONFIG_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(ctd_config, "SIG_PATH", tmp_path / "missing.json.sig")
    ctd_config.clear_cache()
    try:
        with pytest.raises(activation.ActivationError) as exc:
            _ask(db_session, admin)
        assert exc.value.code == "NOT_SET_UP"
        data = json.dumps({"approver_email": "licence@ctdtechs.com"}).encode()
        sig = __import__("base64").b64encode(key.sign(data)).decode()
        with pytest.raises(codes.CodeError):
            ctd_config.install(data.replace(b"licence@", b"someone@"), sig)  # edited after signing
        with pytest.raises(codes.CodeError):
            ctd_config.install(data, __import__("base64").b64encode(Ed25519PrivateKey.generate().sign(data)).decode())  # not CTD's key
        assert ctd_config.load() is None
    finally:
        codes.set_public_key_for_tests(None)
        ctd_config.clear_cache()


def test_the_env_approvers_are_ignored_and_the_list_is_read_only(ctd_key, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ACTIVATION_APPROVER_EMAILS", "someone@ctdtechs.com,other@ctdtechs.com")
    assert [a["email"] for a in activation.list_approvers()] == ["licence@ctdtechs.com"]
    with pytest.raises(activation.ActivationError) as exc:
        activation.set_approver(1, "x@ctdtechs.com", "admin@ctdtechs.com")
    assert exc.value.code == "APPROVER_SIGNED"


# ---------------------------------------------------------------- locked installation


def test_a_locked_install_only_opens_sign_in_the_waiting_page_and_the_code_entry(client, ctd_key, no_grace, monkeypatch):
    r = client.get("/jobs")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "WAITING_FOR_CTD"
    for path in ("/api/v1/candidates", "/api/public/v1/jobs", "/api/v1/ui/autopilot/overview"):
        assert client.get(path).json().get("detail", {}).get("code") == "WAITING_FOR_CTD", path
    assert client.get("/auth/me").status_code == 200
    status = client.get("/api/v1/licence/status")
    assert status.status_code == 200 and status.json()["state"] == "locked" and status.json()["approver"] == "licence@ctdtechs.com"
    assert client.post("/api/v1/licence/code", json={"code": "CTD1.not.valid"}).status_code in (400, 409)


def test_jobs_and_agents_do_not_run_while_locked(ctd_key, no_grace):
    from app.platform.jobs.scheduled import JOBS, _module_guard

    assert _module_guard("autopilot_events", JOBS["autopilot_events"])(None, _tenant()) == {"skipped": "waiting for CTD approval"}
    assert _module_guard("public_webhooks", JOBS["public_webhooks"])(None, _tenant()) == {"skipped": "waiting for CTD approval"}


# ---------------------------------------------------------------- upgrade path


def test_an_existing_install_keeps_working_14_days_then_locks(monkeypatch, ctd_key):
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
    from app.platform.tenancy.models_cp import PlatformConfig

    cp = ControlPlaneSessionLocal()
    try:
        grace = cp.get(PlatformConfig, "licence.grace").value_json
    finally:
        cp.close()
    assert str(TENANT_1_ID) in grace["tenants"]  # recorded by the Part 32 migration
    started = datetime.fromisoformat(grace["started_at"])
    monkeypatch.setattr(licence, "_now", lambda: started + timedelta(days=3))
    licence.invalidate()
    s = licence.standing(_tenant())
    assert s["state"] == "grace" and s["grace_days_left"] == 11 and licence.allowed_modules(_tenant()) is None
    monkeypatch.setattr(licence, "_now", lambda: started + timedelta(days=15))
    licence.invalidate()
    assert licence.standing(_tenant())["state"] == "locked"


def test_a_company_created_after_the_upgrade_gets_no_grace(ctd_key):
    other = TenantContext(tenant_id=__import__("uuid").uuid4(), slug="brand-new", isolation="shared_rls")
    assert licence.standing(other)["state"] == "locked"


def test_valid_until_warns_then_makes_the_modules_read_only(db_session, admin, ctd_key, no_grace, monkeypatch):
    info = _ask(db_session, admin, ("jobs",))
    until = (datetime.now(timezone.utc) + timedelta(days=10)).date().isoformat()
    activation.activate_with_code(db_session, _tenant(), _approve(ctd_key, info["request_text"], valid_until=until), admin)
    s = licence.standing(_tenant())
    assert s["expiring_in_days"] == 10 and not s["expired"] and not licence.read_only(_tenant())
    monkeypatch.setattr(licence, "_now", lambda: datetime.now(timezone.utc) + timedelta(days=11))
    licence.invalidate()
    assert licence.read_only(_tenant()) and module_status.is_active(db_session, _tenant(), "jobs")  # never deleted, only read-only


# ---------------------------------------------------------------- the CTD tool


def test_tool_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("CTD_LICENCE_HOME", str(tmp_path / "keys"))
    monkeypatch.setenv("CTD_LICENCE_PASSPHRASE", "a long test passphrase")
    priv, pub = tool.keygen()
    assert b"ENCRYPTED" in priv.read_bytes()  # the private key is passphrase-protected
    with pytest.raises(tool.ToolError):
        tool.keygen()  # never overwritten by accident
    cfg, sig = tool.make_config("licence@ctdtechs.com", out=tmp_path / "out")
    public = serialization.load_pem_public_key(pub.read_bytes())
    codes.set_public_key_for_tests(public)
    try:
        assert ctd_config.check(cfg.read_bytes(), sig.read_text())["approver_email"] == "licence@ctdtechs.com"
        request = codes.encode_request({"v": 1, "kind": "access", "install_id": "i-1", "slug": "acme", "company": "Acme", "modules": ["jobs"],
                                        "nonce": "n-1", "number": "ACT-2026-00001"})
        code = tool.sign_approval(tool.approval_payload(tool.decode_request(request)), tool.private_key())
        payload = codes.decode_approval(code)  # the app accepts what the tool signs
        assert payload["slug"] == "acme" and payload["nonce"] == "n-1" and payload["modules"] == ["jobs"]
        assert tool.read_approval(code, public)[1] is True and tool.read_approval(code, Ed25519PrivateKey.generate().public_key())[1] is False
        log = tool.log_approval(tool.decode_request(request), payload)
        assert "Acme" in log.read_text() and "ACT-2026-00001" in log.read_text()
    finally:
        codes.set_public_key_for_tests(None)
    with pytest.raises(tool.ToolError):
        tool.make_config("me@gmail.com", out=tmp_path / "out2")
