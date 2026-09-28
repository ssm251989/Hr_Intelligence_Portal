"""Part 17.15: removing candidates.

Step 1 "Remove" -> Recycle bin (soft delete): `candidates.deleted_at` + `applications.removed_at`
are set; a global read filter (install_removed_filter) hides them from every list, search,
report, score and email; live interview offers / form links / queued emails for them are
cancelled. Restorable for `recruitment.candidates.recycle_days` (30).

Step 2 "Delete permanently" (from the bin, when the days run out, or straight away for a
privacy request): the candidate, their applications and every row that belongs to them
(found through the database's own foreign keys), their audit trail (AI results, scores,
notes), their files (resume, photo, BGV documents), and their personal data in the message
log (kept as "removed candidate") are removed. One audit entry is kept: who, when, why, counts
-- no personal data.

Blocked (plain explanation) when an offer was signed or the person is already an employee.
"""

import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import event, false, or_, select
from sqlalchemy.orm import Session, with_loader_criteria

from app.audit.service import log_action
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate

REASONS = ("duplicate", "test_data", "privacy_request", "withdrawn", "other")
INCLUDE_REMOVED = "include_removed"  # execution option: see the recycle bin itself
MAX_BULK = 500


class RemovalBlocked(ValueError):
    pass


# ---------------------------------------------------------------- the global "hide removed" filter

def _hide_removed(execute_state) -> None:
    if not execute_state.is_select or execute_state.execution_options.get(INCLUDE_REMOVED):
        return
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(Candidate, lambda cls: cls.deleted_at.is_(None), include_aliases=True),
        with_loader_criteria(Application, lambda cls: cls.removed_at.is_(None), include_aliases=True),
    )


_installed = False


def install_removed_filter() -> None:
    global _installed
    if not _installed:
        event.listen(Session, "do_orm_execute", _hide_removed)
        _installed = True


def _q(db: Session, model):
    return db.query(model).execution_options(**{INCLUDE_REMOVED: True})


def _setting(db: Session, tenant, key: str):
    from app.platform.settings.resolver import SettingContext, SettingsService

    return SettingsService(db).get(key, SettingContext(tenant=tenant))


# ---------------------------------------------------------------- checks + summary

def _blocking(db: Session, tenant, candidate: Candidate, app_ids: list) -> Optional[str]:
    from app.models.offer import Offer
    from app.models.onboarding import PreboardingCase

    if app_ids and _q(db, Offer).filter(Offer.application_id.in_(app_ids), Offer.signed.is_(True)).first() is not None:
        return "This candidate has signed an offer, so their records can't be removed. If they are not joining, use the offer/exit process instead."
    if _q(db, PreboardingCase).filter(or_(PreboardingCase.candidate_id == candidate.id, PreboardingCase.application_id.in_(app_ids or [None])),
                                      PreboardingCase.employee_id.isnot(None)).first() is not None:
        return "This person is already set up as an employee (or joiner). Use the exit process instead of removing them."
    if app_ids and _q(db, Application).filter(Application.id.in_(app_ids), Application.status.in_(("onboarding_started", "onboarding_completed"))).first():
        return "This candidate has started onboarding. Use the exit process instead of removing them."
    return None


def _app_ids(db: Session, candidate_id) -> list:
    return [a for (a,) in db.query(Application.id).execution_options(**{INCLUDE_REMOVED: True}).filter(Application.candidate_id == candidate_id)]


def _dependents(db: Session, table_name: str, ids: list, seen: set, depth: int = 0) -> list[tuple]:
    """[(table, pk_column, [ids])] of every row that points (by a foreign key) at `ids` in
    `table_name`, deepest first -- the delete order. Stops at 6 levels."""
    from app.core.database import Base

    out: list[tuple] = []
    if not ids or depth > 6:
        return out
    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_keys:
            if fk.column.table.name != table_name or table.name in ("audit_log",):
                continue
            key = (table.name, fk.parent.name)
            if key in seen:
                continue
            pk_cols = list(table.primary_key.columns)
            if len(pk_cols) != 1:
                continue
            pk = pk_cols[0]
            if table.name == table_name and fk.parent.name == "duplicate_of_id":
                continue  # other people's "possible duplicate of" link -> cleared by ON DELETE SET NULL
            rows = [r[0] for r in db.execute(select(pk).where(fk.parent.in_(ids))).all()]
            if not rows:
                continue
            seen.add(key)
            out += _dependents(db, table.name, rows, seen, depth + 1)
            out.append((table, pk, rows))
    return out


