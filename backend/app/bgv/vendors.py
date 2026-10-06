"""Part 21.4: background checks -- [Download all] and BGV vendors.

Download all: one ZIP per candidate (folder per document type, "<Candidate> - <Document>.<ext>") + a summary Excel of
statuses; bulk from the BGV list (up to BULK_INLINE candidates at once, more is prepared in the background and
offered from the HR notifications). Audit-logged.

Assign BGV vendor: an agency of type BGV / Both, the checks it offers (subset), a due date. The vendor gets an email
with a secure link that expires (`recruitment.bgv.vendor_link_days`, 14) and shows ONLY this candidate's documents,
where they can download them and upload their report.
  Assigned -> In progress (vendor opened the link) -> Report received -> HR decision (the existing decision step:
  Clear / Discrepancy / Failed / Resend form).
Reminders to the vendor the day before the due date and every 2 days after it (max 3). Reassign (the old link stops)
and Cancel (link stops). The report shows in the candidate's BGV section and HR is told.
"""

import io
import re
import secrets
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.agency import BgvAssignment, RecruitmentAgency
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole

OPEN = ("assigned", "in_progress", "report_received")
BULK_INLINE = 20
REPORT_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "bgv" / "vendor-reports"
EXPORT_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "exports"


class VendorError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _setting(db: Session, tenant, key: str):
    from app.platform.settings.resolver import SettingContext, SettingsService

    return SettingsService(db).get(key, SettingContext(tenant=tenant))


def _safe(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "-", (text or "").strip())[:80] or "file"


# ---- documents + Download all ----


def documents(db: Session, application: Application) -> list[dict]:
    """Every document HR has for this candidate's background check: BGV documents + joining documents."""
    from app.bgv.storage import resolve_bgv_path
    from app.models.bgv_document import BgvDocument
    from app.models.candidate_document import CandidateDocument
    from app.recruitment.joining_docs import UPLOAD_DIR as JOINING_DIR

    out = []
    for d in db.query(BgvDocument).filter(BgvDocument.application_id == application.id).all():
        if d.file_path:
            p = resolve_bgv_path(d.file_path)
            out.append({"id": f"b-{d.id}", "type": d.doc_type, "label": d.doc_type.replace("_", " ").title(), "path": p, "ext": p.suffix.lstrip(".") or "pdf",
                        "status": d.validation_status})
    for d in db.query(CandidateDocument).filter(CandidateDocument.application_id == application.id).all():
        p = JOINING_DIR / d.file_path
        ext = (Path(d.original_name).suffix.lstrip(".") if d.original_name else "") or p.suffix.lstrip(".") or "pdf"
        out.append({"id": f"j-{d.id}", "type": d.doc_code, "label": d.label or d.doc_code.replace("_", " ").title(), "path": p, "ext": ext,
                    "status": d.hr_status})
    return out


def _names(db: Session, application: Application) -> tuple[str, str]:
    cand = db.get(Candidate, application.candidate_id)
    job = db.get(JobRole, application.job_role_id)
    return (cand.full_name if cand and cand.full_name else "Candidate"), (job.title if job else "")


