"""Policies & handbook (fix 2026-10-05): the one place HR uploads the documents the HR
assistant answers from -- Settings > Company > Policies & handbook. It works whether or not
Helpdesk is switched on (the assistant's knowledge is not a Helpdesk feature).

A file is kept in the company's folder of the storage connection (`storage.documents`; the
server's own disk when none is connected), then read in the background:
processing -> active ("Ready for HR assistant") or failed (+ a plain reason). A new version
of a document becomes the one the assistant uses only once it is Ready -- until then the
old version keeps answering. Deleting removes the file and the searchable text; the row
stays (status "deleted") so answers that cited it still show where they came from.
"""

import io
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.models.intelligence import KnowledgeChunk, KnowledgeDocument
from app.platform.tenancy.context import TenantContext

CATEGORIES = ("leave", "conduct", "benefits", "it", "other")
TYPES = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
MAX_BYTES = 20 * 1024 * 1024
MIN_LETTERS = 80  # less than this = no readable text (a scanned PDF)
POLICY_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "policies"
STORAGE_PREFIX = "storage:"
LIVE = ("processing", "active", "failed")  # shown in the list; retired/deleted are history


class PolicyError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def to_dict(d: KnowledgeDocument, *, older: Optional[list] = None) -> dict:
    status = {"active": "ready"}.get(d.status, d.status)
    return {
        "id": str(d.id), "title": d.title, "category": d.category or "other", "version": d.version, "status": status,
        "effective_date": d.effective_date.isoformat() if d.effective_date else None, "error": d.error,
        "file_name": d.file_name, "content_type": d.content_type, "size_bytes": d.size_bytes, "has_file": bool(d.file_path),
        "source": d.source, "uploaded_by": d.uploaded_by, "created_at": d.created_at.isoformat() if d.created_at else None,
        "processed_at": d.processed_at.isoformat() if d.processed_at else None, "replaces_id": str(d.replaces_id) if d.replaces_id else None,
        "older_versions": older or [],
    }


def listing(db: Session, tenant: TenantContext) -> list[dict]:
    """Uploaded policies, newest first. A version waiting to replace an older Ready one is
    listed on its own row (so HR sees "Processing" / "Failed"); replaced versions are listed
    under the current one as history."""
    rows = (db.query(KnowledgeDocument).filter(KnowledgeDocument.tenant_id == tenant.tenant_id, KnowledgeDocument.source == "upload")
            .order_by(KnowledgeDocument.created_at.desc()).all())
    by_id = {r.id: r for r in rows}
    out = []
    for row in rows:
        if row.status not in LIVE:
            continue
        older, prev = [], by_id.get(row.replaces_id) if row.status == "active" else None
        while prev is not None and prev.status == "retired":
            older.append({"id": str(prev.id), "version": prev.version, "effective_date": prev.effective_date.isoformat() if prev.effective_date else None,
                          "file_name": prev.file_name, "has_file": bool(prev.file_path), "created_at": prev.created_at.isoformat() if prev.created_at else None})
            prev = by_id.get(prev.replaces_id)
        out.append(to_dict(row, older=older))
    return out


def ready_count(db: Session, tenant: TenantContext) -> int:
    return db.query(KnowledgeDocument).filter(KnowledgeDocument.tenant_id == tenant.tenant_id, KnowledgeDocument.status == "active").count()


# ---- files ----


def _storage():
    from app.experience.media_router import _storage as media_storage

    return media_storage()


def _store(tenant: TenantContext, data: bytes, ext: str) -> str:
    key = f"policies/{tenant.tenant_id}/{uuid.uuid4()}.{ext}"
    storage = _storage()
    if storage is not None:
        result = storage.put(key, data, TYPES[ext])
        if getattr(result, "success", False):
            return STORAGE_PREFIX + key
    target = POLICY_DIR.parent / key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return key


def read_file(path: str) -> bytes:
    if path.startswith(STORAGE_PREFIX):
        storage = _storage()
        if storage is None:
            raise PolicyError("The storage connection that holds this file isn't available.")
        return storage.get(path[len(STORAGE_PREFIX):])
    return (POLICY_DIR.parent / path).read_bytes()


def _remove_file(path: Optional[str]) -> None:
    if not path:
        return
    try:
        if path.startswith(STORAGE_PREFIX):
            storage = _storage()
            if storage is not None:
                storage.delete(path[len(STORAGE_PREFIX):])
        else:
            (POLICY_DIR.parent / path).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001 -- a file that can't be removed must not block the delete
        pass


def _ext(filename: str) -> str:
    return filename.lower().rsplit(".", 1)[-1] if filename and "." in filename else ""


