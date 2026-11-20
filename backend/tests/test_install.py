"""Part 27 one-step install: answer checks and the .env writer (no database needed).

The full install (PostgreSQL -> login -> menu) was run end to end with passwords containing
@ # : / % and spaces; see docs/PART27_FIXES_AND_INSTALL.txt for the check to repeat locally."""

import pytest

from app.platform.install import envfile
from app.platform.install.validate import Answers, InvalidInput, check, password_problem

GOOD = dict(company_name="CTD Techs", company_slug="ctd-techs", admin_name="Sundar S", admin_email="ys@ctdtechs.com",
            admin_password="Welcome@2026", pg_superuser_password="Admin@123", app_db_password="App pass @1 #x")


@pytest.mark.parametrize("pw, ok", [
    ("Welcome@2026", True),
    ("pass word 123x", True),          # spaces inside are fine
    ("A@#:/%&x9xxxx", True),           # every URL-special character is fine (encoded later)
    ("Welcome@2026\n", False),         # the line-break problem
    ("Welcome\r2026", False),
    ("Wel\tcome2026", False),
    (" Welcome2026", False),           # invisible leading space
    ("Welcome2026 ", False),
    ("short1A", False),
    ("onlyletterspassword", False),
    ("1234567890", False),
    ("", False),
])
def test_password_rules(pw, ok):
    assert (password_problem(pw) is None) is ok


def test_password_not_the_email():
    assert password_problem("Ys12345678", not_like=("ys12345678@ctdtechs.com",)) is not None


def test_all_problems_are_reported_at_once():
    bad = {**GOOD, "company_slug": "CTD Techs", "admin_password": "x\n", "app_db_password": "Admin@123", "pg_port": 70000,
           "app_db_user": "postgres"}
    with pytest.raises(InvalidInput) as e:
        check(Answers.from_dict(bad))
    assert {"company_slug", "admin_password", "app_db_password", "pg_port", "app_db_user"} <= set(e.value.problems)


def test_existing_postgres_password_only_needs_one_line():
    check(Answers.from_dict({**GOOD, "pg_superuser_password": "pg"}))  # short but it already exists
    with pytest.raises(InvalidInput):
        check(Answers.from_dict({**GOOD, "pg_superuser_password": "pg\n"}))
    with pytest.raises(InvalidInput):  # a NEW PostgreSQL install gets the full rules
        check(Answers.from_dict({**GOOD, "pg_superuser_password": "pg", "new_postgres": True}))


def test_unknown_answer_keys_are_refused():
    with pytest.raises(InvalidInput):
        Answers.from_dict({**GOOD, "admin_pasword": "typo"})


def test_dsn_encodes_special_characters():
    from sqlalchemy.engine import make_url

    url = make_url(envfile.dsn("hr_app", "Ad@m:in/#%1 x", "localhost", 5432, "hr_automation"))
    assert url.password == "Ad@m:in/#%1 x" and url.host == "localhost" and url.database == "hr_automation"
    assert url.drivername == "postgresql+psycopg2"


def test_env_write_fixes_glued_lines_keeps_others_and_reads_back(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# my notes\nANTHROPIC_API_KEY=abc\nAPP_CONTROL_PLANE_DATABASE_URL=postgresql://x/cpSECRET_BACKEND=db_encrypted\n"
                   "SECRET_BACKEND=old\nSECRET_BACKEND=dupe\n", encoding="utf-8")
    values = {"APP_CONTROL_PLANE_DATABASE_URL": envfile.dsn("hr_app", "p@ss #1", "localhost", 5432, "cp"), "SECRET_BACKEND": "db_encrypted",
              "FRONTEND_URL": "http://localhost:5173", "COMPANY_NOTE": "has # and spaces"}
    envfile.write(env, values)
    text = env.read_text(encoding="utf-8")
    assert "# my notes" in text and "ANTHROPIC_API_KEY=abc" in text
    assert text.count("SECRET_BACKEND=") == 1
    got = envfile.read(env)
    assert all(got[k] == v for k, v in values.items())


def test_env_values_never_replace_existing_keys():
    from app.platform.install.provision import env_values

    a = Answers.from_dict(GOOD)
    kept = env_values(a, {"MASTER_KEY": "keep-me", "SECRET_KEY": "keep-too"})
    assert kept["MASTER_KEY"] == "keep-me" and kept["SECRET_KEY"] == "keep-too"
    fresh = env_values(a, {})
    assert fresh["MASTER_KEY"] and fresh["MASTER_KEY"] != env_values(a, {})["MASTER_KEY"]  # generated, random
    assert "Admin%40123" in fresh["DATABASE_URL"] and fresh["APP_DATABASE_URL"].startswith("postgresql+psycopg2://hr_app:")