def summary(db: Session, tenant, candidate: Candidate) -> dict:
    """What a permanent delete would remove, in plain counts (shown before confirming)."""
    from app.models.bgv_document import BgvDocument
    from app.models.interview import Interview

    app_ids = _app_ids(db, candidate.id)
    deps = _dependents(db, "candidates", [candidate.id], set())  # applications and everything under them
    counts: dict[str, int] = {}
    for table, _pk, rows in deps:
        counts[table.name] = counts.get(table.name, 0) + len(rows)
    files = sum(1 for p in (candidate.resume_path, candidate.photo_path) if p)
    files += db.query(BgvDocument).execution_options(**{INCLUDE_REMOVED: True}).filter(BgvDocument.application_id.in_(app_ids or [None]), BgvDocument.file_path.isnot(None)).count()
    interviews = db.query(Interview).execution_options(**{INCLUDE_REMOVED: True}).filter(Interview.application_id.in_(app_ids or [None])).count()
    return {"candidates": 1, "applications": len(app_ids), "interviews": interviews, "files": files, "related_rows": counts,
            "blocked": _blocking(db, tenant, candidate, app_ids)}


# ---------------------------------------------------------------- step 1: recycle bin

def _cancel_pending(db: Session, tenant, candidate: Candidate, app_ids: list) -> dict:
    from app.models.comms import OutboundMessage
    from app.models.iam import ActionToken
    from app.models.interview_confirmation_token import InterviewConfirmationToken
    from app.models.negotiation_token import NegotiationToken

    now = datetime.now(timezone.utc)
    done = {"negotiation_links": 0, "confirmation_links": 0, "form_links": 0, "queued_emails": 0}
    if app_ids:
        for t in db.query(NegotiationToken).filter(NegotiationToken.application_id.in_(app_ids), NegotiationToken.invalidated_at.is_(None)):
            if getattr(t, "used_at", None) is None:
                t.invalidated_at = now
                done["negotiation_links"] += 1
        for t in db.query(InterviewConfirmationToken).filter(InterviewConfirmationToken.application_id.in_(app_ids),
                                                             InterviewConfirmationToken.used_at.is_(None), InterviewConfirmationToken.invalidated_at.is_(None)):
            t.invalidated_at = now
            done["confirmation_links"] += 1
        for t in db.query(ActionToken).filter(ActionToken.tenant_id == tenant.tenant_id, ActionToken.entity_type == "application",
                                              ActionToken.entity_id.in_(app_ids), ActionToken.invalidated_at.is_(None)):
            t.invalidated_at = now
            done["form_links"] += 1
    if candidate.email:
        for m in db.query(OutboundMessage).filter(OutboundMessage.tenant_id == tenant.tenant_id, OutboundMessage.status == "queued",
                                                  OutboundMessage.to_addresses.overlap([candidate.email])):
            m.status, m.error = "suppressed", "candidate removed"
            done["queued_emails"] += 1
    return done


