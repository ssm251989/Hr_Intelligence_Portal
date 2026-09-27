"""Part 17.11: every registered setting -> save a changed (valid) value through the real API,
read it back, and where the value surfaces somewhere (branding, bootstrap, map config,
shortlist threshold ...) check it shows there too. Writes docs/ui/SETTINGS_CHECK.md.

Everything runs on ONE database connection inside a transaction that is rolled back at the
end, so the company's real settings are never changed. Signed-in user = an existing admin
supplied by a dependency override (no password, no token).

    .venv/Scripts/python.exe scripts/settings_check.py [--tenant ctd-techs]
"""

import argparse
import copy
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

OUT = Path(__file__).resolve().parents[2] / "docs" / "ui" / "SETTINGS_CHECK.md"

# key -> (where it shows, how to read it: method, path, extractor)
SHOWS = {
    "org.display_name": ("Company name in the menu, sign-in page and careers site", "/api/v1/public/branding", lambda d: d.get("product_name")),
    "org.support_email": ("Support contact on public pages", "/api/v1/public/branding", lambda d: d.get("support_contact")),
    "org.timezone": ("Dates and times in the app", "/api/me/bootstrap", lambda d: d.get("tz")),
    # the app language is the base language ("hi-IN" -> "hi"), and a person's own choice wins
    "org.locale": ("Language of the app (company default)", "/api/v1/public/branding?probe=locale", None),
    # always-on modules (home, recruitment, settings) are added to the chosen ones
    "platform.modules.enabled": ("Which modules are in the menu", "/api/me/bootstrap", lambda d: d.get("modules")),
    "geo.tile_url": ("Map tiles on every map", "/api/v1/geo/config", lambda d: d.get("tile_url")),
    "geo.tile_attribution": ("Map credit line", "/api/v1/geo/config", lambda d: d.get("attribution")),
    "geo.countries": ("Which countries maps accept", "/api/v1/geo/config", lambda d: d.get("countries")),
    "recruitment.scoring.shortlist_threshold": ("Shortlist threshold on the Screening dashboard", "/screening/settings", lambda d: d.get("shortlist_threshold")),
    "recruitment.shortlisting.auto_shortlist": ("Shortlisting rules form", "/api/v1/scoring/shortlisting", lambda d: d.get("auto_shortlist")),
    "recruitment.shortlisting.undo_hours": ("Shortlisting rules form", "/api/v1/scoring/shortlisting", lambda d: d.get("undo_hours")),
    "recruitment.shortlisting.max_size": ("Shortlisting rules form", "/api/v1/scoring/shortlisting", lambda d: d.get("max_size")),
    "recruitment.shortlisting.notify": ("Shortlisting rules form", "/api/v1/scoring/shortlisting", lambda d: d.get("notify")),
}