def test_env_refuses_a_line_break_in_a_value(tmp_path):
    with pytest.raises(ValueError):
        envfile.write(tmp_path / ".env", {"SECRET_KEY": "a\nb"})


# ---------------------------------------------------------------- Part 28.4: upgrade, uninstall, master key once

import json as _json

import pytest as _pytest


@_pytest.fixture()
def fake_pc(tmp_path, monkeypatch):
    """No Windows services / firewall: the non-Windows path, data in a temp folder."""
    from app.platform.install import windows

    monkeypatch.setattr(windows, "WINDOWS", False)
    monkeypatch.setenv("HRA_DATA", str(tmp_path / "data"))
    install = tmp_path / "installed"
    (install / "app" / "backend").mkdir(parents=True)
    (install / "app" / "backend" / ".env").write_text("MASTER_KEY=abc123key\nDATABASE_URL=\n", encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    (data / "installed.json").write_text(_json.dumps({"version": "1.0.0", "install_dir": str(install), "url": "http://localhost:8080/",
                                                      "web_port": 8080, "new_postgres": True}), encoding="utf-8")
    return windows, install, data


def test_upgrade_backs_up_first_then_files_migrations_service(fake_pc, tmp_path, monkeypatch):
    windows, install, data = fake_pc
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "VERSION.txt").write_text("1.1.0")
    order = []
    monkeypatch.setattr(windows, "step_backup", lambda info: order.append("backup") or {})
    monkeypatch.setattr(windows, "step_files", lambda o: order.append("files") or {})
    monkeypatch.setattr(windows, "step_migrate", lambda info: order.append("migrate") or {})
    monkeypatch.setattr(windows, "step_service", lambda o: order.append("service") or {})
    info = windows.upgrade(bundle, lambda *a: None)
    assert order == ["backup", "files", "migrate", "service"]
    assert info["version"] == "1.1.0" and info["previous_version"] == "1.0.0"
    assert _json.loads((data / "installed.json").read_text())["version"] == "1.1.0"
    assert (install / windows.UNINSTALL_CMD).exists()


def test_failed_backup_stops_the_upgrade_before_anything_changes(fake_pc, tmp_path, monkeypatch):
    windows, install, data = fake_pc
    from app.platform.install import provision

    def boom(info):
        raise provision.StepFailed("backup", "pg_dump failed")

    monkeypatch.setattr(windows, "step_backup", boom)
    monkeypatch.setattr(windows, "step_files", lambda o: _pytest.fail("files copied after a failed backup"))
    with _pytest.raises(provision.StepFailed):
        windows.upgrade(tmp_path, lambda *a: None)


def test_uninstall_keeps_data_unless_confirmed(fake_pc):
    windows, install, data = fake_pc
    out = windows.uninstall(False, lambda *a: None)
    assert out["data_kept"] is True and data.exists() and (data / "uninstalled.json").exists()


def test_uninstall_with_delete_removes_the_data_folder(fake_pc):
    windows, install, data = fake_pc
    out = windows.uninstall(True, lambda *a: None)
    assert out["data_kept"] is False and not data.exists()


def test_uninstall_screen_needs_the_second_confirmation(fake_pc, monkeypatch):
    from app.platform.install import wizard

    sent = {}

    class H(wizard.Handler):
        def __init__(self):
            pass

        def _ok(self):
            return True

        def _body(self):
            return {"delete_data": True, "confirm": "yes"}

        def _send(self, code, obj, ctype="application/json"):
            sent.update(code=code, obj=obj)

    h = H()
    h.path, h.mode = "/api/uninstall?t=x", "uninstall"
    monkeypatch.setattr(wizard.windows, "uninstall", lambda *a: _pytest.fail("uninstalled without DELETE"))
    h.do_POST()
    assert sent["obj"]["ok"] is False and "DELETE" in sent["obj"]["problem"]


def test_master_key_is_shown_once(fake_pc):
    windows, install, data = fake_pc
    from app.platform.install import wizard

    assert windows.master_key(install) == "abc123key"
    wizard.STATE.update(events=[], running=False, failed=None, finished={"url": "u", "master_key": "abc123key"})
    seen = []

    class H(wizard.Handler):
        def __init__(self):
            pass

        def _ok(self):
            return True

        def _send(self, code, obj, ctype="application/json"):
            seen.append(obj)

    h = H()
    h.path = "/api/progress?t=x"
    h.do_GET()
    h.do_GET()
    assert seen[0]["finished"]["master_key"] == "abc123key" and "master_key" not in seen[1]["finished"]