def remove(db: Session, tenant, candidate: Candidate, *, reason: str, note: Optional[str], actor: str) -> dict:
    if reason not in REASONS:
        raise ValueError(f"reason must be one of {', '.join(REASONS)}")
    app_ids = _app_ids(db, candidate.id)
    blocked = _blocking(db, tenant, candidate, app_ids)
    if blocked:
        raise RemovalBlocked(blocked)
    now = datetime.now(timezone.utc)
    cancelled = _cancel_pending(db, tenant, candidate, app_ids)
    from app.recruitment import budgets  # Part 18.15: a removed candidate frees their budget

    for aid in app_ids:
        budgets.release(db, tenant, aid)
    candidate.deleted_at, candidate.deleted_by, candidate.delete_reason, candidate.delete_note = now, actor[:200], reason, (note or None)
    for a in _q(db, Application).filter(Application.id.in_(app_ids or [None])):
        a.removed_at = now
    db.commit()
    log_action(db, "candidate", candidate.id, "candidate_removed", actor[:50], {"reason": reason, "applications": len(app_ids), "cancelled": cancelled})
    days = int(_setting(db, tenant, "recruitment.candidates.recycle_days") or 30)
    return {"removed": True, "restore_until": (now + timedelta(days=days)).isoformat(), "cancelled": cancelled}


def restore(db: Session, tenant, candidate: Candidate, *, actor: str) -> dict:
    if candidate.deleted_at is None:
        return {"restored": False, "reason": "not in the recycle bin"}
    candidate.deleted_at = candidate.deleted_by = candidate.delete_reason = candidate.delete_note = None
    n = 0
    for a in _q(db, Application).filter(Application.candidate_id == candidate.id, Application.removed_at.isnot(None)):
        a.removed_at = None
        n += 1
    db.commit()
    log_action(db, "candidate", candidate.id, "candidate_restored", actor[:50], {"applications": n})
    return {"restored": True, "applications": n}


# ---------------------------------------------------------------- step 2: permanent delete

def _remove_files(db: Session, candidate: Candidate, app_ids: list) -> int:
    from app.bgv.storage import UPLOAD_DIR as BGV_DIR
    from app.candidates.storage import PHOTO_UPLOAD_DIR, UPLOAD_DIR
    from app.models.bgv_document import BgvDocument

    paths = []
    if candidate.resume_path:
        paths.append(Path(UPLOAD_DIR) / candidate.resume_path)
    if candidate.photo_path:
        paths.append(Path(PHOTO_UPLOAD_DIR) / candidate.photo_path)
    for rel in (candidate.custom_fields or {}).get("payslips", []):  # Part 18.12 salary form payslips
        paths.append(Path(UPLOAD_DIR).parent / "salary-payslips" / rel)
    for (fp,) in db.query(BgvDocument.file_path).execution_options(**{INCLUDE_REMOVED: True}).filter(BgvDocument.application_id.in_(app_ids or [None])):
        if fp:
            paths.append(Path(BGV_DIR) / fp)
    removed = 0
    for p in paths:
        try:
            if p.is_file():
                p.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def delete_permanently(db: Session, tenant, candidate: Candidate, *, reason: str, actor: str, confirm: str) -> dict:
    from app.models.comms import OutboundMessage

    if confirm != "DELETE":
        raise ValueError("Type DELETE to confirm.")
    if reason not in REASONS:
        raise ValueError(f"reason must be one of {', '.join(REASONS)}")
    app_ids = _app_ids(db, candidate.id)
    blocked = _blocking(db, tenant, candidate, app_ids)
    if blocked:
        raise RemovalBlocked(blocked)
    counts = summary(db, tenant, candidate)
    protected = {"employees", "users"} & set(counts["related_rows"])
    if protected:
        raise RemovalBlocked("This candidate is linked to an employee or user account, so they can't be deleted permanently. Use the exit process instead.")
    ref = f"removed-{secrets.token_hex(4)}"  # a reference with no personal data in it
    email = (candidate.email or "").lower()
    files = _remove_files(db, candidate, app_ids)
    # message log: keep the fact a message was sent, drop who it was to and what it said
    scrubbed = 0
    msgs = db.query(OutboundMessage).filter(OutboundMessage.tenant_id == tenant.tenant_id,
                                            or_(OutboundMessage.related_entity_id.in_(app_ids + [candidate.id]),
                                                OutboundMessage.to_addresses.overlap([email]) if email else false()))
    for m in msgs:
        m.to_addresses = ["removed candidate"]
        m.subject = "Message to a removed candidate"
        m.body_ref = None
        m.related_entity_id = None
        scrubbed += 1
    if email:
        from app.models.comms import InboundMessage

        for m in db.query(InboundMessage).filter(InboundMessage.tenant_id == tenant.tenant_id, InboundMessage.from_address.ilike(f"%{email}%")):
            m.from_address, m.subject, m.body_ref, m.attachments_json = "removed candidate", "Message from a removed candidate", None, None
            scrubbed += 1
    # audit trail of this person (AI results, scores, notes, timeline)
    entity_ids = [candidate.id] + app_ids
    deps = _dependents(db, "candidates", [candidate.id], set())  # applications and everything under them
    entity_ids += [i for (_t, _pk, rows) in deps for i in rows]
    audit_removed = db.query(AuditLog).filter(AuditLog.tenant_id == tenant.tenant_id, AuditLog.entity_id.in_(entity_ids)).delete(synchronize_session=False)
    # privacy ledger rows about this subject (the erasure itself is recorded in the DPR ledger)
    from app.models.privacy import ConsentRecord

    db.query(ConsentRecord).filter(ConsentRecord.tenant_id == tenant.tenant_id, ConsentRecord.subject_id == candidate.id).delete(synchronize_session=False)
    for table, pk, rows in deps:
        db.execute(table.delete().where(pk.in_(rows)))
    db.execute(Application.__table__.delete().where(Application.id.in_(app_ids or [None])))
    db.execute(Candidate.__table__.delete().where(Candidate.id == candidate.id))
    db.commit()
    record = {"reason": reason, "reference": ref, "applications": len(app_ids), "interviews": counts["interviews"], "files": files,
              "related_rows": counts["related_rows"], "audit_entries_removed": audit_removed, "messages_scrubbed": scrubbed}
    if reason == "privacy_request":
        record["privacy_request_id"] = _record_erasure(db, tenant, email, record, actor)
    log_action(db, "candidate_removal", None, "candidate_deleted", actor[:50], record)
    return record


