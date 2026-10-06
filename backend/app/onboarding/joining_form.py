"""Joining details form settings (change 2026-10-05): Settings > Onboarding & employees > Joining details form.

One setting, `onboarding.joining_form` = {"fields": {key: {show, help, check}}, "documents": {code: show}}:
- show: required | optional | hidden. A field with no entry is OPTIONAL (the default for every field); a
  document with no entry keeps the required/optional it has in its own list.
- help: {en, hi, ta} text shown under the field.
- check: format check on/off (PAN, IFSC, Aadhaar, phone, PIN code, email, bank account, date of birth).

Every save is a new setting version (history + revert are the settings history). A form remembers the
version it was opened with (`form_version`), so a change applies to forms opened after saving.
The portal, the backend validation and HR's view all read the rules from here -- nothing is hardcoded.
"""

from typing import Optional

from sqlalchemy.orm import Session

SETTING = "onboarding.joining_form"
SHOWS = ("required", "optional", "hidden")
LANGS = ("en", "hi", "ta")
# kinds whose values have a format check (welcome_steps._check)
CHECKABLE = ("pan", "ifsc", "aadhaar", "phone", "pin", "email", "bank_account", "date")
SECTIONS = (("personal", "Personal details"), ("address", "Address"), ("emergency", "Emergency contact"), ("bank_id", "Bank and ID"))


class FormSettingsError(ValueError):
    pass


def _fields():
    from app.onboarding.welcome_steps import FIELDS

    return FIELDS


def empty() -> dict:
    return {"fields": {}, "documents": {}}


def _clean(value: Optional[dict]) -> dict:
    """Only known keys and allowed values survive (a bad entry falls back to the default)."""
    value = value if isinstance(value, dict) else {}
    keys = {k for k, *_ in _fields()}
    fields = {}
    for key, rule in (value.get("fields") or {}).items():
        if key not in keys or not isinstance(rule, dict):
            continue
        help_text = rule.get("help") if isinstance(rule.get("help"), dict) else {}
        fields[key] = {"show": rule.get("show") if rule.get("show") in SHOWS else "optional",
                       "help": {lang: str(help_text.get(lang) or "").strip()[:300] for lang in LANGS if str(help_text.get(lang) or "").strip()},
                       "check": rule.get("check") is not False}
    documents = {str(c)[:60]: s for c, s in (value.get("documents") or {}).items() if s in SHOWS}
    return {"fields": fields, "documents": documents}


def _row(db: Session, tenant):
    from app.models.setting_value import SettingValue

    return (db.query(SettingValue).filter(SettingValue.tenant_id == tenant.tenant_id, SettingValue.key == SETTING,
                                          SettingValue.scope_type == "tenant").first())


def current(db: Session, tenant) -> dict:
    row = _row(db, tenant)
    return {**_clean(row.value_json if row else None), "version": row.version if row else 0}


def at_version(db: Session, tenant, version: Optional[int]) -> dict:
    """The rules a form was opened with; the current rules when unknown/None."""
    now = current(db, tenant)
    if version is None or version == now["version"]:
        return now
    if version == 0:
        return {**empty(), "version": 0}
    from app.models.setting_value import SettingValueHistory

    h = (db.query(SettingValueHistory).filter(SettingValueHistory.tenant_id == tenant.tenant_id, SettingValueHistory.key == SETTING,
                                              SettingValueHistory.scope_type == "tenant", SettingValueHistory.version == version).first())
    return {**_clean(h.value_json), "version": version} if h is not None else now


def rule(rules: dict, key: str) -> dict:
    r = (rules.get("fields") or {}).get(key) or {}
    return {"show": r.get("show", "optional"), "help": r.get("help", {}), "check": r.get("check", True)}


def document_show(rules: dict, code: str, default_required: bool) -> str:
    return (rules.get("documents") or {}).get(code) or ("required" if default_required else "optional")


def save(db: Session, tenant, value: dict, *, actor: str) -> dict:
    from app.audit.service import log_action
    from app.platform.settings.resolver import SettingsService

    before = current(db, tenant)
    clean = _clean(value)
    if clean["fields"] == before["fields"] and clean["documents"] == before["documents"]:
        return admin_view(db, tenant)
    row = SettingsService(db).set(SETTING, clean, scope_type="tenant", scope_id=None, actor=actor, tenant=tenant)
    log_action(db, "setting", None, "joining_form_saved", actor[:50], {"version": row.version, "changes": _diff(before, clean)})
    return admin_view(db, tenant)


def revert(db: Session, tenant, version: int, *, actor: str) -> dict:
    old = at_version(db, tenant, version)
    if old["version"] != version:
        raise FormSettingsError("That version doesn't exist.")
    return save(db, tenant, {"fields": old["fields"], "documents": old["documents"]}, actor=actor)


def _diff(a: dict, b: dict) -> list[str]:
    out = []
    labels = {k: label for k, label, *_ in _fields()}
    for key in labels:
        ra, rb = rule(a, key), rule(b, key)
        if ra["show"] != rb["show"]:
            out.append(f"{labels[key]}: {ra['show']} -> {rb['show']}")
        if ra["check"] != rb["check"]:
            out.append(f"{labels[key]}: format check {'on' if rb['check'] else 'off'}")
        if ra["help"] != rb["help"]:
            out.append(f"{labels[key]}: help text")
    for code in sorted(set(a.get("documents", {})) | set(b.get("documents", {}))):
        if a.get("documents", {}).get(code) != b.get("documents", {}).get(code):
            out.append(f"Document {code}: {a.get('documents', {}).get(code, 'default')} -> {b.get('documents', {}).get(code, 'default')}")
    return out


def history(db: Session, tenant) -> list[dict]:
    from app.models.setting_value import SettingValueHistory

    rows = (db.query(SettingValueHistory).filter(SettingValueHistory.tenant_id == tenant.tenant_id, SettingValueHistory.key == SETTING,
                                                 SettingValueHistory.scope_type == "tenant").order_by(SettingValueHistory.version.desc()).all())
    out = []
    for i, h in enumerate(rows):
        prev = _clean(rows[i + 1].value_json) if i + 1 < len(rows) else empty()
        out.append({"version": h.version, "updated_by": h.updated_by, "updated_at": h.updated_at.isoformat() if h.updated_at else None,
                    "changes": _diff(prev, _clean(h.value_json))})
    return out


def admin_view(db: Session, tenant) -> dict:
    from app.onboarding.welcome_steps import base_document_list

    rules = current(db, tenant)
    fields = []
    for key, label, kind, section in _fields():
        r = rule(rules, key)
        fields.append({"key": key, "label": label, "kind": kind, "section": section, "checkable": kind in CHECKABLE,
                       "show": r["show"], "help": {lang: r["help"].get(lang, "") for lang in LANGS}, "check": r["check"]})
    documents = [{"code": d["code"], "label": d["label"], "default": "required" if d["required"] else "optional",
                  "show": document_show(rules, d["code"], d["required"])} for d in base_document_list(db, tenant)]
    return {"version": rules["version"], "sections": [{"key": k, "label": label} for k, label in SECTIONS], "fields": fields,
            "documents": documents, "history": history(db, tenant)}
