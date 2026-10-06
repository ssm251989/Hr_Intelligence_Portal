"""Fix 2026-10-04: the welcome portal's built-in steps -- always there, whatever a company configured:

1. Offer signed      done once the offer is signed; "View signed offer" (PDF); a sign link before that.
2. Joining details   personal details, address, emergency contact, bank details, PAN / Aadhaar
                     (format checks; bank account, PAN and Aadhaar kept encrypted and shown masked).
                     Saved as the joiner types (autosave); done when submitted complete.
3. Documents         the configured list (Settings > Onboarding documents, else the joining-documents
                     list from hiring); anything already received earlier counts; phone-camera upload.
4. Day one           start time, office address with a map link, who to meet, what to bring -> "Got it".
5. Contacts card     shown on the page, not counted as a step.
Steps 2-4 unlock after the offer is signed ("Unlocks after you sign your offer").

HR's Onboarding page counts exactly these steps (plus any configured forms / policies).
"""

import re
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.onboarding import PreboardingCase, PreboardingDocument

KEY = "joining_details"
DAY_ONE = "__day_one"
LOCKED = "Unlocks after you sign your offer."

# (key, label, kind, section). Required / optional / hidden, help text and format checks come from
# Settings > Onboarding & employees > Joining details form (app/onboarding/joining_form.py; default:
# every field optional) -- change 2026-10-05, they were hardcoded here before.
FIELDS = (
    ("first_name", "First name", "text", "personal"), ("last_name", "Last name (surname)", "text", "personal"),
    ("preferred_name", "Preferred name (what we should call you)", "text", "personal"), ("date_of_birth", "Date of birth", "date", "personal"),
    ("phone", "Mobile number", "phone", "personal"), ("personal_email", "Personal email", "email", "personal"),
    ("address_line1", "Address line 1", "text", "address"), ("address_line2", "Address line 2", "text", "address"),
    ("city", "City", "text", "address"), ("state", "State", "text", "address"), ("pin_code", "PIN code", "pin", "address"),
    ("emergency_name", "Emergency contact name", "text", "emergency"), ("emergency_relation", "Relationship", "text", "emergency"),
    ("emergency_phone", "Emergency contact mobile", "phone", "emergency"),
    ("bank_account_holder", "Name on bank account", "text", "bank_id"), ("bank_account_number", "Bank account number", "bank_account", "bank_id"),
    ("bank_ifsc", "IFSC code", "ifsc", "bank_id"), ("pan", "PAN", "pan", "bank_id"), ("aadhaar", "Aadhaar number", "aadhaar", "bank_id"),
)
SENSITIVE = {"bank_account_number", "pan", "aadhaar"}
_PATTERNS = {
    "pan": (re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$"), "PAN looks like ABCDE1234F (5 letters, 4 digits, 1 letter)."),
    "ifsc": (re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$"), "IFSC looks like HDFC0001234 (4 letters, 0, then 6 letters or digits)."),
    "bank_account": (re.compile(r"^[0-9]{9,18}$"), "A bank account number has 9 to 18 digits."),
    "pin": (re.compile(r"^[1-9][0-9]{5}$"), "A PIN code has 6 digits."),
    "phone": (re.compile(r"^(\+?91)?[6-9][0-9]{9}$"), "Enter a 10-digit mobile number."),
    "email": (re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"), "Enter a valid email address."),
}

# Verhoeff checksum (Aadhaar)
_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
      [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1], [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
      [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
      [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1], [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def _aadhaar_ok(n: str) -> bool:
    if not re.fullmatch(r"[2-9][0-9]{11}", n):
        return False
    c = 0
    for i, ch in enumerate(reversed(n)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def _clean(key: str, kind: str, value) -> str:
    v = str(value or "").strip()
    if kind in ("pan", "ifsc"):
        v = v.upper().replace(" ", "")
    elif kind in ("bank_account", "aadhaar", "pin"):
        v = re.sub(r"[\s-]", "", v)
    elif kind == "phone":
        v = re.sub(r"[\s-]", "", v)
    elif kind == "email":
        v = v.lower()
    return v


def _check(kind: str, v: str) -> Optional[str]:
    if kind == "aadhaar":
        return None if _aadhaar_ok(v) else "This Aadhaar number isn't valid - please check the 12 digits."
    if kind == "date":
        try:
            d = date.fromisoformat(v)
        except ValueError:
            return "Enter the date as YYYY-MM-DD."
        age = (date.today() - d).days // 365
        return None if 16 <= age <= 80 else "Please check the date of birth."
    if kind in _PATTERNS:
        rx, msg = _PATTERNS[kind]
        return None if rx.match(v) else msg
    return None


def _mask(key: str, v: str) -> str:
    if not v:
        return ""
    if key == "aadhaar":
        return f"XXXX XXXX {v[-4:]}"
    if key == "pan":
        return "XXXXXX" + v[-4:]
    return "X" * max(0, len(v) - 4) + v[-4:]


def _stored(case: PreboardingCase) -> dict:
    return dict((case.form_submissions_json or {}).get(KEY) or {})


def _plain(case: PreboardingCase) -> dict:
    """Saved values with sensitive ones decrypted (server side only)."""
    from app.core.crypto import decrypt

    data = dict(_stored(case).get("data") or {})
    for k in SENSITIVE:
        if str(data.get(k) or "").startswith("enc:"):
            try:
                data[k] = decrypt(data[k][4:])
            except Exception:  # noqa: BLE001
                data[k] = ""
    return data


def _rules(db: Session, tenant, version: Optional[int] = None) -> dict:
    from app.onboarding import joining_form

    return joining_form.at_version(db, tenant, version)


def joining_details_view(db: Session, tenant, case: PreboardingCase, *, version: Optional[int] = None) -> dict:
    """What the joiner's form shows: visible fields only, each with required / help / format check, the
    rules version the form was opened with, and which fields are still empty."""
    from app.onboarding import joining_form

    rules = _rules(db, tenant, version)
    data = _plain(case)
    fields, shown = [], {}
    for k, label, kind, section in FIELDS:
        r = joining_form.rule(rules, k)
        if r["show"] == "hidden":
            continue
        fields.append({"key": k, "label": label, "kind": kind, "section": section, "required": r["show"] == "required",
                       "help": r["help"], "check": r["check"], "sensitive": k in SENSITIVE})
        shown[k] = _mask(k, data.get(k, "")) if k in SENSITIVE else data.get(k, "")
    st = _stored(case)
    return {"fields": fields, "saved": shown, "status": st.get("status", "new"), "submitted_at": st.get("submitted_at"),
            "updated_at": st.get("updated_at"), "form_version": rules["version"], "locked": bool(st.get("locked_at")),
            "missing_required": [f["key"] for f in fields if f["required"] and not shown.get(f["key"])],
            "missing_optional": [f["key"] for f in fields if not f["required"] and not shown.get(f["key"])]}


class DetailsLocked(Exception):
    pass


def save_joining_details(db: Session, tenant, case: PreboardingCase, values: dict, *, submit: bool, form_version: Optional[int] = None) -> dict:
    """Autosave (submit=False) keeps whatever is there, even incomplete; submit=True needs every REQUIRED field.
    Rules come from the settings version the form was opened with. A typed value is format-checked only when
    that field's check is on; empty optional fields are fine; hidden fields are neither shown nor taken."""
    from app.core.crypto import encrypt
    from app.onboarding import joining_form

    if _stored(case).get("locked_at"):
        raise DetailsLocked("HR has locked your joining details. Please contact HR to change anything.")
    rules = _rules(db, tenant, form_version)
    current = _plain(case)
    errors: dict[str, str] = {}
    for key, label, kind, _section in FIELDS:
        if key not in values or joining_form.rule(rules, key)["show"] == "hidden":
            continue
        raw = values.get(key)
        if key in SENSITIVE and isinstance(raw, str) and "X" in raw and current.get(key):  # unchanged masked value
            continue
        current[key] = _clean(key, kind, raw)
    for key, label, kind, _section in FIELDS:
        r = joining_form.rule(rules, key)
        if r["show"] == "hidden":
            continue
        v = current.get(key, "")
        if v:
            msg = _check(kind, v) if r["check"] else None
            if msg:
                errors[key] = msg
        elif submit and r["show"] == "required":
            errors[key] = f"{label} is needed."
    stored = {k: (("enc:" + encrypt(v)) if (k in SENSITIVE and v) else v) for k, v in current.items()}
    now = datetime.now(timezone.utc).isoformat()
    prev = _stored(case)
    status = "submitted" if submit and not errors else ("submitted" if prev.get("status") == "submitted" and not errors and not submit else "draft")
    entry = {**prev, "data": stored, "status": status, "updated_at": now, "form_version": rules["version"],
             "submitted_at": now if status == "submitted" and submit else prev.get("submitted_at")}
    case.form_submissions_json = {**(case.form_submissions_json or {}), KEY: entry}
    if case.status == "invited":
        case.status = "in_progress"
    if status == "submitted":
        _update_employee(db, case, current)
    db.commit()
    return {**joining_details_view(db, tenant, case, version=rules["version"]), "errors": errors}


def hr_details_view(db: Session, tenant, case: PreboardingCase) -> dict:
    """HR's view of the joining details: every visible field with its (masked) value, what is still empty
    (not errors), whether it was sent, and the lock."""
    view = joining_details_view(db, tenant, case)
    st = _stored(case)
    return {"status": view["status"], "submitted_at": view["submitted_at"], "updated_at": view["updated_at"],
            "locked": view["locked"], "locked_by": st.get("locked_by"), "locked_at": st.get("locked_at"),
            "fields": [{"key": f["key"], "label": f["label"], "section": f["section"], "required": f["required"],
                        "value": view["saved"].get(f["key"]) or ""} for f in view["fields"]],
            "missing_required": view["missing_required"], "missing_optional": view["missing_optional"],
            "last_reminder_at": st.get("last_reminder_at")}


def set_lock(db: Session, case: PreboardingCase, *, locked: bool, actor: str) -> None:
    entry = dict(_stored(case))
    entry.update({"locked_at": datetime.now(timezone.utc).isoformat(), "locked_by": actor} if locked else {"locked_at": None, "locked_by": None})
    case.form_submissions_json = {**(case.form_submissions_json or {}), KEY: entry}
    db.commit()


def mark_reminded(db: Session, case: PreboardingCase) -> None:
    entry = dict(_stored(case))
    entry["last_reminder_at"] = datetime.now(timezone.utc).isoformat()
    case.form_submissions_json = {**(case.form_submissions_json or {}), KEY: entry}
    db.commit()


def _update_employee(db: Session, case: PreboardingCase, data: dict) -> None:
    """The pre-hire employee record gets the names / contact details the joiner confirmed."""
    from app.models.core_hr import Employee

    emp = db.get(Employee, case.employee_id) if case.employee_id else None
    if emp is None:
        return
    if data.get("first_name"):
        emp.first_name = data["first_name"]
    emp.last_name = data.get("last_name") or emp.last_name
    emp.preferred_name = data.get("preferred_name") or emp.preferred_name
    emp.personal_email = data.get("personal_email") or emp.personal_email
    emp.personal_phone = data.get("phone") or emp.personal_phone


def joining_details_done(case: PreboardingCase) -> bool:
    return _stored(case).get("status") == "submitted"


# ---------------------------------------------------------------- documents

def document_list(db: Session, tenant) -> list[dict]:
    """The list the joiner sees: the configured documents with Required / Optional / Hidden from
    Settings > Onboarding & employees > Joining details form (hidden ones left out)."""
    from app.onboarding import joining_form

    rules = joining_form.current(db, tenant)
    out = []
    for d in base_document_list(db, tenant):
        show = joining_form.document_show(rules, d["code"], d["required"])
        if show != "hidden":
            out.append({**d, "required": show == "required"})
    return out


def base_document_list(db: Session, tenant) -> list[dict]:
    from app.platform.settings.resolver import SettingContext, SettingsService

    s = SettingsService(db)
    ctx = SettingContext(tenant=tenant)
    configured = s.get("onboarding.documents.required_types", ctx) or []
    if configured:
        from app.experience.ui_onboarding_router import _document_labels, _humanise

        labels = _document_labels(db, tenant, "en")
        return [{"code": c, "label": labels.get(c) or _humanise(c), "required": True} for c in configured]
    from app.recruitment.joining_docs import DEFAULT_REQUIRED

    return [{"code": d["code"], "label": d.get("label") or d["code"], "required": bool(d.get("required", True)),
             "types": d.get("types"), "max_mb": d.get("max_mb")} for d in (s.get("recruitment.documents.required", ctx) or DEFAULT_REQUIRED)]


def documents_view(db: Session, tenant, case: PreboardingCase) -> list[dict]:
    from app.models.candidate_document import CandidateDocument

    earlier = {}
    if case.application_id:
        for d in db.query(CandidateDocument).filter(CandidateDocument.application_id == case.application_id).all():
            earlier.setdefault(d.doc_code, d)
    mine = {}
    for d in db.query(PreboardingDocument).filter(PreboardingDocument.case_id == case.id).order_by(PreboardingDocument.uploaded_at).all():
        mine[d.document_type_code] = d
    out = []
    for doc in document_list(db, tenant):
        code = doc["code"]
        if code in mine:
            st = mine[code].verification_status
            status = {"verified": "verified", "rejected": "rejected"}.get(st, "uploaded")
            reason = mine[code].rejection_reason if st == "rejected" else None
        elif code in earlier and earlier[code].hr_status != "rejected":
            status, reason = "received_earlier", None
        else:
            status, reason = "missing", None
        out.append({**doc, "status": status, "rejection_reason": reason})
    return out


def documents_done(db: Session, tenant, case: PreboardingCase) -> bool:
    return all(d["status"] in ("uploaded", "verified", "received_earlier") for d in documents_view(db, tenant, case) if d["required"])


def upload_document(db: Session, tenant, case: PreboardingCase, code: str, data: bytes, filename: str) -> dict:
    from app.onboarding.portal import UPLOAD_DIR

    allowed = {d["code"]: d for d in document_list(db, tenant)}
    if code not in allowed:
        raise ValueError("This document isn't on the list.")
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    types = allowed[code].get("types") or ["pdf", "jpg", "jpeg", "png", "heic"]
    if ext not in set(types) | ({"jpeg", "heic"} if "jpg" in types else set()):
        raise ValueError(f"Please upload one of: {', '.join(types)}.")
    max_mb = allowed[code].get("max_mb") or 10
    if len(data) > max_mb * 1024 * 1024:
        raise ValueError(f"The file is too big - at most {max_mb} MB.")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4()}.{ext}"
    (UPLOAD_DIR / name).write_bytes(data)
    db.add(PreboardingDocument(tenant_id=tenant.tenant_id, case_id=case.id, document_type_code=code, file_path=name))
    if case.status == "invited":
        case.status = "in_progress"
    db.commit()
    return {"code": code, "status": "uploaded"}


# ---------------------------------------------------------------- day one

def day_one_info(db: Session, tenant, case: PreboardingCase) -> dict:
    from app.models.core_hr import Location
    from app.platform.settings.resolver import SettingContext, SettingsService

    s = SettingsService(db)
    ctx = SettingContext(tenant=tenant)
    loc = (db.query(Location).filter(Location.tenant_id == tenant.tenant_id).order_by(Location.name).first())
    address, map_url = None, None
    if loc is not None:
        parts = [getattr(loc, a, None) for a in ("name", "address_line1", "address_line2", "city", "state", "postal_code", "address")]
        address = ", ".join(dict.fromkeys(str(p) for p in parts if p))
        lat, lng = getattr(loc, "geo_lat", None), getattr(loc, "geo_lng", None)
        map_url = (f"https://www.google.com/maps/search/?api=1&query={lat},{lng}" if lat and lng
                   else f"https://www.google.com/maps/search/?api=1&query={re.sub(r'[ ]+', '+', address or '')}") if address else None
    welcome = case.welcome_content_json or {}
    buddy = welcome.get("buddy") if isinstance(welcome.get("buddy"), dict) else None
    meet = (s.get("onboarding.day_one.meet", ctx) or "").strip() or ((buddy or {}).get("name") or "")
    return {"date": case.joining_date.isoformat(), "start_time": s.get("onboarding.day_one.start_time", ctx) or None,
            "address": address, "map_url": map_url, "meet": meet or None,
            "what_to_bring": [str(x) for x in (s.get("onboarding.day_one.what_to_bring", ctx) or []) if str(x).strip()],
            "agenda": welcome.get("agenda") if isinstance(welcome.get("agenda"), list) else [],
            "acknowledged_at": ((case.form_submissions_json or {}).get(DAY_ONE) or {}).get("at")}


def acknowledge_day_one(db: Session, case: PreboardingCase) -> None:
    case.form_submissions_json = {**(case.form_submissions_json or {}), DAY_ONE: {"at": datetime.now(timezone.utc).isoformat()}}
    db.commit()


# ---------------------------------------------------------------- the steps

def _offer(db: Session, case: PreboardingCase):
    from app.models.offer import Offer

    return db.get(Offer, case.offer_id) if case.offer_id else None


# fix 2026-10-05: every step has its OWN state; English text is sent too, so a page that doesn't know a step
# type still shows a title (the portal's own i18n keys win when it knows the type).
STATE_TEXT = {"locked": "Unlocks after you sign your offer", "not_started": "Not started", "in_progress": "In progress", "done": "Done"}
TEXT = {
    "offer": ("Sign your offer", "Read your offer letter and sign it online"),
    "joining_details": ("Your joining details", "Personal details, address, emergency contact and bank"),
    "joining_documents": ("Upload documents", "ID, education and other documents - phone camera works"),
    "day_one": ("Your first day", "Time, address, who to meet and what to bring"),
}
PORTAL_SCHEMA = 2  # bump when the step payload changes; an older open page reloads itself


def _step(kind: str, code: str, state: str, **extra) -> dict:
    label, description = TEXT[kind]
    if state == "locked":
        extra["locked_reason"] = LOCKED
    return {"kind": kind, "code": code, "label": label, "description": description, "state": state, "status_text": STATE_TEXT[state],
            "done": state == "done", "counted": extra.pop("counted", True), **{"locked_reason": None, **extra}}


def builtin_steps(db: Session, tenant, case: PreboardingCase) -> list[dict]:
    """Offer is done only when the LATEST version is signed (DocuSign: once its envelope is completed). The other
    three are locked until then -- and a locked step is never done, whatever was collected earlier."""
    from app.offers import esign

    offer = _offer(db, case)
    signed = bool(offer.signed) if offer is not None else True  # no offer record (HR started onboarding by hand): nothing to sign
    steps = []
    if offer is not None:
        st = "done" if signed else ("in_progress" if offer.viewed_at else "not_started")
        steps.append(_step("offer", "offer", st, version_no=offer.version_no or 1,
                           signed_at=offer.signed_at.isoformat() if offer.signed_at else None,
                           sign_url=None if signed else esign.sign_url(db, offer), pdf_url=esign.pdf_url(db, offer),
                           expiry_date=offer.expiry_date.isoformat() if offer.expiry_date else None,
                           method="docusign" if (offer.docusign_envelope_id and offer.docusign_sender_id and not signed) else "in_app"))
    locked = not signed
    if locked:
        steps.append(_step("joining_details", KEY, "locked"))
    else:
        view = joining_details_view(db, tenant, case)
        st = "done" if joining_details_done(case) else ("in_progress" if view["status"] == "draft" and any(view["saved"].values()) else "not_started")
        steps.append(_step("joining_details", KEY, st, **view))
    docs = documents_view(db, tenant, case)
    if locked:
        steps.append(_step("joining_documents", "documents", "locked", counted=bool(docs), documents=[]))
    else:
        have = [d for d in docs if d["status"] in ("uploaded", "verified", "received_earlier")]
        st = "done" if (documents_done(db, tenant, case) if docs else True) else ("in_progress" if have else "not_started")
        steps.append(_step("joining_documents", "documents", st, counted=bool(docs), documents=docs))
    info = day_one_info(db, tenant, case)
    if locked:
        steps.append(_step("day_one", "day_one", "locked", info=None))
    else:
        steps.append(_step("day_one", "day_one", "done" if info["acknowledged_at"] else "not_started", info=info))
    db.flush()  # a new sign link token is saved by the caller's commit (the portal page commits)
    return steps


def builtin_progress(db: Session, tenant, case: PreboardingCase) -> tuple[int, int]:
    steps = [s for s in builtin_steps(db, tenant, case) if s["counted"]]
    return sum(1 for s in steps if s["done"]), len(steps)
