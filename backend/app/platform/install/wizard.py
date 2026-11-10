"""The setup screen HRAutomation.exe opens in the browser (Part 28).

    runtime\\python\\python.exe -m app.platform.install.wizard --bundle <unzipped folder>

A tiny local web server (Python standard library only -- nothing here needs .env or the database):
http://127.0.0.1:<random port>/?t=<one-time token>. Only this computer can reach it, and only with the
token. The page asks the questions, checks them with the SAME rules as everywhere else (validate.py),
then runs windows.install(...) and shows each step. It stops itself when the person closes it.
"""

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.platform.install import provision, windows
from app.platform.install.validate import Answers, InvalidInput

STATE = {"events": [], "running": False, "finished": None, "failed": None}
LOCK = threading.Lock()


def _defaults(bundle: Path) -> dict:
    pf = os.environ.get("ProgramFiles", "C:\\Program Files") if windows.WINDOWS else str(Path.home() / "hr-automation")
    return {"install_dir": str(Path(pf) / "HR Automation") if windows.WINDOWS else pf, "web_port": 8080, "new_postgres": True,
            "pg_port": 5432, "pg_host": "localhost", "bundle": str(bundle)}


def _split(data: dict, bundle: Path) -> tuple[Answers, windows.Options]:
    opt_keys = {"install_dir", "web_port", "new_postgres", "firewall"}
    o = windows.Options(bundle_dir=bundle, install_dir=Path(str(data.get("install_dir") or "")),
                        web_port=int(data.get("web_port") or 0), new_postgres=bool(data.get("new_postgres", True)),
                        firewall=bool(data.get("firewall")))
    answers = {k: v for k, v in data.items() if k not in opt_keys and k not in ("pg_password2", "admin_password2", "app_db_password2")}
    if "pg_port" in answers:
        answers["pg_port"] = int(answers["pg_port"] or 0)
    answers.setdefault("activate_modules", False)
    return Answers.from_dict(answers), o


def _say(step, state, result):
    with LOCK:
        STATE["events"].append({"step": step, "state": state, "result": result, "at": time.time()})


def _install(data: dict, bundle: Path):
    try:
        a, o = _split(data, bundle)
        info = windows.install(a, o, _say)
        STATE["finished"] = info
    except InvalidInput as exc:
        STATE["failed"] = {"problems": exc.problems}
    except provision.StepFailed as exc:
        STATE["failed"] = {"step": exc.step, "message": exc.message, "detail": exc.detail}
    except Exception as exc:  # noqa: BLE001 -- shown on the page, never a silent stop
        STATE["failed"] = {"step": "unexpected", "message": f"{type(exc).__name__}: {exc}"}
    finally:
        STATE["running"] = False


