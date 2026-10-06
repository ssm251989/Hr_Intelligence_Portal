"""Actionable exit checklist (feat 2026-10-06).

Before: the exit "Handover checklist" listed 5 items as "To do" with no way to finish them -- the employee's
exit page and HR's exit dialog only showed them, the generic Mark done / Skip lived on a hidden "Board" tab,
"Revoke access" revoked nothing and "Exit interview and documents" never completed itself.

Now every item has a status -- To do -> Requested -> Waiting for confirmation -> Done, plus Not applicable
(reason) and Blocked (reason) -- an owner, a due date (the last working day minus the item's days), a history,
and the actions that really complete it:
- one line per ASSET assigned (and the ID / access card lines): HR/Admin "Request return" (email + to-do to the
  employee) -> employee "I have returned it" (note / photo) -> owner "Received" (Good / Damaged / Missing parts;
  the asset goes back In stock) or "Lost / not returned" (recovery amount -> the Finance item). No assets at
  all -> "No assets assigned" (done).
- "Revoke system and email access": "Revoke now" (or on the last working day) disables the app account and
  suspends the company mailbox through the email provider (TEST provider for now); without an email-admin
  connection IT confirms by hand.
- "Settle advances and reimbursements": amounts to recover / pay (lost-asset recoveries added) or Nothing pending.
- "Handover sign-off": the manager's to-do + email; notes, knowledge-transfer document, who takes over -> Sign off.
- "Exit interview and documents": Done by itself once the exit interview is in (or recorded from a call / not
  applicable) AND the relieving + experience letters are generated.
Owners get a to-do and an email; a reminder before the due date; overdue items show red. When every item is
Done / Not applicable and the last working day has passed, the exit completes: letters emailed (PDF) to the
personal email, employee Exited, app login off, mailbox suspended. Settings > Onboarding & employees > Exit
checklist decides the items, owners, due days, required/optional and the auto rule.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.core_hr import Employee
from app.models.service_desk import Asset, AssetAllocation, ClearanceItem, Separation, CLEARANCE_CLOSED, CLEARANCE_OPEN
from app.models.user import User

SETTING = "employees.exit.clearance_items"
OWNER_ROLES = ("it", "admin", "finance", "manager", "hr", "person")
AUTO_RULES = ("manual", "asset_return", "access_revoke", "exit_interview_letters")
KIND_OF = {"access_revoke": "access_revocation", "asset_return": "id_card", "exit_interview_letters": "exit_docs"}
DEPT_OF = {"it": "it", "admin": "admin", "finance": "finance", "manager": "manager", "hr": "hr", "person": "hr"}
DEFAULT = [
    {"key": "it_access", "title": "Revoke system and email access", "owner_role": "it", "due_days_before": 0, "required": True, "auto": "access_revoke"},
    {"key": "cards", "title": "Return ID / access card", "owner_role": "admin", "due_days_before": 0, "required": True, "auto": "asset_return",
     "cards": ["ID card", "Access card"]},
    {"key": "finance", "title": "Settle advances and reimbursements", "owner_role": "finance", "due_days_before": 0, "required": True, "auto": "manual",
     "kind": "finance_settlement"},
    {"key": "handover", "title": "Handover sign-off", "owner_role": "manager", "due_days_before": 1, "required": True, "auto": "manual", "kind": "handover_signoff"},
    {"key": "exit_docs", "title": "Exit interview and documents", "owner_role": "hr", "due_days_before": 0, "required": True, "auto": "exit_interview_letters"},
]
ASSET_OWNER_ROLE = "admin"
UPLOADS = Path(__file__).resolve().parent.parent.parent / "uploads" / "exit"
LETTER_VARS = ["today", "employee_name", "first_name", "employee_code", "designation", "department_text", "joined_on", "last_working_day", "company_name"]


class ChecklistError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> date:
    return date.today()


def _setting(db: Session, tenant, key: str):
    from app.platform.settings.resolver import SettingContext, SettingsService

    return SettingsService(db).get(key, SettingContext(tenant=tenant))


# ---- settings ----


def clean_config(value) -> list[dict]:
    out, seen = [], set()
    for e in value if isinstance(value, list) else []:
        if not isinstance(e, dict) or not str(e.get("title") or "").strip():
            continue
        key = str(e.get("key") or "").strip()[:40] or f"item_{len(out) + 1}"
        if key in seen:
            continue
        seen.add(key)
        auto = e.get("auto") if e.get("auto") in AUTO_RULES else "manual"
        item = {"key": key, "title": str(e["title"]).strip()[:200], "owner_role": e.get("owner_role") if e.get("owner_role") in OWNER_ROLES else "hr",
                "owner_email": (str(e.get("owner_email") or "").strip().lower() or None), "required": e.get("required") is not False,
                "auto": auto, "kind": e.get("kind") or KIND_OF.get(auto, "clearance")}
        try:
            item["due_days_before"] = max(0, min(60, int(e.get("due_days_before") or 0)))
        except (TypeError, ValueError):
            item["due_days_before"] = 0
        if auto == "asset_return":
            item["cards"] = [str(c).strip()[:60] for c in (e.get("cards") or ["ID card", "Access card"]) if str(c).strip()][:6]
        out.append(item)
    return out


def config(db: Session, tenant) -> list[dict]:
    value = _setting(db, tenant, SETTING)
    cfg = clean_config(value)
    # the 20.2 default (a plain list with "title"/"owner") or nothing -> the full default
    return cfg if cfg and all("auto" in (e or {}) for e in (value or [])) else clean_config(DEFAULT)


def save_config(db: Session, tenant, value: list, *, actor: str) -> list[dict]:
    from app.platform.settings.resolver import SettingsService

    clean = clean_config(value)
    if not clean:
        raise ChecklistError("Keep at least one item.")
    SettingsService(db).set(SETTING, clean, scope_type="tenant", scope_id=None, actor=actor, tenant=tenant)
    return config(db, tenant)


# ---- helpers ----


def lwd(s: Separation) -> Optional[date]:
    return s.approved_lwd or s.requested_lwd


def _employee(db: Session, s: Separation) -> Optional[Employee]:
    return db.get(Employee, s.employee_id)


def _name(e: Optional[Employee]) -> str:
    return " ".join(p for p in ((e.first_name, e.last_name) if e else ()) if p) or "the employee"


def _manager_user(db: Session, e: Optional[Employee]) -> Optional[User]:
    from app.employees.directory import current_record

    r = current_record(db, e.id) if e is not None else None
    boss = db.get(Employee, r.manager_employee_id) if r is not None and r.manager_employee_id else None
    return db.get(User, boss.user_id) if boss is not None and boss.user_id else None


def _owner_user(db: Session, s: Separation, entry: dict) -> Optional[User]:
    if entry.get("owner_role") == "manager":
        return _manager_user(db, _employee(db, s))
    if entry.get("owner_email"):
        return db.query(User).filter(User.email == entry["owner_email"]).first()
    return None


def _hist(item: ClearanceItem, actor: str, action: str, note: Optional[str] = None, **extra) -> None:
    item.history_json = [*(item.history_json or []), {"at": _now().isoformat(), "actor": actor, "action": action, **({"note": note} if note else {}), **extra}]


def _set(item: ClearanceItem, status: str, actor: str, action: str, note: Optional[str] = None, **extra) -> None:
    item.status = status
    if status in CLEARANCE_CLOSED:
        item.cleared_by, item.cleared_at = actor[:120], _now()
    _hist(item, actor, action, note, **extra)


def items(db: Session, s: Separation) -> list[ClearanceItem]:
    return (db.query(ClearanceItem).filter(ClearanceItem.tenant_id == s.tenant_id, ClearanceItem.separation_id == s.id)
            .order_by(ClearanceItem.cleared_at.is_(None).desc()).all())


# ---- generate (idempotent) ----


def generate(db: Session, tenant, s: Separation) -> list[ClearanceItem]:
    """Items from the settings + one line per asset assigned; owners, due dates. Re-running only adds what is
    missing and fills owners / due dates on older items (incl. the pre-2026-10-06 five)."""
    e = _employee(db, s)
    end = lwd(s)
    current = items(db, s)
    by_key = {i.item_key: i for i in current if i.item_key}
    by_title = {(i.title or "").lower(): i for i in current}
    added = []
    cfg = config(db, tenant)
    for entry in cfg:
        due = end - timedelta(days=entry["due_days_before"]) if end else None
        if entry["auto"] == "asset_return":  # cards -> asset lines (below)
            old = by_key.get(entry["key"]) or by_title.get(entry["title"].lower())
            if old is not None and old.kind not in ("id_card",) and old.status in CLEARANCE_OPEN:  # the old single "Return ID / access card" line
                _set(old, "not_applicable", "system", "replaced", "Replaced by one line per card")
                old.reason = "Replaced by one line per card"
            continue
        row = by_key.get(entry["key"]) or by_title.get(entry["title"].lower())
        owner = _owner_user(db, s, entry)
        if row is None:
            row = ClearanceItem(tenant_id=tenant.tenant_id, separation_id=s.id, department=DEPT_OF[entry["owner_role"]], title=entry["title"],
                                kind=entry["kind"], status="todo", history_json=[])
            db.add(row)
            _hist(row, "system", "created")
            added.append(row)
        row.item_key, row.kind, row.owner_role, row.auto_rule = entry["key"], entry["kind"], entry["owner_role"], entry["auto"]
        row.blocks_relieving = entry["required"]
        row.due_date = due
        if owner is not None and row.owner_user_id is None:
            row.owner_user_id = owner.id
        row.details_json = {**(row.details_json or {}), "owner_email": entry.get("owner_email")}
    # assets
    allocations = (db.query(AssetAllocation).filter(AssetAllocation.tenant_id == tenant.tenant_id, AssetAllocation.employee_id == s.employee_id).all()
                   if e is not None else [])
    have_alloc = {i.asset_allocation_id for i in current if i.asset_allocation_id}
    cards_entry = next((x for x in cfg if x["auto"] == "asset_return"), None)
    card_names = [c.lower() for c in (cards_entry or {}).get("cards", [])]
    covered_cards = set()
    for al in allocations:
        a = db.get(Asset, al.asset_id)
        if a is None:
            continue
        label = _category_label(db, tenant, a.category_code)
        if label.lower() in card_names:
            covered_cards.add(label.lower())
        if al.id in have_alloc or (al.returned_at is not None and al.returned_at < (s.created_at or _now())):
            continue
        row = ClearanceItem(tenant_id=tenant.tenant_id, separation_id=s.id, department="admin", kind="asset_recovery", asset_allocation_id=al.id,
                            title=f"Return {label} - {a.name}, tag {a.asset_tag}", item_key="asset", owner_role=ASSET_OWNER_ROLE, auto_rule="asset_return",
                            blocks_relieving=True, due_date=end, status="done" if al.returned_at else "todo", history_json=[],
                            details_json={"asset_id": str(a.id), "asset_tag": a.asset_tag, "asset_name": a.name, "asset_type": label})
        db.add(row)
        _hist(row, "system", "created", "Asset assigned to the employee")
        added.append(row)
    if cards_entry is not None:
        have_cards = {(i.details_json or {}).get("card", "").lower() for i in current if i.kind == "id_card"}
        for card in cards_entry["cards"]:
            if card.lower() in covered_cards or card.lower() in have_cards:
                continue
            row = ClearanceItem(tenant_id=tenant.tenant_id, separation_id=s.id, department=DEPT_OF[cards_entry["owner_role"]], kind="id_card",
                                title=f"Return {card}", item_key=cards_entry["key"], owner_role=cards_entry["owner_role"], auto_rule="asset_return",
                                blocks_relieving=cards_entry["required"], status="todo", history_json=[],
                                due_date=end - timedelta(days=cards_entry["due_days_before"]) if end else None, details_json={"card": card})
            db.add(row)
            _hist(row, "system", "created")
            added.append(row)
    real_assets = [al for al in allocations if (db.get(Asset, al.asset_id) is not None)]
    none_line = next((i for i in current if i.kind == "no_assets"), None)
    if not real_assets and none_line is None:
        row = ClearanceItem(tenant_id=tenant.tenant_id, separation_id=s.id, department="admin", kind="no_assets", title="No assets assigned",
                            item_key="asset", owner_role=ASSET_OWNER_ROLE, auto_rule="asset_return", blocks_relieving=False, status="done",
                            history_json=[], cleared_by="system", cleared_at=_now())
        _hist(row, "system", "created", "Nothing was assigned to this person")
        db.add(row)
    elif real_assets and none_line is not None and none_line.status == "done":
        _set(none_line, "not_applicable", "system", "assets_found", "An asset was assigned after all")
        none_line.reason = "An asset was assigned after all"
    if s.status == "approved":
        s.status = "clearance"
    db.commit()
    for row in added:
        if row.status in CLEARANCE_OPEN:
            notify_owner(db, tenant, s, row, kind="assigned")
    refresh_auto(db, tenant, s)
    return items(db, s)


def _category_label(db: Session, tenant, code: str) -> str:
    from app.models.metadata import MasterValue

    v = db.query(MasterValue).filter(MasterValue.tenant_id == tenant.tenant_id, MasterValue.type_code == "asset_category", MasterValue.code == code).first()
    return ((v.label_i18n or {}).get("en") if v else None) or (code or "Asset").replace("_", " ").capitalize()


# ---- who may do what ----


def _is_hr(db: Session, tenant, user: User) -> bool:
    from app.platform.iam.authz import has_permission

    return has_permission(db, tenant, user, "separation.clearance.edit")


def allowed(db: Session, tenant, s: Separation, item: ClearanceItem, user: User) -> list[str]:
    hr = _is_hr(db, tenant, user)
    e = _employee(db, s)
    is_self = e is not None and e.user_id == user.id
    owner = item.owner_user_id == user.id
    can = hr or owner
    st = item.status
    acts: list[str] = []
    if st in CLEARANCE_CLOSED:
        return ["reopen"] if hr and item.kind != "no_assets" else []
    if item.kind in ("asset_recovery", "id_card"):
        if can and st == "todo":
            acts.append("request_return")
        if is_self and st in ("todo", "requested"):
            acts.append("employee_returned")
        if can:
            acts += ["received", "lost"]
    elif item.kind == "access_revocation":
        if can and st in ("todo", "requested", "blocked"):
            acts += ["revoke_now", "revoke_last_day"]
        if can and st == "waiting_confirmation":
            acts.append("confirm_manual")
    elif item.kind == "finance_settlement":
        if can:
            acts.append("settle")
    elif item.kind == "handover_signoff":
        if can:
            acts.append("sign_off")
    elif item.kind == "exit_docs":
        if hr:
            acts += ["generate_letters", "interview_na"]
    elif can:
        acts.append("mark_done")
    if can:
        acts += ["unblock"] if st == "blocked" else ["block"]
        acts.append("not_applicable")
    return acts


# ---- actions ----


def act(db: Session, tenant, s: Separation, item: ClearanceItem, user: User, action: str, data: dict) -> ClearanceItem:
    if action not in allowed(db, tenant, s, item, user):
        raise ChecklistError("You can't do that on this item.")
    actor = user.email
    d = dict(item.details_json or {})
    if action == "request_return":
        item.requested_at = _now()
        _set(item, "requested", actor, "return_requested")
        db.commit()
        _ask_employee_to_return(db, tenant, s, item)
    elif action == "employee_returned":
        d["employee_returned"] = {"at": _now().isoformat(), "note": (data.get("note") or "").strip()[:500] or None, "photo": data.get("photo")}
        item.details_json = d
        _set(item, "waiting_confirmation", actor, "employee_returned", data.get("note"))
        db.commit()
        notify_owner(db, tenant, s, item, kind="returned")
    elif action == "received":
        cond = data.get("condition")
        if cond not in ("good", "damaged", "missing_parts"):
            raise ChecklistError("Choose the condition: Good, Damaged or Missing parts.")
        if item.asset_allocation_id:
            _receive_asset(db, tenant, item, cond, actor, data.get("note"))
        d["received"] = {"at": _now().isoformat(), "by": actor, "condition": cond, "note": data.get("note")}
        item.details_json = d
        _set(item, "done", actor, "received", f"Condition: {cond.replace('_', ' ')}" + (f" - {data['note']}" if data.get("note") else ""))
    elif action == "lost":
        try:
            amount = round(float(data.get("amount") or 0), 2)
        except (TypeError, ValueError):
            raise ChecklistError("Enter the amount to recover (0 if none).")
        if item.asset_allocation_id:
            _receive_asset(db, tenant, item, "lost", actor, data.get("note"))
        d["lost"] = {"at": _now().isoformat(), "by": actor, "amount": amount, "note": data.get("note")}
        item.details_json = d
        item.amount_due = amount
        _set(item, "done", actor, "lost", f"Lost / not returned - recover {amount:g}")
        _add_recovery(db, s, item, amount, actor)
    elif action in ("revoke_now", "revoke_last_day"):
        end = lwd(s)
        if action == "revoke_last_day" and end and end > _today():
            d["scheduled_for"] = end.isoformat()
            item.details_json = d
            _set(item, "requested", actor, "revoke_scheduled", f"Will run on {end.strftime('%d %b %Y')}")
        else:
            _revoke(db, tenant, s, item, actor)
    elif action == "confirm_manual":
        d["it_confirmed"] = {"at": _now().isoformat(), "by": actor, "note": data.get("note")}
        item.details_json = d
        _set(item, "done", actor, "confirmed_by_it", data.get("note"))
    elif action == "settle":
        nothing = bool(data.get("nothing_pending"))
        try:
            recover = round(float(data.get("recover") or 0), 2)
            pay = round(float(data.get("pay") or 0), 2)
        except (TypeError, ValueError):
            raise ChecklistError("Amounts must be numbers.")
        d["settlement"] = {"at": _now().isoformat(), "by": actor, "nothing_pending": nothing and not recover and not pay, "recover": recover, "pay": pay,
                           "note": data.get("note"), "asset_recoveries": d.get("recoveries", [])}
        item.details_json = d
        item.amount_due = recover
        _set(item, "done", actor, "settled", "Nothing pending" if nothing and not recover and not pay else f"Recover {recover:g}, pay {pay:g}")
    elif action == "sign_off":
        if not (data.get("notes") or "").strip():
            raise ChecklistError("Write a few handover notes first.")
        takeover = None
        if data.get("takeover_employee_id"):
            t = db.get(Employee, uuid.UUID(str(data["takeover_employee_id"])))
            takeover = {"employee_id": str(t.id), "name": _name(t), "code": t.employee_code} if t is not None and t.tenant_id == tenant.tenant_id else None
        elif (data.get("takeover_name") or "").strip():  # a manager may not see the employee list -> typed name
            takeover = {"employee_id": None, "name": data["takeover_name"].strip()[:120], "code": None}
        d["handover"] = {"at": _now().isoformat(), "by": actor, "notes": data["notes"].strip()[:4000], "takeover": takeover, "document": data.get("document")}
        item.details_json = d
        _set(item, "done", actor, "signed_off", f"Handed over to {takeover['name']}" if takeover else None)
    elif action == "generate_letters":
        generate_letters(db, tenant, s, actor=actor)
        _hist(item, actor, "letters_generated")
    elif action == "interview_na":
        if not (data.get("reason") or "").strip():
            raise ChecklistError("Give a reason.")
        d["interview_na"] = {"at": _now().isoformat(), "by": actor, "reason": data["reason"].strip()[:300]}
        item.details_json = d
        _hist(item, actor, "exit_interview_not_applicable", data["reason"])
    elif action == "mark_done":
        _set(item, "done", actor, "done", data.get("note"))
    elif action in ("not_applicable", "block"):
        reason = (data.get("reason") or "").strip()
        if not reason:
            raise ChecklistError("Give a reason.")
        item.reason = reason[:500]
        _set(item, "not_applicable" if action == "not_applicable" else "blocked", actor, action, reason)
    elif action == "unblock":
        _set(item, "todo", actor, "unblocked", data.get("note"))
        item.reason = None
    elif action == "reopen":
        _set(item, "todo", actor, "reopened", data.get("note"))
        item.cleared_at = item.cleared_by = item.reason = None
    db.commit()
    log_action(db, "separation", s.id, f"checklist_{action}", actor[:50], {"item": item.title, "status": item.status})
    refresh_auto(db, tenant, s)
    try_complete(db, tenant, s, actor="exit checklist")
    db.refresh(item)
    return item


def _receive_asset(db: Session, tenant, item: ClearanceItem, condition: str, actor: str, note: Optional[str]) -> None:
    """The asset itself: Good / Damaged / Missing parts -> back In stock (available again); Lost -> lost."""
    from app.service_desk import assets as svc

    al = db.get(AssetAllocation, item.asset_allocation_id)
    if al is None or al.returned_at is not None:
        return
    svc_condition = "lost" if condition == "lost" else ("damaged" if condition in ("damaged", "missing_parts") else "good")
    svc.return_asset(db, tenant, al, condition=svc_condition, received_by=actor, notes=(f"{condition.replace('_', ' ')}: {note}" if note else condition.replace("_", " ")))
    a = db.get(Asset, al.asset_id)
    if a is not None and condition != "lost":
        a.status = "in_stock"  # the owner's rule: received back = available to assign again (condition is on the record)
    db.commit()


def _add_recovery(db: Session, s: Separation, item: ClearanceItem, amount: float, actor: str) -> None:
    fin = next((i for i in items(db, s) if i.kind == "finance_settlement"), None)
    if fin is None:
        return
    d = dict(fin.details_json or {})
    d["recoveries"] = [*d.get("recoveries", []), {"item": item.title, "amount": amount, "at": _now().isoformat()}]
    fin.details_json = d
    _hist(fin, actor, "recovery_added", f"{item.title}: {amount:g}")
    if fin.status in CLEARANCE_CLOSED:  # settled before the loss was known -> open again
        _set(fin, "todo", "system", "reopened", "A lost asset added an amount to recover")
    db.commit()


def _revoke(db: Session, tenant, s: Separation, item: ClearanceItem, actor: str) -> None:
    """App login off + company mailbox suspended (email-admin connection; IT to-do if none)."""
    from app.employees import mailboxes

    e = _employee(db, s)
    d = dict(item.details_json or {})
    user = db.get(User, e.user_id) if e is not None and e.user_id else None
    if user is not None and user.deactivated_at is None:
        user.deactivated_at = _now()
    d["app_login"] = "disabled" if user is not None else "no account"
    mb = mailboxes.suspend(db, tenant, e, actor=actor) if e is not None else {"mode": "none"}
    d["mailbox"] = mb
    d["revoked_at"] = _now().isoformat()
    item.details_json = d
    if mb.get("mode") == "it_todo":
        _set(item, "waiting_confirmation", actor, "revoked_login_mailbox_to_it", "App login disabled. IT to suspend the mailbox and confirm.")
    else:
        _set(item, "done", actor, "revoked", f"App login disabled; mailbox {'suspended' if mb.get('mode') == 'provider' else 'none'} ({mb.get('provider') or '-'})")
        d["auto_done_on"] = _today().isoformat()
        item.details_json = d
    db.commit()
    log_action(db, "employee", e.id if e else None, "access_revoked", actor[:50], {"mailbox": mb, "app_login": d["app_login"]})


# ---- exit interview + letters ----


def ensure_letter_templates(db: Session, tenant) -> dict:
    """Default relieving + experience letter templates when the company has none (they were missing entirely)."""
    from app.core_hr import letters
    from app.models.core_hr import LetterTemplate

    keys = {"relieving": _setting(db, tenant, "employees.letters.relieving_template") or "relieving_letter",
            "experience": _setting(db, tenant, "employees.letters.experience_template") or "experience_letter"}
    bodies = {
        "relieving": ("Relieving letter", "<p>{{ today }}</p><p><strong>To whom it may concern</strong></p>"
                      "<p>This is to certify that <strong>{{ employee_name }}</strong> (Employee ID {{ employee_code }}) worked with {{ company_name }} "
                      "as <strong>{{ designation }}</strong> from {{ joined_on }} to {{ last_working_day }}.</p>"
                      "<p>{{ first_name }} has been relieved from their duties at the close of business on {{ last_working_day }}, and all dues and company "
                      "property have been settled.</p><p>We wish {{ first_name }} all the best.</p><p>For {{ company_name }}<br>Human Resources</p>"),
        "experience": ("Experience letter", "<p>{{ today }}</p><p><strong>Experience certificate</strong></p>"
                       "<p>This is to certify that <strong>{{ employee_name }}</strong> (Employee ID {{ employee_code }}) was employed with {{ company_name }} "
                       "from {{ joined_on }} to {{ last_working_day }}. During this time {{ first_name }} worked as <strong>{{ designation }}</strong>"
                       "{{ department_text }}.</p><p>We found {{ first_name }} sincere and dependable, and wish them success in the future.</p>"
                       "<p>For {{ company_name }}<br>Human Resources</p>"),
    }
    for kind, key in keys.items():
        exists = db.query(LetterTemplate).filter(LetterTemplate.tenant_id == tenant.tenant_id, LetterTemplate.key == key, LetterTemplate.status == "published").first()
        if exists is None:
            name, html = bodies[kind]
            # publish() test-renders with the "required" variables only, so list every placeholder the letter uses
            draft = (db.query(LetterTemplate).filter(LetterTemplate.tenant_id == tenant.tenant_id, LetterTemplate.key == key, LetterTemplate.status == "draft",
                                                     LetterTemplate.html_tpl == html).first()
                     or letters.create_draft(db, tenant, key=key[:50], name=name, html_tpl=html))
            draft.variables_schema_json = {"required": LETTER_VARS}
            letters.publish(db, draft)
    return keys


def generate_letters(db: Session, tenant, s: Separation, *, actor: str) -> dict:
    from app.core_hr import letters
    from app.employees.directory import current_record
    from app.models.core_hr import Department

    open_required = [i.title for i in items(db, s) if i.blocks_relieving and i.status in CLEARANCE_OPEN and i.kind != "exit_docs"]
    if open_required:
        raise ChecklistError("Finish these first: " + "; ".join(open_required))
    if s.approved_lwd is None:
        raise ChecklistError("Confirm the last working day first.")
    keys = ensure_letter_templates(db, tenant)
    e = _employee(db, s)
    r = current_record(db, e.id) if e else None
    dep = db.get(Department, r.department_id) if r is not None and r.department_id else None
    ctx = {"employee_name": _name(e), "first_name": (e.preferred_name or e.first_name) if e else "", "employee_code": e.employee_code if e else "",
           "designation": (r.designation if r else None) or "an employee", "department_text": f" in the {dep.name} team" if dep else "",
           "joined_on": (e.joined_on.strftime("%d %b %Y") if e and e.joined_on else "their joining date"),
           "last_working_day": s.approved_lwd.strftime("%d %b %Y"), "today": _today().strftime("%d %b %Y"), "separation_type": s.separation_type,
           "company_name": _setting(db, tenant, "org.display_name") or ""}
    if s.relieving_letter_id is None:
        s.relieving_letter_id = letters.generate_letter(db, tenant, employee_id=s.employee_id, template_key=keys["relieving"], context=ctx, generated_by=actor).id
    if s.experience_letter_id is None:
        s.experience_letter_id = letters.generate_letter(db, tenant, employee_id=s.employee_id, template_key=keys["experience"], context=ctx, generated_by=actor).id
    db.commit()
    log_action(db, "separation", s.id, "exit_letters_generated", actor[:50], {})
    refresh_auto(db, tenant, s)
    return {"relieving_letter_id": str(s.relieving_letter_id), "experience_letter_id": str(s.experience_letter_id)}


def interview_done(s: Separation) -> bool:
    return bool((s.exit_interview_json or {}).get("submitted_at"))


def refresh_auto(db: Session, tenant, s: Separation) -> None:
    """Auto rules: exit docs Done when the interview is in (or not applicable) AND both letters exist; a
    scheduled revoke runs on the last working day."""
    changed = False
    for item in items(db, s):  # a scheduled revoke first, so the letters below can follow in the same run
        d = item.details_json or {}
        if item.kind == "access_revocation" and item.status == "requested" and d.get("scheduled_for") and date.fromisoformat(d["scheduled_for"]) <= _today():
            _revoke(db, tenant, s, item, "system (last working day)")
    rows = items(db, s)
    docs = next((i for i in rows if i.kind == "exit_docs" and i.status in CLEARANCE_OPEN), None)
    if docs is not None and s.approved_lwd is not None:
        d = dict(docs.details_json or {})
        if not interview_done(s) and not d.get("interview_na") and s.approved_lwd < _today():  # never answered by the last day
            d["interview_na"] = {"at": _now().isoformat(), "by": "system", "reason": "Not answered by the last working day"}
            docs.details_json = d
            _hist(docs, "system", "exit_interview_not_applicable", "Not answered by the last working day")
            changed = True
        others_done = not any(i.blocks_relieving and i.status in CLEARANCE_OPEN and i.kind != "exit_docs" for i in rows)
        if others_done and not (s.relieving_letter_id and s.experience_letter_id) and s.status in ("approved", "clearance"):
            if changed:
                db.commit()
            try:
                generate_letters(db, tenant, s, actor="system")  # calls refresh_auto again, which closes the docs item
                _hist(docs, "system", "letters_generated")
                db.commit()
                return
            except Exception:  # noqa: BLE001 -- HR can still press Generate; the reason shows there
                db.rollback()
    for item in items(db, s):
        d = item.details_json or {}
        if item.kind == "exit_docs" and item.status in CLEARANCE_OPEN:
            iv = interview_done(s) or bool(d.get("interview_na"))
            letters_ok = bool(s.relieving_letter_id and s.experience_letter_id)
            if iv and letters_ok:
                how = "recorded from a call" if (s.exit_interview_json or {}).get("filled_by") == "hr_call" else ("not applicable" if d.get("interview_na") else "submitted")
                _set(item, "done", "system", "auto_done", f"Exit interview {how}; relieving and experience letters generated")
                item.details_json = {**d, "auto_done_on": _today().isoformat()}
                changed = True
    if changed:
        db.commit()


# ---- completion ----


def pending(db: Session, s: Separation) -> list[ClearanceItem]:
    return [i for i in items(db, s) if i.status in CLEARANCE_OPEN]


def try_complete(db: Session, tenant, s: Separation, *, actor: str, force_reason: Optional[str] = None) -> bool:
    end = s.approved_lwd
    if s.status != "clearance" or end is None:
        return False
    open_items = [i for i in pending(db, s) if i.blocks_relieving]
    if force_reason is None and (open_items or end >= _today()):  # completes the day AFTER the last working day
        return False
    for i in pending(db, s):
        if not i.blocks_relieving:  # optional items never hold an exit up
            i.reason = "Optional - closed with the exit"
            _set(i, "not_applicable", actor, "closed_with_exit", "Optional item")
    if force_reason is not None:
        if end >= _today():
            raise ChecklistError("The last working day hasn't passed yet.")
        for i in open_items:
            i.reason = f"Closed by HR: {force_reason}"[:500]
            _set(i, "not_applicable", actor, "closed_with_exit", force_reason)
        s.completion_note = force_reason[:2000]
    from app.employees import mailboxes
    from app.employees.directory import current_record

    e = _employee(db, s)
    if e is not None:
        e.status = "exited" if s.separation_type != "absconding" else "absconded"
        e.exited_on = end
        e.rehire_eligible = s.rehire_eligible if s.rehire_eligible is not None else (s.separation_type in ("resignation", "contract_end", "retirement"))
        r = current_record(db, e.id)
        if r is not None and (r.effective_to is None or r.effective_to > end):
            r.effective_to = end
        user = db.get(User, e.user_id) if e.user_id else None
        if user is not None and user.deactivated_at is None:
            user.deactivated_at = _now()
        try:
            if e.company_email and not any((i.details_json or {}).get("mailbox", {}).get("mode") == "provider" for i in items(db, s) if i.kind == "access_revocation"):
                mailboxes.suspend(db, tenant, e, actor=actor)
        except Exception:  # noqa: BLE001 -- the exit completes; the mailbox shows on the access item
            pass
    s.rehire_eligible = e.rehire_eligible if e is not None else s.rehire_eligible
    s.status, s.completed_at = "completed", _now()
    db.commit()
    log_action(db, "separation", s.id, "exit_completed" if force_reason is None else "exit_closed_with_open_items", actor[:50],
               {"open_items": [i.title for i in open_items], "reason": force_reason})
    _email_letters(db, tenant, s, actor=actor)
    _off_interviewer_pools(db, tenant, e, actor=actor)
    try:
        from app.platform.comms.service import dispatch_event

        dispatch_event(db, tenant, "separation.completed", {"separation_id": str(s.id), "employee_id": str(s.employee_id), "last_working_day": end.isoformat()})
    except Exception:  # noqa: BLE001
        pass
    return True


def _off_interviewer_pools(db: Session, tenant, e: Optional[Employee], *, actor: str) -> None:
    """Removed from interviewer pools; future interviews -> HR to-do (20.3)."""
    if e is None:
        return
    from app.models.interviewer_pool import InterviewerPool

    emails = {a.lower() for a in (e.company_email, e.personal_email) if a}
    user = db.get(User, e.user_id) if e.user_id else None
    if user is not None:
        emails.add(user.email.lower())
    removed = []
    for p in db.query(InterviewerPool).filter(InterviewerPool.tenant_id == tenant.tenant_id).all():
        members = [m for m in (p.member_emails_json or []) if str(m).lower() not in emails]
        if len(members) != len(p.member_emails_json or []):
            p.member_emails_json = members
            removed.append(p.name)
    if removed:
        db.commit()
        log_action(db, "employee", e.id, "removed_from_interviewer_pools", actor[:50], {"pools": removed})
    _future_interviews_todo(db, tenant, e, emails, user, actor=actor)


def _future_interviews_todo(db: Session, tenant, e: Employee, emails: set, user: Optional[User], *, actor: str) -> None:
    """Part 20.3: interviews this person was still due to take -> one HR to-do to reassign them (never moved silently)."""
    from sqlalchemy import func, or_

    from app.models.intelligence import AgentSuggestion
    from app.models.interview import Interview

    conds = [func.lower(Interview.interviewer_email).in_(list(emails))] if emails else []
    if user is not None:
        conds.append(Interview.interviewer_id == user.id)
    if not conds:
        return
    rows = (db.query(Interview).filter(Interview.tenant_id == tenant.tenant_id, or_(*conds), Interview.scheduled_at > _now(), Interview.decision.is_(None))
            .order_by(Interview.scheduled_at).all())
    if not rows:
        return
    exists = db.query(AgentSuggestion).filter(AgentSuggestion.tenant_id == tenant.tenant_id, AgentSuggestion.kind == "interviews_reassign",
                                              AgentSuggestion.entity_id == e.id, AgentSuggestion.status == "pending").first()
    payload = {"employee_id": str(e.id), "name": _name(e), "interviews": [{"id": str(i.id), "at": i.scheduled_at.isoformat(), "application_id": str(i.application_id)} for i in rows]}
    title = f"Reassign {len(rows)} interview(s) - {_name(e)} has left"
    if exists is not None:
        exists.title, exists.payload_json = title, payload
    else:
        db.add(AgentSuggestion(tenant_id=tenant.tenant_id, agent="onboarding", kind="interviews_reassign", title=title, entity_type="employee",
                               entity_id=e.id, reviewer_permission="core_hr.employee.edit", payload_json=payload))
    db.commit()
    log_action(db, "employee", e.id, "interviews_reassign_todo", actor[:50], {"count": len(rows)})


def letter_pdf(db: Session, letter_id) -> Optional[bytes]:
    import html as _html
    import re

    from fpdf import FPDF

    from app.models.core_hr import LetterRecord

    rec = db.get(LetterRecord, letter_id)
    if rec is None:
        return None
    text = re.sub(r"<br\s*/?>|</p>|</h\d>|</div>", "\n", rec.rendered_html or "", flags=re.I)
    text = _html.unescape(re.sub(r"<[^>]+>", "", text))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    safe = text.replace("’", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-").encode("latin-1", "replace").decode("latin-1")
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, safe, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 8)
    pdf.multi_cell(0, 5, f"Verification code: {rec.verification_token}", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def _email_letters(db: Session, tenant, s: Separation, *, actor: str) -> None:
    from app.platform.comms.defaults import send_default

    e = _employee(db, s)
    if e is None or s.letters_emailed_at is not None or not (s.relieving_letter_id or s.experience_letter_id):
        return
    to = e.personal_email or ((db.get(User, e.user_id).email) if e.user_id else None)
    if not to:
        return
    files = []
    for lid, name in ((s.relieving_letter_id, "relieving-letter"), (s.experience_letter_id, "experience-letter")):
        if lid:
            data = letter_pdf(db, lid)
            if data:
                files.append({"content": data, "maintype": "application", "subtype": "pdf", "filename": f"{name}-{e.employee_code}.pdf"})
    m = send_default(db, tenant, "employee.exit_letters", to=[to], purpose="email.outbound.hr_letters", related_entity_type="separation", related_entity_id=s.id,
                     ctx={"first_name": e.preferred_name or e.first_name, "last_working_day": s.approved_lwd.strftime("%d %b %Y")}) \
        if not files else _send_with_files(db, tenant, to, e, s, files)
    s.letters_emailed_at = _now()
    db.commit()
    log_action(db, "separation", s.id, "exit_letters_emailed", actor[:50], {"to": to, "email": getattr(m, "status", None), "files": len(files)})


def _send_with_files(db: Session, tenant, to: str, e: Employee, s: Separation, files: list):
    from app.platform.comms.defaults import ensure_template
    from app.platform.comms.service import send
    from app.platform.settings.resolver import SettingContext, SettingsService

    ensure_template(db, tenant, "employee.exit_letters")
    company = SettingsService(db).get("org.display_name", SettingContext(tenant=tenant)) or ""
    return send(db, tenant, template_key="employee.exit_letters", to=[to], purpose="email.outbound.hr_letters", related_entity_type="separation",
                related_entity_id=s.id, attachments=files,
                ctx={"company_name": company, "first_name": e.preferred_name or e.first_name, "last_working_day": s.approved_lwd.strftime("%d %b %Y")})


def extend(db: Session, tenant, s: Separation, new_lwd: date, *, actor: str) -> None:
    if s.status not in ("approved", "clearance"):
        raise ChecklistError("Only an open exit can be extended.")
    old = s.approved_lwd
    s.approved_lwd = new_lwd
    cfg = {c["key"]: c for c in config(db, tenant)}
    for i in items(db, s):
        if i.status in CLEARANCE_OPEN:
            days = (cfg.get(i.item_key) or {}).get("due_days_before", 0)
            i.due_date = new_lwd - timedelta(days=days)
            if i.kind == "access_revocation" and (i.details_json or {}).get("scheduled_for"):  # "on the last working day" follows the new day
                i.details_json = {**i.details_json, "scheduled_for": new_lwd.isoformat()}
                _hist(i, actor, "revoke_scheduled", f"Moved to {new_lwd.strftime('%d %b %Y')}")
    if old != new_lwd and s.letters_emailed_at is None and (s.relieving_letter_id or s.experience_letter_id):
        # the letters carry the last working day -> make them again (unsent ones only)
        s.relieving_letter_id = s.experience_letter_id = None
        for i in items(db, s):
            if i.kind == "exit_docs" and i.status == "done":
                _set(i, "todo", actor, "reopened", "Last working day changed - the letters will be made again")
                i.cleared_at = i.cleared_by = None
            if i.kind == "exit_docs":
                i.due_date = new_lwd
    db.commit()
    log_action(db, "separation", s.id, "exit_last_day_extended", actor[:50], {"from": old.isoformat() if old else None, "to": new_lwd.isoformat()})


# ---- owners: to-dos, emails, reminders ----


def _owner_emails(db: Session, tenant, s: Separation, item: ClearanceItem) -> list[str]:
    if item.owner_user_id:
        u = db.get(User, item.owner_user_id)
        return [u.email] if u is not None and u.deactivated_at is None else []
    if (item.details_json or {}).get("owner_email"):
        return [item.details_json["owner_email"]]
    # a team role without a named person -> the HR people who handle exits
    from app.platform.iam.authz import has_permission

    out = []
    for u in db.query(User).filter(User.tenant_id == tenant.tenant_id, User.deactivated_at.is_(None), User.role.in_(("admin",))).all():
        if not u.email.endswith("@example.com") and has_permission(db, tenant, u, "separation.clearance.edit"):
            out.append(u.email)
    return out[:3]


def _is_demo(db: Session, s: Separation) -> bool:
    e = _employee(db, s)
    return bool(e is not None and (e.custom_fields or {}).get("demo") is True)


def notify_owner(db: Session, tenant, s: Separation, item: ClearanceItem, *, kind: str) -> bool:
    """Assigned / returned / reminder email to the item's owner. Demo employees (hrctl demo employees) never email real staff."""
    from app.platform.comms.defaults import send_default
    from app.platform.links import public_app_url

    if _is_demo(db, s) and kind != "assigned_demo_ok":
        to = [a for a in _owner_emails(db, tenant, s, item) if a.endswith("@example.com")]
    else:
        to = _owner_emails(db, tenant, s, item)
    if not to:
        return False
    e = _employee(db, s)
    key = {"assigned": "employee.exit_task_assigned", "returned": "employee.exit_task_returned", "reminder": "employee.exit_task_reminder"}[kind]
    end = lwd(s)
    try:
        send_default(db, tenant, key, to=to, purpose="email.outbound.hr_letters", related_entity_type="separation", related_entity_id=s.id,
                     ctx={"item": item.title, "name": _name(e), "last_day": end.strftime("%d %b %Y") if end else "not set yet",
                          "due": item.due_date.strftime("%d %b %Y") if item.due_date else "the last working day", "link": f"{public_app_url(db)}/exits?item={item.id}"})
    except Exception:  # noqa: BLE001 -- the to-do is still in their list
        return False
    return True