def _record_erasure(db: Session, tenant, email: str, record: dict, actor: str) -> str:
    """DPDP erasure: a completed request in the privacy ledger. The email is kept only as a
    one-way hash, so a repeat request can be matched without keeping the person's data."""
    import hashlib

    from app.models.privacy import DataPrincipalRequest

    now = datetime.now(timezone.utc)
    row = DataPrincipalRequest(tenant_id=tenant.tenant_id, request_type="erasure", subject_type="candidate",
                               subject_email="sha256:" + hashlib.sha256(email.encode()).hexdigest() if email else "unknown",
                               details="Candidate asked to delete their data", status="completed", due_at=now,
                               identity_verified_at=now, assigned_to=actor[:200], resolution="Erased (candidate removal)",
                               outcome_json={k: record[k] for k in ("applications", "interviews", "files", "messages_scrubbed", "reference")}, closed_at=now)
    db.add(row)
    db.commit()
    return str(row.id)


# ---------------------------------------------------------------- bulk (background, with progress)

def start_bulk(db: Session, tenant, ids: list, *, mode: str, reason: str, note: Optional[str], actor: str):
    from app.models.candidate_removal import CandidateRemovalRun

    if mode not in ("remove", "delete"):
        raise ValueError("mode must be remove or delete")
    if reason not in REASONS:
        raise ValueError(f"reason must be one of {', '.join(REASONS)}")
    ids = list(dict.fromkeys(str(i) for i in ids))
    if not ids:
        raise ValueError("Select at least one candidate.")
    if len(ids) > MAX_BULK:
        raise ValueError(f"You can remove up to {MAX_BULK} candidates at a time.")
    run = CandidateRemovalRun(tenant_id=tenant.tenant_id, mode=mode, reason=reason, note=note, candidate_ids=ids, total=len(ids), started_by=actor[:200])
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def run_bulk(tenant_id, slug: str, isolation: str, run_id) -> None:
    """Runs in the background (own session). Progress is saved every 10 candidates."""
    from app.models.candidate_removal import CandidateRemovalRun
    from app.platform.tenancy.context import TenantContext, tenant_context
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
    from app.platform.tenancy.models_cp import Tenant
    from app.platform.tenancy.provisioning import tenant_session

    cp = ControlPlaneSessionLocal()
    try:
        tenant_row = cp.get(Tenant, tenant_id)
    finally:
        cp.close()
    tenant = TenantContext(tenant_id=tenant_id, slug=slug, isolation=isolation)
    with tenant_context(tenant_id, slug, isolation):
        db = tenant_session(tenant_row)
        try:
            run = db.get(CandidateRemovalRun, run_id)
            skipped = []
            try:
                for n, cid in enumerate(run.candidate_ids, 1):
                    cand = _q(db, Candidate).filter(Candidate.tenant_id == tenant.tenant_id, Candidate.id == cid).first()
                    try:
                        if cand is None:
                            skipped.append({"candidate_id": cid, "why": "not found"})
                        elif run.mode == "remove" and cand.deleted_at is not None:
                            skipped.append({"candidate_id": cid, "why": "already in the recycle bin"})
                        elif run.mode == "remove":
                            remove(db, tenant, cand, reason=run.reason, note=run.note, actor=run.started_by or "bulk")
                        else:
                            delete_permanently(db, tenant, cand, reason=run.reason, actor=run.started_by or "bulk", confirm="DELETE")
                    except (RemovalBlocked, ValueError) as exc:
                        db.rollback()
                        skipped.append({"candidate_id": cid, "why": str(exc)})
                    if n % 10 == 0 or n == run.total:
                        run.done, run.skipped = n, list(skipped)
                        db.commit()
                run.status = "finished"
            except Exception as exc:  # noqa: BLE001 -- keep the run row honest
                db.rollback()
                run = db.get(CandidateRemovalRun, run_id)
                run.status, run.skipped = "failed", skipped + [{"candidate_id": None, "why": str(exc)[:300]}]
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
        finally:
            db.close()


