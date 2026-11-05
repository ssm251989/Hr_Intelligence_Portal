"""Part 17.15 API: removing candidates (Recycle bin, restore, delete permanently).

- GET  /api/v1/ui/candidates/recycle-bin                what is in the bin (+ the day each is deleted for good)
- GET  /api/v1/ui/candidates/{id}/delete-summary        counts shown before confirming ("1 candidate, 2 applications ...")
- POST /api/v1/ui/candidates/{id}/remove                {reason, note} -> Recycle bin (privacy_request: needs confirm=DELETE, deletes at once)
- POST /api/v1/ui/candidates/{id}/restore               back from the bin
- POST /api/v1/ui/candidates/{id}/delete-permanently    {reason, confirm: "DELETE"}
- POST /api/v1/ui/candidates/bulk-remove                {candidate_ids (<=500), mode: remove|delete, reason, note, confirm} -> background run
- GET  /api/v1/ui/candidates/removal-runs/{id}          progress of a bulk run
All need `recruitment.candidate.delete` (HR Admin by default; Settings > Roles to change).
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.user import User
from app.platform.iam.authz import has_permission
from app.platform.tenancy.context import require_current_tenant
from app.recruitment import removal

router = APIRouter(prefix="/api/v1/ui/candidates", tags=["ui-candidate-removal"])
PERMISSION = "recruitment.candidate.delete"


class RemoveBody(BaseModel):
    reason: str
    note: Optional[str] = Field(default=None, max_length=1000)
    confirm: Optional[str] = None


class BulkBody(RemoveBody):
    candidate_ids: list[UUID]
    mode: str = "remove"


def _allowed(db, user):
    tenant = require_current_tenant()
    if not has_permission(db, tenant, user, PERMISSION):
        raise HTTPException(status_code=403, detail=f"Missing permission: {PERMISSION}")
    return tenant


def _cand(db, tenant, cid: UUID) -> Candidate:
    c = (db.query(Candidate).execution_options(**{removal.INCLUDE_REMOVED: True})
         .filter(Candidate.tenant_id == tenant.tenant_id, Candidate.id == cid).first())
    if c is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return c


def _actor(user: User) -> str:
    return user.email or str(user.id)


@router.get("/recycle-bin")
def recycle_bin(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return removal.recycle_bin(db, _allowed(db, current_user))


@router.get("/removal-runs/{run_id}")
def run_status(run_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models.candidate_removal import CandidateRemovalRun

    tenant = _allowed(db, current_user)
    run = db.query(CandidateRemovalRun).filter(CandidateRemovalRun.tenant_id == tenant.tenant_id, CandidateRemovalRun.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"id": str(run.id), "mode": run.mode, "status": run.status, "total": run.total, "done": run.done, "skipped": run.skipped,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None}


@router.post("/bulk-remove", status_code=202)
def bulk_remove(body: BulkBody, background: BackgroundTasks, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = _allowed(db, current_user)
    mode = "delete" if body.reason == "privacy_request" else body.mode
    if mode == "delete" and body.confirm != "DELETE":
        raise HTTPException(status_code=400, detail="Type DELETE to confirm.")
    try:
        run = removal.start_bulk(db, tenant, body.candidate_ids, mode=mode, reason=body.reason, note=body.note, actor=_actor(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    background.add_task(removal.run_bulk, tenant.tenant_id, tenant.slug, tenant.isolation, run.id)
    return {"run_id": str(run.id), "total": run.total, "mode": mode}


@router.get("/{candidate_id}/delete-summary")
def delete_summary(candidate_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = _allowed(db, current_user)
    return removal.summary(db, tenant, _cand(db, tenant, candidate_id))


@router.post("/{candidate_id}/remove")
def remove(candidate_id: UUID, body: RemoveBody, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = _allowed(db, current_user)
    cand = _cand(db, tenant, candidate_id)
    try:
        if body.reason == "privacy_request":  # DPDP erasure: straight to permanent delete
            return {"deleted": True, **removal.delete_permanently(db, tenant, cand, reason=body.reason, actor=_actor(current_user), confirm=body.confirm or "")}
        if cand.deleted_at is not None:
            raise HTTPException(status_code=409, detail="This candidate is already in the Recycle bin.")
        return removal.remove(db, tenant, cand, reason=body.reason, note=body.note, actor=_actor(current_user))
    except removal.RemovalBlocked as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{candidate_id}/restore")
def restore(candidate_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = _allowed(db, current_user)
    return removal.restore(db, tenant, _cand(db, tenant, candidate_id), actor=_actor(current_user))


@router.post("/{candidate_id}/delete-permanently")
def delete_permanently(candidate_id: UUID, body: RemoveBody, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant = _allowed(db, current_user)
    cand = _cand(db, tenant, candidate_id)
    try:
        return {"deleted": True, **removal.delete_permanently(db, tenant, cand, reason=body.reason, actor=_actor(current_user), confirm=body.confirm or "")}
    except removal.RemovalBlocked as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