# ---- upload / replace / delete ----


def upload(db: Session, tenant: TenantContext, *, data: bytes, filename: str, title: str, category: str, version: Optional[str],
           effective_date: Optional[date], actor: str, replaces: Optional[KnowledgeDocument] = None) -> KnowledgeDocument:
    ext = _ext(filename)
    if ext not in TYPES:
        raise PolicyError("Please upload a PDF or Word (.docx) file.")
    if not data:
        raise PolicyError("That file is empty.")
    if len(data) > MAX_BYTES:
        raise PolicyError("That file is larger than 20 MB. Please split it or upload a smaller copy.")
    title = (title or "").strip() or Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    if category not in CATEGORIES:
        category = "other"
    document = KnowledgeDocument(
        tenant_id=tenant.tenant_id, title=title[:300], source="upload", status="processing", uploaded_by=actor,
        category=category, version=(version or "").strip()[:30] or None, effective_date=effective_date,
        file_path=_store(tenant, data, ext), file_name=Path(filename).name[:200], content_type=TYPES[ext], size_bytes=len(data),
        replaces_id=replaces.id if replaces is not None else None, updated_at=_now(),
        language=replaces.language if replaces is not None else "en",
        audience_role_names=list(replaces.audience_role_names or []) if replaces is not None else [],
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    _audit(db, tenant, "policy.uploaded" if replaces is None else "policy.new_version", document, actor,
           {"title": document.title, "version": document.version, "file": document.file_name})
    return document


def update_details(db: Session, tenant: TenantContext, document: KnowledgeDocument, *, title: Optional[str], category: Optional[str],
                   version: Optional[str], effective_date: Optional[date], actor: str) -> KnowledgeDocument:
    if title is not None and title.strip():
        document.title = title.strip()[:300]
    if category is not None:
        document.category = category if category in CATEGORIES else "other"
    if version is not None:
        document.version = version.strip()[:30] or None
    document.effective_date = effective_date if effective_date is not None else document.effective_date
    document.updated_at = _now()
    db.commit()
    _audit(db, tenant, "policy.details_changed", document, actor, {"title": document.title, "version": document.version})
    return document


def delete(db: Session, tenant: TenantContext, document: KnowledgeDocument, *, actor: str) -> None:
    """The file and its searchable text go; the row stays as "deleted" so earlier answers that
    cited it still name their source. Older versions of it go the same way."""
    chain, seen = [document], {document.id}
    prev = db.get(KnowledgeDocument, document.replaces_id) if document.replaces_id else None
    while prev is not None and prev.id not in seen and prev.status == "retired":
        chain.append(prev)
        seen.add(prev.id)
        prev = db.get(KnowledgeDocument, prev.replaces_id) if prev.replaces_id else None
    for row in chain:
        db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == row.id).delete(synchronize_session=False)
        _remove_file(row.file_path)
        row.file_path, row.status, row.updated_at = None, "deleted", _now()
    db.commit()
    _audit(db, tenant, "policy.deleted", document, actor, {"title": document.title, "versions": len(chain)})


# ---- processing ----