def recycle_bin(db: Session, tenant) -> dict:
    days = int(_setting(db, tenant, "recruitment.candidates.recycle_days") or 30)
    rows = _q(db, Candidate).filter(Candidate.tenant_id == tenant.tenant_id, Candidate.deleted_at.isnot(None)).order_by(Candidate.deleted_at.desc()).limit(1000).all()
    ids = [c.id for c in rows]
    apps: dict = {}
    for cid, jid in db.query(Application.candidate_id, Application.job_role_id).execution_options(**{INCLUDE_REMOVED: True}).filter(Application.candidate_id.in_(ids or [None])):
        apps.setdefault(cid, []).append(jid)
    from app.models.job_role import JobRole

    titles = {j.id: j.title for j in db.query(JobRole).filter(JobRole.tenant_id == tenant.tenant_id)}
    return {"recycle_days": days, "items": [{
        "candidate_id": str(c.id), "name": c.full_name, "email": c.email, "reason": c.delete_reason, "note": c.delete_note,
        "removed_by": c.deleted_by, "removed_at": c.deleted_at.isoformat(),
        "deleted_permanently_on": (c.deleted_at + timedelta(days=days)).date().isoformat(),
        "jobs": [titles.get(j) for j in apps.get(c.id, []) if j in titles],
    } for c in rows]}


def purge_expired(db: Session, tenant) -> dict:
    """Daily: permanently delete what has been in the bin longer than the setting allows."""
    days = int(_setting(db, tenant, "recruitment.candidates.recycle_days") or 30)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    done, blocked = 0, 0
    for cand in _q(db, Candidate).filter(Candidate.tenant_id == tenant.tenant_id, Candidate.deleted_at.isnot(None), Candidate.deleted_at < cutoff).limit(200).all():
        try:
            delete_permanently(db, tenant, cand, reason=cand.delete_reason or "other", actor="system (recycle bin time limit)", confirm="DELETE")
            done += 1
        except RemovalBlocked:
            blocked += 1
    return {"deleted": done, "blocked": blocked}
