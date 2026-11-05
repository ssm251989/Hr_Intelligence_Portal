"""Part 18.18: the BGV decision is HR's -- Passed / Resend form / Failed. The system never marks
BGV failed by itself (document checks only colour and explain).

- passed:  bgv_cleared (then the joining-date step, 18.19).
- resend:  the candidate gets the upload form again listing exactly what is needed + HR's note
           (the joining-documents link, 18.16); the status stays in BGV.
- failed:  a reason is required; the candidate gets a polite "BGV unsuccessful" email with it.
           HR previews and can edit the message before it is sent (template
           recruitment.bgv_unsuccessful, editable in Settings > Communication > Templates).
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole

IN_BGV = ("bgv_requested", "bgv_pending")
# BGV document type -> joining document asked for again
FROM_BGV = {"pan": "pan", "aadhaar": "aadhaar", "degree": "education", "experience": "experience"}


def _names(db, application):
    cand = db.get(Candidate, application.candidate_id)
    job = db.get(JobRole, application.job_role_id)
    from app.recruitment.offer_welcome import greeting_name

    first = greeting_name(db, cand) if cand else ""  # fix 2026-10-04: never the first word only (it can be the surname)
    return cand, job, first


def preview_failed(db: Session, tenant, application: Application, reason: str) -> dict:
    from app.platform.settings.resolver import SettingContext, SettingsService

    _cand, job, first = _names(db, application)
    company = SettingsService(db).get("org.display_name", SettingContext(tenant=tenant)) or ""
    message = (f"Hi {first},\n\nThank you for your patience while we completed your background verification for the "
               f"{job.title if job else ''} role. We're sorry to tell you that we can't take your application forward at this time.\n\n"
               f"Reason: {reason.strip()}\n\nIf you think something is not right, please reply to this email and we will look into it.\n\n"
               f"We wish you all the best.")
    return {"subject": f"{job.title if job else 'Your application'}: background verification update", "message": message, "company": company}


def decide(db: Session, tenant, application: Application, *, decision: str, actor: str, note: Optional[str] = None,
           reason: Optional[str] = None, message: Optional[str] = None, codes: Optional[list[str]] = None) -> dict:
    from app.platform.comms.defaults import send_default
    from app.recruitment import budgets, joining_docs

    if application.status not in IN_BGV:
        raise ValueError("This candidate is not waiting for a BGV decision.")
    cand, job, first = _names(db, application)
    previous = application.status
    out: dict = {"decision": decision}
    if decision == "passed":
        application.status = "bgv_cleared"
        db.commit()
        try:  # Part 18.19: HR proposes the joining dates next
            from app.recruitment.joining_dates import after_bgv_passed

            after_bgv_passed(db, tenant, application, actor=actor)
        except Exception:  # noqa: BLE001
            pass
    elif decision == "discrepancy":  # Part 21.4: clear, but something didn't match -- HR notes what
        if not (note or "").strip():
            raise ValueError("Write what didn't match, so it stays on the record.")
        application.status = "bgv_cleared"
        db.commit()
        try:
            from app.recruitment.joining_dates import after_bgv_passed

            after_bgv_passed(db, tenant, application, actor=actor)
        except Exception:  # noqa: BLE001
            pass
    elif decision == "resend":
        wanted = [c for c in (codes or []) if c]
        if not wanted:
            raise ValueError("Choose which documents the candidate should send again.")
        mapped = [FROM_BGV.get(c, c) for c in wanted]
        application.status = "bgv_pending"
        db.commit()
        out.update(joining_docs.request_reupload(db, tenant, application, actor=actor, codes=mapped, note=note))
    elif decision == "failed":
        if not (reason or "").strip():
            raise ValueError("Please give the reason - it is included in the email to the candidate.")
        application.status = "bgv_rejected"
        db.commit()
        budgets.release(db, tenant, application.id)
        body = (message or preview_failed(db, tenant, application, reason)["message"]).strip()
        sent = False
        if cand and cand.email:
            try:
                msg = send_default(db, tenant, "recruitment.bgv_unsuccessful", to=[cand.email], related_entity_type="application",
                                   related_entity_id=application.id, ctx={"candidate_first_name": first, "job_title": job.title if job else "", "message": body})
                sent = msg.status in ("sent", "queued")
            except Exception:  # noqa: BLE001
                sent = False
        out["email_sent"] = sent
    else:
        raise ValueError("decision must be passed, discrepancy, resend or failed")
    log_action(db, "application", application.id, f"bgv_{decision}", actor[:50],
               {"previous_status": previous, "new_status": application.status, "reason": reason, "note": note, "codes": codes})
    out["status"] = application.status
    try:  # Part 21.4: the vendor's assignment gets HR's decision
        from app.bgv.vendors import on_decision

        on_decision(db, tenant, application, decision)
    except Exception:  # noqa: BLE001
        db.rollback()
    return out
