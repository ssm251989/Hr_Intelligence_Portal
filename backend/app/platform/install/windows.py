"""The package steps around the install engine (Part 28: unzip -> double-click HRAutomation.exe).

    files     copy the unzipped package to the install folder (default C:\\Program Files\\HR Automation)
    postgres  "install new": initdb with the chosen password (from a temp file, deleted at once),
              port 5432 or the next free one, Windows service HRAutomation-PostgreSQL (automatic)
    engine    provision.run(...) -- databases, .env, tables, company, admin, modules
    service   Windows service HRAutomation-App (WinSW): one port for the web app + API (app.web)
    finish    firewall rule (optional), desktop + Start-menu shortcuts, installed.json

On Linux/macOS (developers, tests) the same code runs PostgreSQL with pg_ctl and skips the Windows
services, so the steps can be checked anywhere. Package layout (see installer/build_zip.ps1):

    HR-Automation\\HRAutomation.exe   runtime\\python\\   runtime\\pgsql\\   runtime\\winsw\\WinSW-x64.exe
    app\\backend\\   app\\frontend\\dist\\
"""

import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from app.platform.install import provision
from app.platform.install.validate import Answers, InvalidInput, check, password_problem

WINDOWS = os.name == "nt"
PG_SERVICE = "HRAutomation-PostgreSQL"
APP_SERVICE = "HRAutomation-App"
VERSION_FILE = "VERSION.txt"


def data_root() -> Path:
    return Path(os.environ.get("PROGRAMDATA", "/var/lib")) / "HRAutomation" if WINDOWS else Path(os.environ.get("HRA_DATA", Path.home() / ".hrautomation"))


def installed_info() -> Optional[dict]:
    f = data_root() / "installed.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


@dataclass
class Options:
    bundle_dir: Path  # the unzipped package (where HRAutomation.exe is)
    install_dir: Path
    web_port: int = 8080
    new_postgres: bool = True
    firewall: bool = False


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) != 0


def check_options(o: Options) -> None:
    p = {}
    if not 1024 <= int(o.web_port) <= 65535:
        p["web_port"] = "Port must be a number from 1024 to 65535 (8080 is usual)."
    elif not port_free(int(o.web_port)) and not installed_info():
        p["web_port"] = f"Port {o.web_port} is already used by another program. Choose another, e.g. 8081."
    text = str(o.install_dir)
    if not text or any(ord(c) < 32 for c in text) or not Path(text).is_absolute():
        p["install_dir"] = "Choose a full folder path, e.g. C:\\Program Files\\HR Automation."
    if p:
        raise InvalidInput(p)


def _run(cmd: list, step: str, **kw) -> str:
    proc = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-8:]
        raise provision.StepFailed(step, (tail[-1] if tail else f"{Path(str(cmd[0])).name} failed")[:300], "\n".join(tail))
    return proc.stdout


def step_files(o: Options) -> dict:
    src, dst = o.bundle_dir.resolve(), o.install_dir.resolve()
    if src == dst:
        return {"copied": False}
    dst.mkdir(parents=True, exist_ok=True)
    # code and runtime are replaced; uploads and .env (data) are kept on an upgrade
    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".env", "uploads", "__pycache__"))
    return {"copied": True, "to": str(dst)}


def _pg_bin(o: Options, name: str) -> Path:
    exe = name + (".exe" if WINDOWS else "")
    bundled = o.install_dir / "runtime" / "pgsql" / "bin" / exe
    if bundled.exists():
        return bundled
    found = shutil.which(name) or next(iter(sorted(Path("/usr/lib/postgresql").glob(f"*/bin/{name}"), reverse=True)), None)
    if not found:
        raise provision.StepFailed("postgres", f"PostgreSQL program {exe} not found in the package.")
    return Path(found)


def free_pg_port(start: int = 5432) -> int:
    for port in range(start, start + 20):
        if port_free(port):
            return port
    raise provision.StepFailed("postgres", "No free port for PostgreSQL between 5432 and 5451.")


