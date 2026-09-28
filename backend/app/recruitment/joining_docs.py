"""Part 18.16/18.17: joining documents -- asked for automatically after the salary is approved,
checked by the agent as they arrive, approved by HR, then the candidate moves to BGV.

Settings (Settings > Hiring > Required documents):
- recruitment.documents.required   list of {code, label, required, types, max_mb, job_types?}
- recruitment.documents.auto_send  email the form as soon as the salary is approved (default on)
- recruitment.documents.reminder_hours  [24, 72] -- reminders while required documents are missing
Checks per file (green ok / amber check / red problem, with reasons): readable, looks like the
right document, the candidate's name appears, the same name / date of birth across documents,
expiry dates in the past. AI (Claude) adds a judgement when it is switched on; the rule checks
run either way. Nothing is ever marked approved by the agent -- HR approves.
"""

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument
from app.models.job_role import JobRole

FORM_ACTION = "joining_documents_form"
FORM_TTL_DAYS = 21
BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = BACKEND_ROOT / "uploads" / "joining-docs"
TYPES = {"pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
# joining document -> BGV document type (copied into BGV when HR approves)
TO_BGV = {"pan": "pan", "aadhaar": "aadhaar", "education": "degree", "experience": "experience"}

DEFAULT_REQUIRED = [
    {"code": "pan", "label": "PAN card", "required": True, "types": ["pdf", "jpg", "png"], "max_mb": 5},
    {"code": "aadhaar", "label": "Aadhaar card", "required": True, "types": ["pdf", "jpg", "png"], "max_mb": 5},
    {"code": "education", "label": "Education certificates", "required": True, "types": ["pdf", "jpg", "png"], "max_mb": 10},
    {"code": "experience", "label": "Experience letters", "required": False, "types": ["pdf", "jpg", "png"], "max_mb": 10},
    {"code": "payslips", "label": "Last 3 payslips", "required": True, "types": ["pdf", "jpg", "png"], "max_mb": 10},
    {"code": "relieving", "label": "Relieving letter", "required": False, "types": ["pdf", "jpg", "png"], "max_mb": 5},
    {"code": "photo", "label": "Passport-size photo", "required": True, "types": ["jpg", "png"], "max_mb": 2},
]

# rule checks: what a document of this kind usually contains
_KEYWORDS = {
    "pan": [r"income\s*tax", r"permanent\s+account", r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"],
    "aadhaar": [r"aadhaar|aadhar|unique\s+identification", r"\b\d{4}\s?\d{4}\s?\d{4}\b"],
    "education": [r"degree|diploma|certificate|university|marks|grade|bachelor|master|b\.?tech|m\.?tech"],
    "experience": [r"experience|employ|worked|designation|relieved|service"],
    "payslips": [r"pay\s*slip|salary|earnings|deductions|net\s+pay|gross"],
    "relieving": [r"reliev|release|last\s+working\s+day"],
}


def _setting(db, tenant, key):
    from app.platform.settings.resolver import SettingContext, SettingsService

    return SettingsService(db).get(key, SettingContext(tenant=tenant))


def required_for(db: Session, tenant, job: Optional[JobRole]) -> list[dict]:
    items = _setting(db, tenant, "recruitment.documents.required") or DEFAULT_REQUIRED
    jt = getattr(job, "job_type", None) if job else None
    return [i for i in items if not i.get("job_types") or (jt and jt in i["job_types"])]


def form_link(token: str) -> str:
    from app.core.config import settings as app_settings

    return f"{app_settings.FRONTEND_URL.rstrip('/')}/documents/{token}"


def _open_token(db, tenant, application):
    from app.models.iam import ActionToken

    return (db.query(ActionToken).filter(ActionToken.tenant_id == tenant.tenant_id, ActionToken.entity_type == "application",
                                         ActionToken.entity_id == application.id, ActionToken.action == FORM_ACTION,
                                         ActionToken.invalidated_at.is_(None), ActionToken.expires_at > datetime.now(timezone.utc))
            .order_by(ActionToken.created_at.desc()).first())


def send_form(db: Session, tenant, application: Application, *, actor: str = "system", reminder: bool = False,
              reupload: Optional[list[dict]] = None, note: Optional[str] = None) -> dict:
    """Email the "Documents upload" link (reusing an open one). `reupload` = the documents HR asked for again."""
    from app.platform.comms.defaults import send_default
    from app.platform.iam.action_tokens import create_action_token

    cand = db.get(Candidate, application.candidate_id)
    job = db.get(JobRole, application.job_role_id)
    if cand is None or not cand.email:
        return {"sent": False, "reason": "no email"}
    row = _open_token(db, tenant, application)
    if row is not None and row.responded_at is not None and reupload:
        row.responded_at = None  # the same link opens again for the re-uploads
        db.commit()
    if row is None:
        row = create_action_token(db, tenant, entity_type="application", entity_id=application.id, action=FORM_ACTION,
                                  payload={"reminders": 0}, created_by=actor[:50], ttl_days=FORM_TTL_DAYS)
    link = form_link(row.token)
    key = "recruitment.documents_reupload" if reupload else "recruitment.documents_request"
    items = reupload or required_for(db, tenant, job)
    listing = "\n".join(f"- {i['label']}{'' if i.get('required', True) else ' (optional)'}{(': ' + i['note']) if i.get('note') else ''}" for i in items)
    try:
        msg = send_default(db, tenant, key, to=[cand.email], related_entity_type="application", related_entity_id=application.id,
                           ctx={"candidate_first_name": (cand.full_name or "").split(" ")[0], "job_title": job.title if job else "",
                                "form_link": link, "documents": listing, "note": note or "", "reminder": reminder})
        sent = msg.status in ("sent", "queued")
    except Exception:  # noqa: BLE001 -- HR can share the link instead
        sent = False
    log_action(db, "application", application.id, "documents_reupload_requested" if reupload else "documents_form_reminder" if reminder else "documents_form_sent",
               actor[:50], {"sent": sent, "documents": [i["code"] for i in items]})
    return {"sent": sent, "link": None if sent else link}


def after_salary_approved(db: Session, tenant, application: Application, actor: str = "system") -> Optional[dict]:
    """Part 18.16: salary auto- or HR-approved -> the documents form goes out (setting)."""
    if not _setting(db, tenant, "recruitment.documents.auto_send"):
        return None
    if _open_token(db, tenant, application) is not None:
        return None
    return send_form(db, tenant, application, actor=actor)


def status(db: Session, tenant, application: Application) -> dict:
    job = db.get(JobRole, application.job_role_id)
    req = required_for(db, tenant, job)
    docs = db.query(CandidateDocument).filter(CandidateDocument.tenant_id == tenant.tenant_id, CandidateDocument.application_id == application.id).order_by(CandidateDocument.uploaded_at).all()
    by_code: dict = {}
    for d in docs:
        by_code.setdefault(d.doc_code, []).append(d)
    items = []
    for r in req:
        files = by_code.get(r["code"], [])
        live = [f for f in files if f.hr_status != "reupload"]
        items.append({**r, "files": [_doc(f) for f in files], "received": bool(live),
                      "approved": bool(live) and all(f.hr_status == "approved" for f in live),
                      "reupload_note": next((f.hr_note for f in reversed(files) if f.hr_status == "reupload"), None) if not live else None,
                      "level": _worst([f.check_level for f in live])})
    missing = [i["code"] for i in items if i.get("required", True) and not i["received"]]
    return {"application_id": str(application.id), "items": items, "missing": missing,
            "all_received": not missing, "all_approved": all(i["approved"] for i in items if i["received"]) and not missing,
            "reds": sum(1 for i in items if i["level"] == "red"), "ambers": sum(1 for i in items if i["level"] == "amber")}


def _worst(levels):
    levels = [x for x in levels if x]
    return "red" if "red" in levels else "amber" if "amber" in levels else "green" if levels else None


def _doc(d: CandidateDocument) -> dict:
    return {"id": str(d.id), "code": d.doc_code, "name": d.original_name, "size": d.size_bytes, "level": d.check_level,
            "reasons": (d.check_output or {}).get("reasons", []), "hr_status": d.hr_status, "hr_note": d.hr_note,
            "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None}


def save_upload(db: Session, tenant, application: Application, code: str, filename: str, content_type: str, data: bytes) -> CandidateDocument:
    job = db.get(JobRole, application.job_role_id)
    spec = next((r for r in required_for(db, tenant, job) if r["code"] == code), None)
    if spec is None:
        raise ValueError("This document isn't on the list.")
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext not in spec.get("types", ["pdf", "jpg", "png"]) or ext not in TYPES:
        raise ValueError(f"Please upload one of: {', '.join(t.upper() for t in spec.get('types', []))}.")
    if len(data) > int(spec.get("max_mb", 5)) * 1024 * 1024:
        raise ValueError(f"That file is larger than {spec.get('max_mb', 5)} MB.")
    folder = UPLOAD_DIR / str(tenant.tenant_id)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4()}.{ext}"
    (folder / name).write_bytes(data)
    doc = CandidateDocument(tenant_id=tenant.tenant_id, application_id=application.id, doc_code=code, label=spec["label"],
                            file_path=f"{tenant.tenant_id}/{name}", original_name=filename[:200], content_type=TYPES[ext], size_bytes=len(data))
    db.add(doc)
    db.commit()
    check_document(db, tenant, doc)
    log_action(db, "application", application.id, "document_uploaded", "candidate", {"code": code, "level": doc.check_level})
    return doc


# ---------------------------------------------------------------- the agent's check (18.17)

def _text_of(doc: CandidateDocument) -> str:
    from app.bgv.document_extraction import extract_bgv_text

    try:
        return extract_bgv_text((UPLOAD_DIR / doc.file_path).read_bytes(), doc.original_name or doc.file_path)
    except Exception:  # noqa: BLE001
        return ""


_DATE = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b")


def check_document(db: Session, tenant, doc: CandidateDocument) -> None:
    cand = db.get(Candidate, db.get(Application, doc.application_id).candidate_id)
    text = _text_of(doc)
    reasons: list[dict] = []
    is_image = (doc.content_type or "").startswith("image/")
    readable = len(text.strip()) >= 30 and not text.startswith("[Image document")
    if doc.doc_code == "photo":
        if not is_image:
            reasons.append({"level": "red", "code": "not_photo"})
    elif not readable:
        reasons.append({"level": "amber", "code": "not_readable"})
    else:
        pats = _KEYWORDS.get(doc.doc_code)
        if pats and not any(re.search(p, text, re.I) for p in pats):
            reasons.append({"level": "red", "code": "wrong_type"})
        name = (cand.full_name or "").replace("Demo - ", "").strip() if cand else ""
        parts = [p for p in re.split(r"\s+", name.lower()) if len(p) > 2]
        if parts and not any(p in text.lower() for p in parts):
            reasons.append({"level": "amber", "code": "name_missing", "name": name})
        for m in _DATE.finditer(text):
            window = text[max(0, m.start() - 40): m.start()].lower()
            if re.search(r"valid|expir|till|upto|up to", window):
                try:
                    d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                    if d < date.today():
                        reasons.append({"level": "red", "code": "expired", "date": d.isoformat()})
                except ValueError:
                    pass
    ai = _ai_check(db, tenant, doc, text) if readable and doc.doc_code in TO_BGV else None
    if ai:
        if ai.get("validation_status") == "invalid":
            reasons.append({"level": "red", "code": "ai_problem", "issues": ai.get("issues", [])[:3]})
        elif ai.get("validation_status") == "needs_review":
            reasons.append({"level": "amber", "code": "ai_check", "issues": ai.get("issues", [])[:3]})
    level = "red" if any(r["level"] == "red" for r in reasons) else "amber" if reasons else "green"
    fields = (ai or {}).get("extracted_fields") or {}
    doc.check_level, doc.check_output = level, {"reasons": reasons, "readable": readable, "ai": bool(ai), "fields": fields,
                                                "checked_at": datetime.now(timezone.utc).isoformat()}
    db.commit()


def _ai_check(db, tenant, doc, text) -> Optional[dict]:
    try:
        from app.platform.ai.governance import feature_enabled

        if not feature_enabled(db, tenant, "recruitment.document_check"):
            return None
        from app.ai_services.document_validator import validate_document

        return validate_document(TO_BGV[doc.doc_code], text[:6000])
    except Exception:  # noqa: BLE001 -- AI off / unreachable: the rule checks stand
        return None


def cross_check(db: Session, tenant, application: Application) -> list[dict]:
    """Same name / date of birth across the documents the AI could read."""
    docs = db.query(CandidateDocument).filter(CandidateDocument.application_id == application.id, CandidateDocument.hr_status != "reupload").all()
    names = {(d.check_output or {}).get("fields", {}).get("name") for d in docs} - {None, ""}
    dates = {(d.check_output or {}).get("fields", {}).get("date") for d in docs if d.doc_code in ("pan", "aadhaar")} - {None, ""}
    out = []
    if len({n.strip().lower() for n in names}) > 1:
        out.append({"level": "amber", "code": "names_differ", "names": sorted(names)})
    if len(dates) > 1:
        out.append({"level": "amber", "code": "dob_differs", "dates": sorted(dates)})
    return out


# ---------------------------------------------------------------- HR review (18.17)

def approve(db: Session, tenant, application: Application, *, actor: str, doc_ids: Optional[list[str]] = None) -> dict:
    now = datetime.now(timezone.utc)
    q = db.query(CandidateDocument).filter(CandidateDocument.tenant_id == tenant.tenant_id, CandidateDocument.application_id == application.id,
                                           CandidateDocument.hr_status == "pending")
    if doc_ids:
        q = q.filter(CandidateDocument.id.in_(doc_ids))
    n = 0
    for d in q:
        d.hr_status, d.reviewed_by, d.reviewed_at = "approved", actor[:200], now
        n += 1
    db.commit()
    log_action(db, "application", application.id, "documents_approved", actor[:50], {"count": n})
    st = status(db, tenant, application)
    moved = False
    if st["all_approved"] and application.status == "salary_approved":
        moved = move_to_bgv(db, tenant, application, actor=actor)
    return {"approved": n, "moved_to_bgv": moved, "status": status(db, tenant, application)}


def request_reupload(db: Session, tenant, application: Application, *, actor: str, codes: list[str], note: Optional[str]) -> dict:
    job = db.get(JobRole, application.job_role_id)
    spec = {r["code"]: r for r in required_for(db, tenant, job)}
    codes = [c for c in codes if c in spec]
    if not codes:
        raise ValueError("Choose which documents to ask for again.")
    now = datetime.now(timezone.utc)
    for d in db.query(CandidateDocument).filter(CandidateDocument.tenant_id == tenant.tenant_id, CandidateDocument.application_id == application.id,
                                                CandidateDocument.doc_code.in_(codes), CandidateDocument.hr_status != "reupload"):
        d.hr_status, d.hr_note, d.reviewed_by, d.reviewed_at = "reupload", note, actor[:200], now
    db.commit()
    result = send_form(db, tenant, application, actor=actor, reupload=[{**spec[c], "note": note} for c in codes], note=note)
    return {"requested": codes, **result}


def move_to_bgv(db: Session, tenant, application: Application, *, actor: str) -> bool:
    """All documents approved -> BGV starts, with the matching documents already in it."""
    import shutil

    from app.bgv.storage import UPLOAD_DIR as BGV_DIR
    from app.models.bgv_document import BgvDocument

    for d in db.query(CandidateDocument).filter(CandidateDocument.application_id == application.id, CandidateDocument.hr_status == "approved",
                                                CandidateDocument.doc_code.in_(list(TO_BGV))):
        src = UPLOAD_DIR / d.file_path
        if not src.is_file():
            continue
        BGV_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4()}{src.suffix}"
        shutil.copyfile(src, BGV_DIR / name)
        db.add(BgvDocument(tenant_id=tenant.tenant_id, application_id=application.id, doc_type=TO_BGV[d.doc_code], file_path=name))
    previous = application.status
    application.status = "bgv_requested"
    db.commit()
    log_action(db, "application", application.id, "bgv_requested", actor[:50], {"previous_status": previous, "reason": "documents approved"})
    return True


def remind_due(db: Session, tenant) -> int:
    """Hourly: remind while required documents are still missing (recruitment.documents.reminder_hours)."""
    from app.models.iam import ActionToken

    hours = sorted(int(h) for h in (_setting(db, tenant, "recruitment.documents.reminder_hours") or [24, 72]) if int(h) > 0)
    if not hours:
        return 0
    now = datetime.now(timezone.utc)
    done = 0
    for row in db.query(ActionToken).filter(ActionToken.tenant_id == tenant.tenant_id, ActionToken.action == FORM_ACTION,
                                            ActionToken.responded_at.is_(None), ActionToken.invalidated_at.is_(None),
                                            ActionToken.created_at < now - timedelta(hours=hours[0]), ActionToken.expires_at > now):
        sent = int((row.payload_json or {}).get("reminders", 0))
        if sent >= len(hours) or now - row.created_at < timedelta(hours=hours[sent]):
            continue
        app = db.get(Application, row.entity_id)
        if app is None or status(db, tenant, app)["all_received"]:
            continue
        send_form(db, tenant, app, reminder=True)
        row.payload_json = {**(row.payload_json or {}), "reminders": sent + 1}
        db.commit()
        done += 1
    return done