def process(db: Session, tenant: TenantContext, document_id) -> Optional[KnowledgeDocument]:
    """Reads the file into searchable passages. Ready -> the assistant uses it (and the
    version it replaces is retired); otherwise Failed with a reason HR can act on."""
    document = db.get(KnowledgeDocument, document_id)
    if document is None or document.status != "processing":
        return document
    try:
        text_value = extract(read_file(document.file_path), document.file_name or "")
        if sum(ch.isalpha() for ch in text_value) < MIN_LETTERS:
            raise PolicyError("No readable text was found. It may be a scanned copy - please upload the original PDF or Word file.")
        from app.copilot.retrieval import write_chunks

        count = write_chunks(db, tenant, document, text_value)
        document.status, document.error = "active", None
        if document.replaces_id:
            old = db.get(KnowledgeDocument, document.replaces_id)
            if old is not None and old.status in ("active", "failed", "processing"):
                old.status = "retired"
                db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == old.id).delete(synchronize_session=False)
        detail = {"passages": count}
    except PolicyError as exc:
        document.status, document.error, detail = "failed", str(exc), {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001 -- a broken file is a Failed row, never a crash
        document.status = "failed"
        document.error = "This file couldn't be opened. It may be damaged or password-protected - please save it again and re-upload."
        detail = {"error": str(exc)[:300]}
    document.processed_at = document.updated_at = _now()
    db.commit()
    _audit(db, tenant, "policy.ready" if document.status == "active" else "policy.failed", document, "system", detail)
    return document


def process_later(tenant: TenantContext, document_id) -> None:
    """Background task after the upload response: its own session + tenant."""
    from app.core.database import SessionLocal
    from app.platform.tenancy.context import reset_current_tenant, set_current_tenant

    token = set_current_tenant(tenant)
    db = SessionLocal()
    try:
        process(db, tenant, document_id)
    finally:
        db.close()
        reset_current_tenant(token)


def resume_stuck(db: Session, tenant: TenantContext) -> int:
    """Rows left in Processing by a restart are processed again (called by the list endpoint)."""
    from datetime import timedelta

    stale = _now() - timedelta(minutes=2)
    rows = db.query(KnowledgeDocument).filter(KnowledgeDocument.tenant_id == tenant.tenant_id, KnowledgeDocument.status == "processing",
                                              KnowledgeDocument.updated_at < stale).all()
    for row in rows:
        process(db, tenant, row.id)
    return len(rows)


_HEADING_NUM = re.compile(r"^(\d+(\.\d+)*\.?|[A-Z]\.)\s+\S")


def extract(data: bytes, filename: str) -> str:
    """Plain text with "# " headings and blank lines between paragraphs, the shape
    retrieval.chunk_text() splits into cited passages."""
    ext = _ext(filename)
    if ext == "docx":
        from docx import Document

        doc = Document(io.BytesIO(data))
        parts = []
        for p in doc.paragraphs:
            text_value = p.text.strip()
            if not text_value:
                continue
            style = (p.style.name if p.style is not None else "") or ""
            parts.append(f"# {text_value}" if style.lower().startswith(("heading", "title")) else text_value)
        for table in doc.tables:
            parts.append("\n".join(" | ".join(c.text.strip() for c in row.cells) for row in table.rows))
        return "\n\n".join(parts)
    if ext == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise PolicyError("This PDF is password-protected. Please upload a copy without a password.")
        lines = [ln.strip() for page in reader.pages for ln in (page.extract_text() or "").splitlines()]
        out, para = [], []

        def _flush():
            if para:
                out.append(" ".join(para))
                para.clear()

        for ln in lines:
            if not ln:
                _flush()
                continue
            short = len(ln) < 70 and not ln.endswith((".", ",", ";", ":"))
            if short and (_HEADING_NUM.match(ln) or ln.istitle() or ln.isupper()):
                _flush()
                out.append(f"# {ln}")
                continue
            para.append(ln)
            if sum(len(x) for x in para) > 600:
                _flush()
        _flush()
        return "\n\n".join(out)
    raise PolicyError("Please upload a PDF or Word (.docx) file.")


# ---- sample ----


SAMPLE_SECTIONS = (
    ("Leave policy", [
        "Every employee gets 18 days of annual leave in each calendar year, credited at 1.5 days per month.",
        "Up to 6 unused annual leave days can be carried forward to the next year. Days above that lapse on 31 December.",
        "Sick leave: 8 days a year. A doctor's note is needed for more than 2 sick days in a row.",
        "Apply for leave in the HR app at least 3 working days in advance; your manager approves it.",
    ]),
    ("Code of conduct", [
        "Treat colleagues, candidates and customers with respect. Harassment of any kind is not tolerated.",
        "Report a concern to your manager or to hr@yourcompany.com. Reports can be made anonymously.",
        "Gifts worth more than Rs 2,000 from vendors or customers must be declared to HR.",
    ]),
    ("Benefits", [
        "Group health insurance covers you, your spouse and two children up to Rs 5,00,000 a year from your first day.",
        "Learning budget: Rs 20,000 a year for courses, books and certifications related to your role.",
    ]),
    ("Work from home", [
        "You can work from home up to 2 days a week with your manager's agreement.",
        "Core hours are 11:00 to 16:00, when everyone should be reachable.",
    ]),
    ("IT and devices", [
        "Company laptops must have disk encryption on and must be locked when you step away.",
        "Report a lost or stolen device to IT within 24 hours.",
    ]),
)


def sample_docx() -> bytes:
    from docx import Document

    doc = Document()
    doc.add_heading("Employee handbook (sample)", level=0)
    doc.add_paragraph("A sample handbook to show the format. Replace the wording with your own policies, save, and upload it.")
    for heading, paras in SAMPLE_SECTIONS:
        doc.add_heading(heading, level=1)
        for p in paras:
            doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _audit(db: Session, tenant: TenantContext, action: str, document: KnowledgeDocument, actor: str, detail: dict) -> None:
    from app.audit.service import log_action

    log_action(db, "policy_document", document.id, action, (actor or "system")[:50], detail)
    db.commit()