def _ask_employee_to_return(db: Session, tenant, s: Separation, item: ClearanceItem) -> None:
    from app.platform.comms.defaults import send_default
    from app.platform.links import public_app_url

    e = _employee(db, s)
    user = db.get(User, e.user_id) if e is not None and e.user_id else None
    to = [a for a in dict.fromkeys([user.email if user else None, e.company_email if e else None]) if a]
    if not to:
        return
    d = item.details_json or {}
    what = f"{d.get('asset_type')} - {d.get('asset_name')}, tag {d.get('asset_tag')}" if d.get("asset_tag") else (d.get("card") or item.title)
    end = lwd(s)
    send_default(db, tenant, "employee.asset_return_request", to=to[:1], purpose="email.outbound.hr_letters", related_entity_type="separation",
                 related_entity_id=s.id, ctx={"first_name": (e.preferred_name or e.first_name) if e else "", "what": what,
                                              "by": end.strftime("%d %b %Y") if end else "your last working day", "link": f"{public_app_url(db)}/exits"})


def run_reminders(db: Session, tenant) -> dict:
    """Hourly: scheduled revokes on the last day, auto rules, one reminder per item the day before it is due, completion."""
    sent = completed = 0
    for s in db.query(Separation).filter(Separation.tenant_id == tenant.tenant_id, Separation.status.in_(("approved", "clearance"))).all():
        refresh_auto(db, tenant, s)
        for i in pending(db, s):
            if i.due_date and i.due_date - timedelta(days=1) <= _today() and i.last_reminder_at is None:
                sent += 1 if notify_owner(db, tenant, s, i, kind="reminder") else 0
                i.last_reminder_at = _now()
        db.commit()
        if try_complete(db, tenant, s, actor="exit checklist"):
            completed += 1
    return {"reminders": sent, "completed": completed}