class Handler(BaseHTTPRequestHandler):
    token = ""
    bundle = Path(".")
    server_ref = None

    def log_message(self, *args):  # quiet console
        pass

    def _ok(self) -> bool:
        q = parse_qs(urlparse(self.path).query)
        if (q.get("t") or [""])[0] != self.token or self.client_address[0] not in ("127.0.0.1", "::1"):
            self._send(403, {"error": "forbidden"})
            return False
        return True

    def _send(self, code, obj, ctype="application/json"):
        body = obj.encode("utf-8") if isinstance(obj, str) else json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}") if n else {}

    def do_GET(self):  # noqa: N802
        if not self._ok():
            return
        path = urlparse(self.path).path
        if path == "/":
            return self._send(200, PAGE.replace("__DEFAULTS__", json.dumps(_defaults(self.bundle))), "text/html")
        if path == "/api/progress":
            with LOCK:
                return self._send(200, {"events": STATE["events"], "running": STATE["running"], "finished": STATE["finished"], "failed": STATE["failed"]})
        self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if not self._ok():
            return
        path = urlparse(self.path).path
        data = self._body()
        if path == "/api/check":
            try:
                a, o = _split(data, self.bundle)
                a.new_postgres = o.new_postgres
                windows.check_all(a, o)
                return self._send(200, {"ok": True})
            except InvalidInput as exc:
                return self._send(200, {"ok": False, "problems": exc.problems})
        if path == "/api/install":
            if STATE["running"]:
                return self._send(409, {"error": "already running"})
            STATE.update(events=[], running=True, finished=None, failed=None)
            threading.Thread(target=_install, args=(data, self.bundle), daemon=True).start()
            return self._send(200, {"started": True})
        if path == "/api/close":
            self._send(200, {"bye": True})
            threading.Thread(target=self.server_ref.shutdown, daemon=True).start()
            return None
        self._send(404, {"error": "not found"})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="setup wizard")
    ap.add_argument("--bundle", type=Path, default=Path(__file__).resolve().parents[5])
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)
    Handler.token, Handler.bundle = windows.new_token(), args.bundle.resolve()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    Handler.server_ref = server
    url = f"http://127.0.0.1:{server.server_address[1]}/?t={Handler.token}"
    print(f"WIZARD_URL={url}", flush=True)
    if not args.no_browser:
        import webbrowser

        webbrowser.open(url)
    print("HR Automation setup is open in your browser. Keep this window open until setup finishes.", flush=True)
    server.serve_forever()
    return 0


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>HR Automation setup</title>
<style>
:root{--ink:#1d2433;--quiet:#5b6578;--line:#dfe3ea;--brand:#0f766e;--bad:#b42318;--bg:#f6f7f9}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,Segoe UI,sans-serif;color:var(--ink);background:var(--bg)}
main{max-width:720px;margin:32px auto;padding:0 16px}h1{font-size:24px;margin:0 0 4px}p.lead{color:var(--quiet);margin:0 0 24px}
section{background:#fff;border:1px solid var(--line);border-radius:12px;padding:20px;margin-bottom:16px}
h2{font-size:16px;margin:0 0 12px}label{display:block;font-weight:600;margin:12px 0 4px}small{color:var(--quiet);font-weight:400}
input[type=text],input[type=email],input[type=password],input[type=number]{width:100%;padding:10px;border:1px solid var(--line);border-radius:8px;font:inherit}
input.bad{border-color:var(--bad)}.err{color:var(--bad);font-size:13px;min-height:0}.row{display:flex;gap:12px}.row>div{flex:1}
.choice{display:flex;gap:16px;margin-top:6px}button{background:var(--brand);color:#fff;border:0;border-radius:8px;padding:12px 20px;font:600 15px system-ui;cursor:pointer}
button[disabled]{opacity:.5;cursor:default}ol#steps{padding-left:20px}ol#steps li{margin:6px 0}.done{color:var(--brand)}.fail{color:var(--bad)}
pre{white-space:pre-wrap;background:#f1f3f6;padding:10px;border-radius:8px;font-size:12px}
</style></head><body><main>
<h1>Install HR Automation</h1><p class="lead">Answer a few questions. Everything else (database, tables, your company, your admin account, the Windows services) is set up for you.</p>
<form id="f" autocomplete="off" novalidate>
<section><h2>Your company</h2>
<label>Company name<input type="text" name="company_name" required></label><div class="err" data-for="company_name"></div>
<label>Short name <small>(lower-case letters, digits, "-"; e.g. ctd-techs)</small><input type="text" name="company_slug"></label><div class="err" data-for="company_slug"></div></section>
<section><h2>Administrator (you)</h2>
<label>Full name<input type="text" name="admin_name"></label><div class="err" data-for="admin_name"></div>
<label>Work email <small>(you sign in with it)</small><input type="email" name="admin_email"></label><div class="err" data-for="admin_email"></div>
<div class="row"><div><label>Password<input type="password" name="admin_password"></label></div><div><label>Type it again<input type="password" name="admin_password2"></label></div></div>
<div class="err" data-for="admin_password"></div><small>10+ characters, a letter and a digit, no spaces at the start or end. Symbols like @ # are fine.</small></section>
<section><h2>Database</h2>
<div class="choice"><label><input type="radio" name="new_postgres" value="1" checked> Install the database for me <small>(recommended)</small></label>
<label><input type="radio" name="new_postgres" value="0"> Use my existing PostgreSQL</label></div>
<div id="existing" hidden><div class="row"><div><label>Server<input type="text" name="pg_host" value="localhost"></label><div class="err" data-for="pg_host"></div></div>
<div><label>Port<input type="number" name="pg_port" value="5432"></label><div class="err" data-for="pg_port"></div></div></div></div>
<div class="row"><div><label><span id="pglabel">Choose a database admin password</span><input type="password" name="pg_superuser_password"></label></div><div id="pg2"><label>Type it again<input type="password" name="pg_password2"></label></div></div>
<div class="err" data-for="pg_superuser_password"></div>
<div class="row"><div><label>Choose the app's database password<input type="password" name="app_db_password"></label></div><div><label>Type it again<input type="password" name="app_db_password2"></label></div></div>
<div class="err" data-for="app_db_password"></div><small>Keep these passwords somewhere safe. The app stores them for itself; you only need them for support or a move to another computer.</small></section>
<section><h2>Where and how</h2>
<label>Install folder<input type="text" name="install_dir"></label><div class="err" data-for="install_dir"></div>
<label>Web address port <small>(people open http://this-computer:port)</small><input type="number" name="web_port"></label><div class="err" data-for="web_port"></div>
<label style="font-weight:400"><input type="checkbox" name="firewall"> Let other computers on the office network open it (Windows Firewall)</label></section>
<button id="go" type="submit">Install</button> <span class="err" id="top"></span>
</form>
<section id="progress" hidden><h2>Installing...</h2><ol id="steps"></ol><div id="result"></div></section>
</main><script>
const D=__DEFAULTS__, T=new URLSearchParams(location.search).get('t'), f=document.getElementById('f');
const LABELS={files:'Copying the program files',postgres_server:'Installing the database',postgres:'Checking the database',databases:'Creating the app login and databases',env:'Saving settings',migrate:'Creating tables',grants:'Giving the app access',company:'Creating your company',base_data:'Adding base data',admin:'Creating your admin account',modules:'Requesting your modules from CTD Techs',engine:'Setting up',service:'Starting HR Automation (Windows service)',finish:'Shortcuts'};
f.install_dir.value=D.install_dir; f.web_port.value=D.web_port;
const newPg=()=>f.querySelector('input[name=new_postgres]:checked').value==='1';
f.querySelectorAll('input[name=new_postgres]').forEach(r=>r.onchange=()=>{document.getElementById('existing').hidden=newPg();
 document.getElementById('pg2').hidden=!newPg(); document.getElementById('pglabel').textContent=newPg()?'Choose a database admin password':"PostgreSQL 'postgres' password";});
function data(){const o={};for(const el of f.elements){if(!el.name||el.type==='radio')continue;o[el.name]=el.type==='checkbox'?el.checked:el.value;}
 o.new_postgres=newPg(); o.web_port=+o.web_port||0; o.pg_port=+o.pg_port||5432; if(o.company_slug)o.company_slug=o.company_slug.trim(); return o;}
function show(p){document.querySelectorAll('.err[data-for]').forEach(e=>{e.textContent=p[e.dataset.for]||'';const i=f.elements[e.dataset.for];if(i&&i.classList)i.classList.toggle('bad',!!p[e.dataset.for]);});
 document.getElementById('top').textContent=Object.keys(p).length?'Please fix the fields marked in red.':'';}
async function post(u,b){const r=await fetch(u+'?t='+T,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});return r.json();}
f.company_name.oninput=()=>{if(!f.company_slug.dataset.touched)f.company_slug.value=f.company_name.value.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'').slice(0,40);};
f.company_slug.oninput=()=>f.company_slug.dataset.touched=1;
f.onsubmit=async e=>{e.preventDefault();const d=data(),p={};
 if(d.admin_password!==d.admin_password2)p.admin_password='The two admin passwords are different.';
 if(d.app_db_password!==d.app_db_password2)p.app_db_password='The two app database passwords are different.';
 if(d.new_postgres&&d.pg_superuser_password!==d.pg_password2)p.pg_superuser_password='The two database admin passwords are different.';
 if(Object.keys(p).length)return show(p);
 const c=await post('/api/check',d); if(!c.ok)return show(c.problems); show({});
 document.getElementById('go').disabled=true; await post('/api/install',d); f.hidden=true; document.getElementById('progress').hidden=false; poll();};
async function poll(){const r=await (await fetch('/api/progress?t='+T)).json(),ol=document.getElementById('steps'),seen={};ol.innerHTML='';
 for(const ev of r.events){seen[ev.step]=ev.state;}
 for(const [s,st] of Object.entries(seen)){const li=document.createElement('li');li.textContent=(LABELS[s]||s)+(st==='done'?' - done':' ...');li.className=st==='done'?'done':'';ol.appendChild(li);}
 const res=document.getElementById('result');
 if(r.finished){document.querySelector('#progress h2').textContent='HR Automation is installed';
  res.innerHTML='<p>Open <a href="'+r.finished.url+'">'+r.finished.url+'</a> and sign in with <b>'+r.finished.admin_email+'</b>. A shortcut "HR Automation" is on the desktop.</p><p><small>Your modules were requested from CTD Techs; they switch on when CTD Techs approves.</small></p><button onclick="post(\'/api/close\',{}).then(()=>location.href=\''+r.finished.url+'\')">Open HR Automation</button>';return;}
 if(r.failed){document.querySelector('#progress h2').textContent='Setup stopped';
  if(r.failed.problems){f.hidden=false;document.getElementById('progress').hidden=true;document.getElementById('go').disabled=false;return show(r.failed.problems);}
  res.innerHTML='<p class="fail">'+(LABELS[r.failed.step]||r.failed.step)+': '+(r.failed.message||'')+'</p>'+(r.failed.detail?'<pre>'+r.failed.detail.replace(/</g,'&lt;')+'</pre>':'')+
   '<p>Fix the problem and press Try again - finished steps are not repeated.</p><button onclick="location.reload()">Try again</button>';return;}
 setTimeout(poll,1000);}
</script></body></html>"""


if __name__ == "__main__":
    sys.exit(main())
