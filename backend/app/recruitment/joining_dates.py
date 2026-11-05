"""Part 18.19: joining date -- after BGV passes, HR proposes 3 tentative dates; the candidate is
emailed "Background verification successful" with the dates and picks one with one click.

Stored on applications.custom_fields["joining"]:
  {"proposed": ["2026-10-15", ...], "proposed_at", "proposed_by", "chosen", "chosen_at", "history": [...]}
Reminder after recruitment.joining.reminder_hours (default [48]); HR can propose new dates at any
time (the old link stops working). When the candidate chooses, 18.20 sends the offer + welcome.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.user import User

ACTION = "joining_date_choice"
TTL_DAYS = 14


def _setting(db, tenant, key):
    from app.platform.settings.resolver import SettingContext, SettingsService

    return SettingsService(db).get(key, SettingContext(tenant=tenant))


def info(application: Application) -> dict:
    return dict((application.custom_fields or {}).get("joining") or {})


def _save(db, application, data):
    fields = dict(application.custom_fields or {})
    fields["joining"] = data
    application.custom_fields = fields
    db.commit()


def link(token: str, db: Optional[Session] = None) -> str:
    from app.platform.links import public_app_url  # fix 2026-10-04: the public address setting, not FRONTEND_URL

    return f"{public_app_url(db)}/joining/{token}"


def after_bgv_passed(db: Session, tenant, application: Application, actor: str = "system") -> None:
    """Nudge the recruiters: pick 3 joining dates (in-app)."""
    from app.models.comms import OutboundMessage

    job = db.get(JobRole, application.job_role_id)
    cand = db.get(Candidate, application.candidate_id)
    ids = [i for i in (job.created_by, job.hiring_manager_id) if i] if job else []
    emails = [u.email for u in db.query(User).filter(User.tenant_id == tenant.tenant_id, User.id.in_(ids or [None])) if u.email]
    if not emails and "@" in actor:
        emails = [actor]
    for addr in emails:
        db.add(OutboundMessage(tenant_id=tenant.tenant_id, channel="in_app", purpose="recruitment.joining", to_addresses=[addr],
                               subject=f"BGV passed for {(cand.full_name if cand else None) or 'a candidate'} ({job.title if job else ''}) - pick 3 joining dates.",
                               body_ref="/offers", status="sent", related_entity_type="application", related_entity_id=application.id))
    db.commit()


def propose(db: Session, tenant, application: Application, dates: list[str], *, actor: str, note: Optional[str] = None) -> dict:
    from app.models.iam import ActionToken
    from app.platform.comms.defaults import send_default
    from app.platform.iam.action_tokens import create_action_token
    from app.recruitment.offer_welcome import greeting_name

    if application.status != "bgv_cleared":
        raise ValueError("Joining dates are proposed once BGV has passed.")
    try:
        parsed = sorted({date.fromisoformat(d) for d in dates})
    except ValueError:
        raise ValueError("Please give the dates as YYYY-MM-DD.")
    if len(parsed) != 3:
        raise ValueError("Please propose exactly 3 different dates.")
    if parsed[0] <= date.today():
        raise ValueError("The dates must be in the future.")
    now = datetime.now(timezone.utc)
    for t in db.query(ActionToken).filter(ActionToken.tenant_id == tenant.tenant_id, ActionToken.entity_id == application.id,
                                          ActionToken.action == ACTION, ActionToken.invalidated_at.is_(None)):
        t.invalidated_at = now  # new dates replace the old link
    row = create_action_token(db, tenant, entity_type="application", entity_id=application.id, action=ACTION,
                              payload={"reminders": 0}, created_by=actor[:50], ttl_days=TTL_DAYS)
    data = info(application)
    history = data.get("history", [])
    if data.get("proposed"):
        history.append({"proposed": data["proposed"], "at": data.get("proposed_at"), "chosen": data.get("chosen")})
    data = {"proposed": [d.isoformat() for d in parsed], "proposed_at": now.isoformat(), "proposed_by": actor, "note": note,
            "chosen": None, "chosen_at": None, "history": history[-5:]}
    _save(db, application, data)
    cand = db.get(Candidate, application.candidate_id)
    job = db.get(JobRole, application.job_role_id)
    sent = False
    if cand and cand.email:
        pretty = "\n".join(f"- {d.strftime('%A, %d %B %Y')}" for d in parsed)
        try:
            msg = send_default(db, tenant, "recruitment.joining_dates", to=[cand.email], related_entity_type="application", related_entity_id=application.id,
                               ctx={"candidate_first_name": greeting_name(db, cand), "job_title": job.title if job else "",
                                    "dates": pretty, "choose_link": link(row.token, db), "note": note or ""})
            sent = msg.status in ("sent", "queued")
        except Exception:  # noqa: BLE001
            sent = False
    log_action(db, "application", application.id, "joining_dates_proposed", actor[:50], {"dates": data["proposed"], "sent": sent})
    return {"proposed": data["proposed"], "sent": sent, "link": None if sent else link(row.token, db)}


def choose(db: Session, tenant, token_row, application: Application, chosen: str) -> dict:
    data = info(application)
    if chosen not in (data.get("proposed") or []):
        raise ValueError("Please pick one of the dates offered.")
    now = datetime.now(timezone.utc)
    data["chosen"], data["chosen_at"] = chosen, now.isoformat()
    _save(db, application, data)
    token_row.responded_at = now
    db.commit()
    log_action(db, "application", application.id, "joining_date_chosen", "candidate", {"date": chosen})
    try:  # Part 18.20: offer letter + welcome go out automatically
        from app.recruitment.offer_welcome import after_joining_date_chosen

        after_joining_date_chosen(db, tenant, application)
    except Exception:  # noqa: BLE001 -- the choice is saved either way; HR sees it
        pass
    return {"chosen": chosen}


def remind_due(db: Session, tenant) -> int:
    from app.models.iam import ActionToken
    from app.platform.comms.defaults import send_default
    from app.recruitment.offer_welcome import greeting_name

    hours = sorted(int(h) for h in (_setting(db, tenant, "recruitment.joining.reminder_hours") or [48]) if int(h) > 0)
    if not hours:
        return 0
    now = datetime.now(timezone.utc)
    done = 0
    for row in db.query(ActionToken).filter(ActionToken.tenant_id == tenant.tenant_id, ActionToken.action == ACTION, ActionToken.responded_at.is_(None),
                                            ActionToken.invalidated_at.is_(None), ActionToken.created_at < now - timedelta(hours=hours[0]), ActionToken.expires_at > now):
        sent = int((row.payload_json or {}).get("reminders", 0))
        if sent >= len(hours) or now - row.created_at < timedelta(hours=hours[sent]):
            continue
        app = db.get(Application, row.entity_id)
        cand = db.get(Candidate, app.candidate_id) if app else None
        job = db.get(JobRole, app.job_role_id) if app else None
        if app is None or not cand or not cand.email:
            continue
        pretty = "\n".join(f"- {date.fromisoformat(d).strftime('%A, %d %B %Y')}" for d in info(app).get("proposed", []))
        try:
            send_default(db, tenant, "recruitment.joining_dates", to=[cand.email], related_entity_type="application", related_entity_id=app.id,
                         ctx={"candidate_first_name": greeting_name(db, cand), "job_title": job.title if job else "", "dates": pretty,
                              "choose_link": link(row.token, db), "note": "Reminder: please choose your joining date."})
        except Exception:  # noqa: BLE001
            pass
        row.payload_json = {**(row.payload_json or {}), "reminders": sent + 1}
        db.commit()
        log_action(db, "application", app.id, "joining_dates_reminder", "system", {})
        done += 1
    return done