# ---- views ----


def item_dict(db: Session, tenant, s: Separation, i: ClearanceItem, user: Optional[User]) -> dict:
    owner = db.get(User, i.owner_user_id) if i.owner_user_id else None
    d = dict(i.details_json or {})
    return {"id": str(i.id), "title": i.title, "kind": i.kind, "status": i.status, "owner_role": i.owner_role, "department": i.department,
            "owner_name": (owner.full_name or owner.email) if owner else None, "owner_email": owner.email if owner else d.get("owner_email"),
            "due_date": i.due_date.isoformat() if i.due_date else None, "required": bool(i.blocks_relieving), "reason": i.reason, "auto_rule": i.auto_rule,
            "overdue": bool(i.due_date and i.due_date < _today() and i.status in CLEARANCE_OPEN), "details": d, "history": i.history_json or [],
            "amount_due": float(i.amount_due) if i.amount_due is not None else None, "done_by": i.cleared_by,
            "done_at": i.cleared_at.isoformat() if i.cleared_at else None, "actions": allowed(db, tenant, s, i, user) if user is not None else []}


def view(db: Session, tenant, s: Separation, user: User) -> dict:
    generate(db, tenant, s) if s.status in ("approved", "clearance") else None
    rows = [item_dict(db, tenant, s, i, user) for i in items(db, s)]
    rows.sort(key=lambda r: (r["status"] in CLEARANCE_CLOSED, {"asset_recovery": 0, "id_card": 1, "no_assets": 2}.get(r["kind"], 3), r["due_date"] or "9999"))
    done = sum(1 for r in rows if r["status"] in CLEARANCE_CLOSED)
    end = lwd(s)
    open_n = len(rows) - done
    e = _employee(db, s)
    return {"separation_id": str(s.id), "status": s.status, "last_working_day": end.isoformat() if end else None, "items": rows, "done": done, "total": len(rows),
            "percent": round(100 * done / len(rows)) if rows else 0, "pending": open_n,
            "past_last_day": bool(end and end < _today()), "pending_after_last_day": bool(end and end < _today() and open_n),
            "can_manage": _is_hr(db, tenant, user), "completion_note": s.completion_note,
            "letters": {"relieving": str(s.relieving_letter_id) if s.relieving_letter_id else None, "experience": str(s.experience_letter_id) if s.experience_letter_id else None},
            "letters_emailed_at": s.letters_emailed_at.isoformat() if s.letters_emailed_at else None,
            "employee": {"id": str(e.id), "name": _name(e), "code": e.employee_code, "status": e.status} if e else None}


def save_upload(tenant, data: bytes, filename: str) -> str:
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext not in ("pdf", "png", "jpg", "jpeg", "webp", "docx", "doc", "txt"):
        raise ChecklistError("Please upload a PDF, image or Word file.")
    if len(data) > 10 * 1024 * 1024:
        raise ChecklistError("That file is larger than 10 MB.")
    folder = UPLOADS / str(tenant.tenant_id)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4()}.{ext}"
    (folder / name).write_bytes(data)
    return f"{tenant.tenant_id}/{name}"
