from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.application import TERMINAL_APPLICATION_STATUSES, Application


def put_application_on_hold(db: Session, application: Application, actor: str) -> None:
    """Any non-terminal status -> on_hold. Stores the current status into previous_status
    so resume_application_from_hold can restore it later.

    Rejects re-holding an already on-hold application -- unlike jobs' hold_job (which
    tolerates a same-status no-op since a job has no previous_status to protect),
    applications store the pre-hold status in that column. Silently "holding" an
    already-on-hold application would overwrite previous_status with 'on_hold' itself,
    permanently losing the real status resume should restore.
    """
    if application.status == "on_hold":
        raise HTTPException(status_code=400, detail="Application is already on hold.")
    if application.status in TERMINAL_APPLICATION_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot put an application on hold from terminal status '{application.status}'.",
        )

    previous_status = application.status
    application.previous_status = previous_status
    application.status = "on_hold"
    db.commit()
    db.refresh(application)
    log_action(
        db, "application", application.id, "application_put_on_hold", actor,
        {"previous_status": previous_status},
    )


def resume_application_from_hold(db: Session, application: Application, actor: str) -> None:
    """on_hold -> the status stored in previous_status when it was put on hold."""
    if application.status != "on_hold":
        raise HTTPException(
            status_code=400, detail=f"Only an on-hold application can be resumed, not '{application.status}'."
        )
    # previous_status is always set by put_application_on_hold before this point is
    # reachable -- there's no code path that sets status='on_hold' any other way. A missing
    # value here means the row was put on hold before this feature existed (or edited
    # directly in the DB), which is a data-integrity problem worth surfacing loudly rather
    # than silently guessing a fallback status.
    if not application.previous_status:
        raise HTTPException(
            status_code=409,
            detail="This application has no recorded previous status to resume to. It must be corrected manually.",
        )

    restored_status = application.previous_status
    application.status = restored_status
    application.previous_status = None
    db.commit()
    db.refresh(application)
    log_action(
        db, "application", application.id, "application_resumed_from_hold", actor,
        {"restored_status": restored_status},
    )


def assert_application_not_on_hold(application: Application) -> None:
    """Guard for every pipeline-mutating endpoint (screen, shortlist, schedule, salary,
    BGV, offer) -- same principle as app/jobs/router.py's on_hold guard on JD generation/
    publishing. Read-only endpoints are never guarded; only actions that would advance or
    otherwise mutate the pipeline while it's deliberately paused."""
    if application.status == "on_hold":
        raise HTTPException(
            status_code=400,
            detail="This application is on hold. Resume it before performing pipeline actions.",
        )