def _summary_xlsx(rows: list[list]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "BGV summary"
    ws.append(["Candidate", "Job", "BGV status", "Document", "Type", "Document status", "In the ZIP"])
    for r in rows:
        ws.append(r)
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 22
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_zip(db: Session, applications: list[Application]) -> tuple[bytes, dict]:
    buf = io.BytesIO()
    summary, counts = [], {"candidates": 0, "files": 0, "missing": 0}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for app in applications:
            name, job = _names(db, app)
            base = f"{_safe(name)}/" if len(applications) > 1 else ""
            counts["candidates"] += 1
            for d in documents(db, app):
                exists = d["path"].exists()
                if exists:
                    arc = f"{base}{_safe(d['label'])}/{_safe(name)} - {_safe(d['label'])}.{d['ext']}"
                    z.write(d["path"], arc)
                    counts["files"] += 1
                else:
                    counts["missing"] += 1
                summary.append([name, job, app.status, d["label"], d["type"], d["status"], "yes" if exists else "file missing"])
        z.writestr("BGV summary.xlsx", _summary_xlsx(summary))
    return buf.getvalue(), counts


def bulk_export(tenant_id, export_id: str, app_ids: list, actor: str) -> None:
    """Background: a large Download all, written to uploads/exports; HR is told in the app when it is ready."""
    from app.core.database import SessionLocal
    from app.models.comms import OutboundMessage
    from app.platform.tenancy.context import get_current_tenant

    db = SessionLocal()
    try:
        apps = db.query(Application).filter(Application.id.in_(app_ids)).all()
        data, counts = build_zip(db, apps)
        folder = EXPORT_DIR / str(tenant_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"bgv-{export_id}.zip").write_bytes(data)
        db.add(OutboundMessage(tenant_id=tenant_id, channel="in_app", purpose="recruitment.bgv", to_addresses=[actor], status="sent",
                               subject=f"Your BGV download is ready ({counts['candidates']} candidates, {counts['files']} files)",
                               body_ref=f"/api/v1/ui/bgv/exports/{export_id}", related_entity_type="bgv_export"))
        db.commit()
        log_action(db, "bgv_export", None, "bgv_download_all_ready", actor[:50], {"export_id": export_id, **counts})
    finally:
        db.close()


def export_path(tenant, export_id: str) -> Optional[Path]:
    p = EXPORT_DIR / str(tenant.tenant_id) / f"bgv-{_safe(export_id)}.zip"
    return p if p.exists() else None


# ---- vendors ----


def vendors(db: Session, tenant) -> list[dict]:
    rows = db.query(RecruitmentAgency).filter(RecruitmentAgency.tenant_id == tenant.tenant_id, RecruitmentAgency.active.is_(True),
                                              RecruitmentAgency.agency_type.in_(("bgv", "both"))).order_by(RecruitmentAgency.name).all()
    return [{"id": str(a.id), "name": a.name, "email": a.contact_email, "checks": a.bgv_checks_json or [], "turnaround_days": a.turnaround_days} for a in rows]


def _link(db: Session, token: str) -> str:
    from app.platform.links import public_app_url

    return f"{public_app_url(db)}/bgv-vendor/{token}"


def assignment_dict(db: Session, a: BgvAssignment, *, with_link: bool = False) -> dict:
    ag = db.get(RecruitmentAgency, a.agency_id)
    overdue = bool(a.due_date and a.status in ("assigned", "in_progress") and a.due_date < date.today())
    d = {"id": str(a.id), "application_id": str(a.application_id), "agency_id": str(a.agency_id), "agency": ag.name if ag else None,
         "agency_email": ag.contact_email if ag else None, "checks": a.checks_json or [], "due_date": a.due_date.isoformat() if a.due_date else None,
         "status": a.status, "overdue": overdue, "link_expires_at": a.link_expires_at.isoformat(), "opened_at": a.opened_at.isoformat() if a.opened_at else None,
         "report_name": a.report_name, "report_note": a.report_note, "report_uploaded_at": a.report_uploaded_at.isoformat() if a.report_uploaded_at else None,
         "decision": a.decision, "cost": float(a.cost) if a.cost is not None else None, "created_by": a.created_by,
         "created_at": a.created_at.isoformat() if a.created_at else None, "cancelled_at": a.cancelled_at.isoformat() if a.cancelled_at else None,
         "cancel_reason": a.cancel_reason, "reminders": a.reminders_json or []}
    if with_link and a.status in OPEN:
        d["link"] = _link(db, a.token)
    return d


def current(db: Session, application_id) -> Optional[BgvAssignment]:
    return (db.query(BgvAssignment).filter(BgvAssignment.application_id == application_id, BgvAssignment.status.in_(OPEN))
            .order_by(BgvAssignment.created_at.desc()).first())


def _email(db: Session, tenant, key: str, to: Optional[str], a: BgvAssignment, **ctx) -> Optional[str]:
    from app.platform.comms.defaults import send_default

    if not to:
        return None
    app = db.get(Application, a.application_id)
    name, job = _names(db, app)
    try:
        m = send_default(db, tenant, key, to=[to], purpose="email.outbound.recruitment", related_entity_type="bgv_assignment", related_entity_id=a.id,
                         ctx={"candidate": name, "job_title": job, "link": _link(db, a.token), "due": a.due_date.strftime("%d %b %Y") if a.due_date else "as agreed",
                              "checks": ", ".join(c.replace("_", " ") for c in (a.checks_json or [])) or "as agreed", **ctx})
        return getattr(m, "status", None)
    except Exception as exc:  # noqa: BLE001 -- shown on the card; HR can copy the link
        return f"failed: {exc}"[:200]


def assign(db: Session, tenant, application: Application, *, agency_id, checks: list[str], due_date: Optional[date], actor: str) -> dict:
    if application.status not in ("bgv_requested", "bgv_pending"):
        raise VendorError("Send the background check first (the candidate must be at the BGV step).")
    ag = db.get(RecruitmentAgency, agency_id)
    if ag is None or ag.tenant_id != tenant.tenant_id or not ag.active or ag.agency_type not in ("bgv", "both"):
        raise VendorError("Pick an active BGV vendor (Agencies, type BGV).")
    offered = {c["check"]: c.get("price") for c in (ag.bgv_checks_json or [])}
    checks = [c for c in dict.fromkeys(checks or []) if c]
    if not checks:
        raise VendorError("Choose at least one check.")
    bad = [c for c in checks if c not in offered]
    if bad:
        raise VendorError(f"{ag.name} doesn't offer: {', '.join(bad)}.")
    if due_date is None:
        due_date = date.today() + timedelta(days=int(ag.turnaround_days or 7))
    if due_date < date.today():
        raise VendorError("The due date can't be in the past.")
    old = current(db, application.id)
    if old is not None:  # reassign: the old link stops
        old.status, old.cancelled_at, old.cancel_reason = "cancelled", _now(), f"reassigned to {ag.name}"
        _email(db, tenant, "bgv.vendor_cancelled", (db.get(RecruitmentAgency, old.agency_id) or ag).contact_email, old)
    days = int(_setting(db, tenant, "recruitment.bgv.vendor_link_days") or 14)
    a = BgvAssignment(tenant_id=tenant.tenant_id, application_id=application.id, agency_id=ag.id, checks_json=checks, due_date=due_date,
                      token=secrets.token_urlsafe(32), link_expires_at=_now() + timedelta(days=days), created_by=actor[:200],
                      cost=sum(float(offered[c] or 0) for c in checks), reminders_json=[])
    db.add(a)
    db.commit()
    sent = _email(db, tenant, "bgv.vendor_assigned", ag.contact_email, a, vendor=ag.name, expires=a.link_expires_at.strftime("%d %b %Y"))
    log_action(db, "application", application.id, "bgv_vendor_assigned", actor[:50],
               {"agency": ag.name, "checks": checks, "due": due_date.isoformat(), "reassigned_from": str(old.id) if old else None, "email": sent})
    return {**assignment_dict(db, a, with_link=True), "email": sent}


def cancel(db: Session, tenant, a: BgvAssignment, *, actor: str, reason: Optional[str]) -> dict:
    if a.status not in OPEN:
        raise VendorError("This assignment is already closed.")
    a.status, a.cancelled_at, a.cancel_reason = "cancelled", _now(), (reason or "cancelled by HR").strip()[:300]
    db.commit()
    ag = db.get(RecruitmentAgency, a.agency_id)
    _email(db, tenant, "bgv.vendor_cancelled", ag.contact_email if ag else None, a)
    log_action(db, "application", a.application_id, "bgv_vendor_cancelled", actor[:50], {"agency": ag.name if ag else None, "reason": a.cancel_reason})
    return assignment_dict(db, a)


def on_decision(db: Session, tenant, application: Application, decision: str) -> None:
    a = (db.query(BgvAssignment).filter(BgvAssignment.application_id == application.id, BgvAssignment.status.in_(OPEN))
         .order_by(BgvAssignment.created_at.desc()).first())
    if a is not None and decision in ("passed", "discrepancy", "failed"):
        a.status, a.decision, a.decided_at = "decided", decision, _now()
        db.commit()


# ---- the vendor's link (public) ----


def resolve(db: Session, token: str) -> BgvAssignment:
    a = db.query(BgvAssignment).filter(BgvAssignment.token == token).first()
    if a is None or a.status == "cancelled":
        raise VendorError("This link is no longer active. Please contact the company that sent it.")
    if a.link_expires_at < _now():
        raise VendorError("This link has expired. Please ask the company for a new one.")
    return a


def vendor_view(db: Session, tenant, a: BgvAssignment) -> dict:
    if a.status == "assigned":
        a.status, a.opened_at = "in_progress", _now()
        db.commit()
        log_action(db, "application", a.application_id, "bgv_vendor_opened", "vendor", {})
    app = db.get(Application, a.application_id)
    name, job = _names(db, app)
    ag = db.get(RecruitmentAgency, a.agency_id)
    company = _setting(db, tenant, "org.display_name") or ""
    return {"company": company, "vendor": ag.name if ag else None, "candidate": name, "job_title": job, "checks": a.checks_json or [],
            "due_date": a.due_date.isoformat() if a.due_date else None, "status": a.status, "link_expires_at": a.link_expires_at.isoformat(),
            "documents": [{"id": d["id"], "label": d["label"], "type": d["type"], "available": d["path"].exists()} for d in documents(db, app)],
            "report": {"name": a.report_name, "uploaded_at": a.report_uploaded_at.isoformat() if a.report_uploaded_at else None} if a.report_name else None,
            "can_upload": a.status in ("assigned", "in_progress", "report_received")}


def vendor_file(db: Session, a: BgvAssignment, doc_id: str) -> tuple[Path, str]:
    app = db.get(Application, a.application_id)
    name, _job = _names(db, app)
    for d in documents(db, app):
        if d["id"] == doc_id and d["path"].exists():
            log_action(db, "application", a.application_id, "bgv_vendor_downloaded", "vendor", {"document": d["label"]})
            return d["path"], f"{_safe(name)} - {_safe(d['label'])}.{d['ext']}"
    raise VendorError("That document isn't available.")


def upload_report(db: Session, tenant, a: BgvAssignment, data: bytes, filename: str, note: Optional[str]) -> dict:
    from app.models.comms import OutboundMessage

    if a.status not in ("assigned", "in_progress", "report_received"):
        raise VendorError("This check is already decided - the report can't be changed.")
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext not in ("pdf", "doc", "docx", "zip", "png", "jpg", "jpeg", "xlsx"):
        raise VendorError("Please upload the report as PDF, Word, Excel, ZIP or an image.")
    if len(data) > 20 * 1024 * 1024:
        raise VendorError("The report is larger than 20 MB.")
    folder = REPORT_DIR / str(tenant.tenant_id)
    folder.mkdir(parents=True, exist_ok=True)
    stored = f"{tenant.tenant_id}/{uuid.uuid4()}.{ext}"
    (REPORT_DIR / stored).write_bytes(data)
    a.report_path, a.report_name, a.report_note = stored, filename[:200], (note or "").strip()[:2000] or None
    a.report_uploaded_at, a.status = _now(), "report_received"
    db.commit()
    app = db.get(Application, a.application_id)
    name, job = _names(db, app)
    ag = db.get(RecruitmentAgency, a.agency_id)
    from app.recruitment.automation import _admins

    for addr in _admins(db, tenant)[:5]:
        db.add(OutboundMessage(tenant_id=tenant.tenant_id, channel="in_app", purpose="recruitment.bgv", to_addresses=[addr], status="sent",
                               subject=f"BGV report received for {name} ({job}) from {ag.name if ag else 'the vendor'} - decide now",
                               body_ref=f"/bgv?application={app.id}", related_entity_type="application", related_entity_id=app.id))
    db.commit()
    log_action(db, "application", a.application_id, "bgv_vendor_report_received", "vendor", {"agency": ag.name if ag else None, "file": a.report_name})
    return {"ok": True}


def report_file(a: BgvAssignment) -> Optional[Path]:
    if not a.report_path:
        return None
    p = REPORT_DIR / a.report_path
    return p if p.exists() else None


# ---- reminders ----


def run_reminders(db: Session, tenant) -> dict:
    """Daily: the day before the due date, then every 2 days after it (at most 3 after)."""
    sent = 0
    today = date.today()
    for a in db.query(BgvAssignment).filter(BgvAssignment.tenant_id == tenant.tenant_id, BgvAssignment.status.in_(("assigned", "in_progress")),
                                            BgvAssignment.due_date.isnot(None)).all():
        log = list(a.reminders_json or [])
        last = date.fromisoformat(log[-1]["on"]) if log else None
        before = a.due_date - timedelta(days=1)
        after = [x for x in log if x.get("kind") == "overdue"]
        kind = None
        if today == before and not any(x.get("kind") == "before" for x in log):
            kind = "before"
        elif today > a.due_date and len(after) < 3 and (last is None or (today - last).days >= 2):
            kind = "overdue"
        if kind is None:
            continue
        ag = db.get(RecruitmentAgency, a.agency_id)
        status = _email(db, tenant, "bgv.vendor_reminder", ag.contact_email if ag else None, a,
                        when="tomorrow" if kind == "before" else f"was due on {a.due_date.strftime('%d %b %Y')}")
        a.reminders_json = [*log, {"on": today.isoformat(), "kind": kind, "email": status}]
        sent += 1
    db.commit()
    return {"reminders": sent}