def step_postgres(o: Options, a: Answers) -> dict:
    """New PostgreSQL in <data>\\pgdata. Re-run safe: an existing data folder is only (re)started."""
    data = data_root() / "pgdata"
    if (data / "PG_VERSION").exists():
        port = int((data_root() / "pg_port.txt").read_text().strip()) if (data_root() / "pg_port.txt").exists() else a.pg_port
        _start_pg(o, data, port)
        return {"data": str(data), "port": port, "created": False}
    data.parent.mkdir(parents=True, exist_ok=True)
    port = free_pg_port(5432)
    fd, pwfile = tempfile.mkstemp(prefix="hra-", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(a.pg_superuser_password)
        _run([_pg_bin(o, "initdb"), "-D", data, "-U", a.pg_superuser, "--pwfile", pwfile, "-A", "scram-sha-256", "-E", "UTF8",
              "--locale=C"], "postgres")
    finally:
        os.remove(pwfile)
    conf = data / "postgresql.conf"
    conf.write_text(conf.read_text(encoding="utf-8") + f"\n# HR Automation\nport = {port}\nlisten_addresses = 'localhost'\n", encoding="utf-8")
    (data_root() / "pg_port.txt").write_text(str(port))
    if WINDOWS:  # the service runs as NetworkService: it must own the data folder
        _run(["icacls", data, "/grant", "NT AUTHORITY\\NetworkService:(OI)(CI)F", "/T", "/Q"], "postgres")
        _run([_pg_bin(o, "pg_ctl"), "register", "-N", PG_SERVICE, "-D", data, "-S", "auto"], "postgres")
    _start_pg(o, data, port)
    return {"data": str(data), "port": port, "created": True}


def _start_pg(o: Options, data: Path, port: int) -> None:
    if WINDOWS:
        subprocess.run(["sc", "start", PG_SERVICE], capture_output=True)
    else:
        if subprocess.run([str(_pg_bin(o, "pg_ctl")), "status", "-D", str(data)], capture_output=True).returncode != 0:
            _run([_pg_bin(o, "pg_ctl"), "start", "-D", data, "-l", data / "server.log", "-w", "-o", f"-p {port} -k {data}"], "postgres")
    for _ in range(60):
        if not port_free(port):
            return
        time.sleep(1)
    raise provision.StepFailed("postgres", f"PostgreSQL did not start on port {port} (see {data}\\log).")


def _winsw_xml(o: Options) -> str:
    py = o.install_dir / "runtime" / "python" / ("python.exe" if WINDOWS else "python")
    backend = o.install_dir / "app" / "backend"
    logs = data_root() / "logs"
    depend = f"<depend>{PG_SERVICE}</depend>" if o.new_postgres else ""
    return f"""<service>
  <id>{APP_SERVICE}</id>
  <name>HR Automation</name>
  <description>HR Automation web app and API on port {o.web_port}</description>
  <executable>{py}</executable>
  <arguments>-m uvicorn app.web:app --host 0.0.0.0 --port {o.web_port}</arguments>
  <workingdirectory>{backend}</workingdirectory>
  <env name="FRONTEND_DIST" value="{o.install_dir / 'app' / 'frontend' / 'dist'}"/>
  <env name="PYTHONIOENCODING" value="utf-8"/>
  {depend}
  <startmode>Automatic</startmode>
  <onfailure action="restart" delay="10 sec"/>
  <onfailure action="restart" delay="60 sec"/>
  <logpath>{logs}</logpath>
  <log mode="roll-by-size"><sizeThreshold>10240</sizeThreshold><keepFiles>8</keepFiles></log>
</service>
"""


def step_service(o: Options) -> dict:
    url = f"http://localhost:{o.web_port}/"
    (data_root() / "logs").mkdir(parents=True, exist_ok=True)
    if not WINDOWS:
        return {"url": url, "service": "skipped (not Windows): run python -m uvicorn app.web:app"}
    svc_dir = o.install_dir / "service"
    svc_dir.mkdir(parents=True, exist_ok=True)
    exe = svc_dir / f"{APP_SERVICE}.exe"
    shutil.copy2(o.install_dir / "runtime" / "winsw" / "WinSW-x64.exe", exe)
    (svc_dir / f"{APP_SERVICE}.xml").write_text(_winsw_xml(o), encoding="utf-8")
    subprocess.run([str(exe), "stop"], capture_output=True)
    subprocess.run([str(exe), "uninstall"], capture_output=True)  # re-run safe: replace the old definition
    _run([exe, "install"], "service")
    _run([exe, "start"], "service")
    for _ in range(90):  # first start imports everything and runs start-up checks
        if not port_free(o.web_port):
            return {"url": url, "service": APP_SERVICE}
        time.sleep(1)
    raise provision.StepFailed("service", f"The app did not start on port {o.web_port}; see {data_root() / 'logs'}.")


def step_finish(o: Options, a: Answers, version: str) -> dict:
    url = f"http://localhost:{o.web_port}/"
    if WINDOWS:
        if o.firewall:
            subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule", "name=HR Automation"], capture_output=True)
            subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule", "name=HR Automation", "dir=in", "action=allow", "protocol=TCP",
                            f"localport={o.web_port}", "profile=private,domain"], capture_output=True)
        shortcut = f"[InternetShortcut]\r\nURL={url}\r\n"
        for folder in (Path(os.environ.get("PUBLIC", "C:\\Users\\Public")) / "Desktop",
                       Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"):
            try:
                (folder / "HR Automation.url").write_text(shortcut, encoding="utf-8")
            except OSError:
                pass
    info = {"version": version, "install_dir": str(o.install_dir), "url": url, "web_port": o.web_port, "new_postgres": o.new_postgres,
            "pg_port": a.pg_port, "admin_email": a.admin_email, "installed_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    data_root().mkdir(parents=True, exist_ok=True)
    (data_root() / "installed.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


def check_all(a: Answers, o: Options) -> None:
    problems = {}
    for fn in (lambda: check(a), lambda: check_options(o)):
        try:
            fn()
        except InvalidInput as exc:
            problems.update(exc.problems)
    if o.new_postgres:  # this installer sets the PostgreSQL password -> the full rules
        prob = password_problem(a.pg_superuser_password, label="PostgreSQL password")
        if prob:
            problems["pg_superuser_password"] = prob
    if problems:
        raise InvalidInput(problems)


def install(a: Answers, o: Options, say: Callable[[str, str, dict], None]) -> dict:
    """The whole package install. Raises InvalidInput / provision.StepFailed."""
    a.new_postgres = o.new_postgres
    check_all(a, o)
    version = (o.bundle_dir / VERSION_FILE).read_text().strip() if (o.bundle_dir / VERSION_FILE).exists() else "dev"
    results = {}

    def do(step, fn):
        say(step, "start", {})
        r = fn()
        results[step] = r
        say(step, "done", r)
        return r

    do("files", lambda: step_files(o))
    if o.new_postgres:
        pg = do("postgres_server", lambda: step_postgres(o, a))
        a.pg_host, a.pg_port = "localhost", pg["port"]
    a.frontend_url = f"http://localhost:{o.web_port}"
    a.app_base_url = f"http://localhost:{o.web_port}/_api"
    env_path = o.install_dir / "app" / "backend" / ".env"
    # the engine runs from the INSTALLED copy (its python, its backend)
    py = o.install_dir / "runtime" / "python" / ("python.exe" if WINDOWS else "python")
    if py.exists() and Path(sys.executable).resolve() != py.resolve():
        do("engine", lambda: _engine_subprocess(py, o, a, env_path, say))
    else:
        provision.run(a, env_path=env_path, say=say)
    do("service", lambda: step_service(o))
    return do("finish", lambda: step_finish(o, a, version))


def _engine_subprocess(py: Path, o: Options, a: Answers, env_path: Path, say) -> dict:
    """Run the engine with the installed python; answers via a private temp file it deletes."""
    fd, path = tempfile.mkstemp(prefix="hra-answers-", suffix=".json", text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(a.__dict__, f)
    proc = subprocess.Popen([str(py), "-m", "app.platform.install", "--answers", path, "--delete-answers", "--json", "--env", str(env_path)],
                            cwd=o.install_dir / "app" / "backend", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    last = {}
    for line in proc.stdout:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        last = ev
        if ev.get("event") in ("start", "done"):
            say(ev["step"], ev["event"], ev.get("result") or {})
    proc.wait()
    if os.path.exists(path):
        os.remove(path)
    if proc.returncode != 0:
        if last.get("event") == "invalid":
            raise InvalidInput(last.get("problems") or {})
        raise provision.StepFailed(last.get("step", "engine"), last.get("message", "setup failed"), last.get("detail", ""))
    return {"ok": True}


def new_token() -> str:
    return secrets.token_urlsafe(24)