def changed_value(defn, current):
    """A different value that should pass validation (None = only a same-value round trip)."""
    t, key = defn.type, defn.key
    schema = defn.json_schema or {}
    if t == "bool":
        return not bool(current)
    if t == "int":
        cur = int(current or 0)
        hi = schema.get("maximum")
        return cur + 1 if hi is None or cur + 1 <= hi else cur - 1
    if t == "decimal":
        cur = float(current or 0)
        return round(cur + 0.05, 2) if cur < 1 else cur + 1
    if t == "email":
        return "settings-check@example.com"
    if t == "str":
        cur = current or ""
        if key.endswith("timezone"):
            return "Asia/Dubai" if cur != "Asia/Dubai" else "Asia/Kolkata"
        if key.endswith("locale"):
            return "hi-IN" if cur != "hi-IN" else "en-IN"
        if key.endswith("currency"):
            return "USD" if cur != "USD" else "INR"
        if "url" in key and cur.startswith("http"):
            return cur + ("&" if "?" in cur else "?") + "check=1"
        return (cur + " (check)") if cur else "check"
    return None  # json / others: same-value round trip


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", default="ctd-techs")
    args = parser.parse_args()

    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    import app.main as main_mod
    from app.auth import dependencies as deps
    from app.core.config import settings
    from app.core.database import get_db
    from app.models.user import User
    from app.platform.settings.bootstrap_definitions import register_all
    from app.platform.settings.registry import all_definitions

    register_all()
    conn = create_engine(settings.APP_DATABASE_URL).connect()
    outer = conn.begin()

    def db_override():
        db = Session(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield db
        finally:
            db.close()

    def as_admin(request: deps.Request, db=deps.Depends(get_db)):
        return db.query(User).filter(User.role == "admin").order_by(User.created_at).first()

    app = main_mod.app
    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[deps.get_current_user] = as_admin
    app.dependency_overrides[deps.get_current_user_optional] = as_admin
    client = TestClient(app)

    def values():
        return {r["key"]: r["value"] for r in client.get("/api/v1/settings").json()}

    rows = []
    try:
        before = values()
        for defn in sorted(all_definitions(), key=lambda d: d.key):
            key = defn.key
            if defn.sensitive or defn.type == "secret_ref":
                rows.append((key, defn.group, defn.type, "skipped", "skipped", "n/a", "secret - never shown or checked here"))
                continue
            if "tenant" not in defn.scopes_allowed:
                rows.append((key, defn.group, defn.type, "n/a", "n/a", "n/a", f"per-person setting (scope {', '.join(defn.scopes_allowed)}), saved from its own screen"))
                continue
            current = copy.deepcopy(before.get(key, defn.default))
            target = changed_value(defn, current)
            note = ""
            resp = client.put(f"/api/v1/settings/{key}", json={"value": target if target is not None else current, "scope_type": "tenant"})
            if resp.status_code != 200 and target is not None:
                note = f"changed value refused ({resp.json().get('detail', resp.status_code)!s:.80}) - checked with the same value"
                target = None
                resp = client.put(f"/api/v1/settings/{key}", json={"value": current, "scope_type": "tenant"})
            expected = target if target is not None else current
            saved = "OK" if resp.status_code == 200 else f"FAILED {resp.status_code}: {str(resp.json().get('detail'))[:80]}"
            got = values().get(key, "<missing>") if resp.status_code == 200 else None
            reloaded = "OK" if resp.status_code == 200 and got == expected else ("-" if resp.status_code != 200 else f"FAILED (read back {got!r})")
            shows = "n/a (used by server logic)"
            if key in SHOWS and resp.status_code == 200:
                where, path, pick = SHOWS[key]
                if key == "org.locale":
                    seen = client.get("/api/me/bootstrap").json().get("locale")
                    base = str(expected).split("-")[0]
                    from app.models.setting_value import SettingValue

                    with Session(bind=conn, join_transaction_mode="create_savepoint") as s2:
                        own = s2.query(SettingValue).filter(SettingValue.key == "org.locale", SettingValue.scope_type == "user").first()
                    if seen == base:
                        shows = f"OK - {where}: app language '{seen}'"
                    elif own is not None and str(own.value_json).split("-")[0] == seen:
                        shows = f"OK - {where}: the signed-in admin chose '{seen}' for themselves, which wins over the company default (as designed)"
                    else:
                        shows = f"FAILED - {where}: shows '{seen}', expected '{base}'"
                elif key == "platform.modules.enabled":
                    seen = pick(client.get(path).json()) or []
                    shows = f"OK - {where}" if set(expected) <= set(seen) else f"FAILED - {where}: shows {seen!r}"
                else:
                    seen = pick(client.get(path).json())
                    shows = f"OK - {where}" if seen == expected else f"FAILED - {where}: shows {seen!r}"
            if target is None and not note:
                note = "same-value round trip (list/object setting)"
            rows.append((key, defn.group, defn.type, saved, reloaded, shows, note))
    finally:
        app.dependency_overrides.clear()
        outer.rollback()
        conn.close()

    ok = sum(1 for r in rows if r[3] in ("OK", "n/a") and r[4] in ("OK", "n/a") and not r[5].startswith("FAILED"))
    failed = [r for r in rows if r[3].startswith("FAILED") or r[4].startswith("FAILED") or r[5].startswith("FAILED")]
    lines = [
        "# Settings check (Part 17.11)",
        "",
        "Every registered setting, saved through the real API (`PUT /api/v1/settings/{key}`) with a changed, valid value, read back "
        "(`GET /api/v1/settings`), and - where the value shows up somewhere - checked there. Everything ran inside a database "
        "transaction that was rolled back, so no real setting was changed. Re-run: `backend/.venv/Scripts/python.exe backend/scripts/settings_check.py`.",
        "",
        f"**Result: {ok} of {len(rows)} settings OK, {len(failed)} failed, "
        f"{sum(1 for r in rows if r[3] == 'skipped')} secrets skipped.**",
        "",
        "Settings kept on their own pages (not in this registry) were checked separately in FIXES_17.md 17.11: company logo, "
        "brand colours, mailboxes/connections, email templates, approval steps, custom fields, roles.",
        "",
        "| Setting | Group | Type | Saved | Reloaded | Shows in app | Note |",
        "|---|---|---|---|---|---|---|",
    ]
    lines += [f"| `{r[0]}` | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | {r[6]} |" for r in rows]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{ok}/{len(rows)} OK, {len(failed)} failed -> {OUT}")
    for r in failed:
        print("FAILED", r)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
