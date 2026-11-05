"""Exit interview -- answered by the EMPLOYEE (fix 2026-10-06), read by HR.

Before: HR's exit dialog showed the questions as an editable form (ExitCaseDialog.tsx -> POST
/service-desk/separations/{id}/exit-interview with separation.case.edit) and the employee's own exit page
never showed them (/me/separation stripped them). Now:
- the employee answers after "Submit resignation" (step 2 "A few questions before you go", skippable) or
  later from their exit page, until the last working day. Draft autosaves; after Submit it is read-only.
- HR sees a READ-ONLY card: status, answers, an AI summary made on submit ("AI summary - check the
  answers"), Send reminder, and private HR notes. HR can't change answers. Only when the person can't
  answer (absconded / terminated / no app access) can HR "Record answers from a call" -- labelled
  "Filled by HR on <date> (call with employee)".
- Only `separation_hr.exit_interview.*` (HR Admin, HRBP, Super Admin) can see answers; managers can't (API).
- Questions, required/optional, en/hi/ta text, AI summary on/off and reminder days: setting
  `employees.exit_interview` (Settings > Onboarding & employees > Exit interview).
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.models.service_desk import Separation

SETTING = "employees.exit_interview"
TYPES = ("text", "stars", "yes_maybe_no", "choice")
LANGS = ("en", "hi", "ta")
DEFAULT = {
    "questions": [
        {"id": "reason", "type": "text", "required": False, "label": {"en": "What is the main reason you are leaving?", "hi": "आप मुख्य रूप से किस कारण से जा रहे हैं?", "ta": "நீங்கள் விலகுவதற்கான முக்கியக் காரணம் என்ன?"}},
        {"id": "liked", "type": "text", "required": False, "label": {"en": "What did you like most about working here?", "hi": "यहाँ काम करने में आपको सबसे अच्छा क्या लगा?", "ta": "இங்கு வேலை செய்ததில் உங்களுக்கு மிகவும் பிடித்தது எது?"}},
        {"id": "improve", "type": "text", "required": False, "label": {"en": "What should we do better?", "hi": "हमें क्या बेहतर करना चाहिए?", "ta": "நாங்கள் எதை இன்னும் சிறப்பாகச் செய்ய வேண்டும்?"}},
        {"id": "manager", "type": "stars", "required": False, "label": {"en": "How well did your manager support you?", "hi": "आपके मैनेजर ने आपका कितना साथ दिया?", "ta": "உங்கள் மேலாளர் உங்களுக்கு எவ்வளவு ஆதரவாக இருந்தார்?"}},
        {"id": "recommend", "type": "yes_maybe_no", "required": False, "label": {"en": "Would you recommend us to a friend?", "hi": "क्या आप हमें किसी दोस्त को सुझाएँगे?", "ta": "எங்களை ஒரு நண்பருக்குப் பரிந்துரைப்பீர்களா?"}},
        {"id": "return", "type": "yes_maybe_no", "required": False, "label": {"en": "Would you come back to work here?", "hi": "क्या आप फिर से यहाँ काम करना चाहेंगे?", "ta": "மீண்டும் இங்கு வேலை செய்ய வருவீர்களா?"}},
    ],
    "ai_summary": True,
    "reminder_days": 3,
}
CANNOT_ANSWER_TYPES = ("absconding", "termination", "death")


class ExitInterviewError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---- settings ----


def _clean_config(value) -> dict:
    value = value if isinstance(value, dict) else {}
    qs, seen = [], set()
    for q in value.get("questions") or []:
        if not isinstance(q, dict):
            continue
        qid = str(q.get("id") or "").strip()[:40]
        label = q.get("label") if isinstance(q.get("label"), dict) else {}
        label = {lang: str(label.get(lang) or "").strip()[:300] for lang in LANGS if str(label.get(lang) or "").strip()}
        if not qid or qid in seen or not label.get("en"):
            continue
        seen.add(qid)
        qtype = q.get("type") if q.get("type") in TYPES else "text"
        item = {"id": qid, "type": qtype, "required": bool(q.get("required")), "label": label}
        if qtype == "choice":
            item["options"] = [str(o).strip()[:80] for o in (q.get("options") or []) if str(o).strip()][:12]
        qs.append(item)
    try:
        days = int(value.get("reminder_days", DEFAULT["reminder_days"]))
    except (TypeError, ValueError):
        days = DEFAULT["reminder_days"]
    return {"questions": qs or DEFAULT["questions"], "ai_summary": bool(value.get("ai_summary", True)), "reminder_days": max(0, min(30, days))}


def config(db: Session, tenant) -> dict:
    from app.platform.settings.resolver import SettingContext, SettingsService

    return _clean_config(SettingsService(db).get(SETTING, SettingContext(tenant=tenant)) or DEFAULT)


def save_config(db: Session, tenant, value: dict, *, actor: str) -> dict:
    from app.platform.settings.resolver import SettingsService

    clean = _clean_config(value)
    SettingsService(db).set(SETTING, clean, scope_type="tenant", scope_id=None, actor=actor, tenant=tenant)
    return config(db, tenant)


# ---- state ----


def _state(s: Separation) -> dict:
    return dict(s.exit_interview_json or {})


def status_of(s: Separation) -> str:
    st = _state(s)
    if st.get("submitted_at"):
        return "submitted"
    return "in_progress" if st.get("answers") else "not_started"


def deadline(s: Separation) -> Optional[date]:
    return s.approved_lwd or s.requested_lwd


def employee_can_edit(s: Separation) -> bool:
    if status_of(s) == "submitted" or s.status in ("withdrawn", "closed", "completed"):
        return False
    d = deadline(s)
    return d is None or date.today() <= d


def _questions_for(db: Session, tenant, s: Separation) -> list[dict]:
    """The questions the answers belong to: frozen at submit, else today's settings."""
    st = _state(s)
    return st.get("questions") or config(db, tenant)["questions"]


def _validate(questions: list[dict], answers: dict, *, final: bool) -> dict:
    out, missing = {}, []
    for q in questions:
        v = answers.get(q["id"])
        if v in (None, "", []):
            if final and q.get("required"):
                missing.append(q["label"].get("en", q["id"]))
            continue
        if q["type"] == "stars":
            try:
                v = int(v)
            except (TypeError, ValueError):
                continue
            if not 1 <= v <= 5:
                continue
        elif q["type"] == "yes_maybe_no":
            if v not in ("yes", "maybe", "no"):
                continue
        elif q["type"] == "choice":
            if v not in (q.get("options") or []):
                continue
        else:
            v = str(v).strip()[:3000]
        out[q["id"]] = v
    if missing:
        raise ExitInterviewError(f"Please answer: {', '.join(missing)}.")
    return out


# ---- employee ----


def employee_view(db: Session, tenant, s: Separation) -> dict:
    st = _state(s)
    d = deadline(s)
    return {"separation_id": str(s.id), "status": status_of(s), "questions": _questions_for(db, tenant, s), "answers": st.get("answers") or {},
            "submitted_at": st.get("submitted_at"), "deadline": d.isoformat() if d else None, "can_edit": employee_can_edit(s),
            "note": "Your answers go only to HR. Your manager will not see them."}


def save_draft(db: Session, tenant, s: Separation, answers: dict, *, actor: str) -> dict:
    if not employee_can_edit(s):
        raise ExitInterviewError("This exit interview can no longer be changed.")
    st = _state(s)
    st["answers"] = {**(st.get("answers") or {}), **_validate(_questions_for(db, tenant, s), answers or {}, final=False)}
    st.setdefault("started_at", _now().isoformat())
    st["updated_at"] = _now().isoformat()
    s.exit_interview_json = st
    db.commit()
    return employee_view(db, tenant, s)


def submit(db: Session, tenant, s: Separation, answers: dict, *, actor: str, filled_by: str = "employee") -> dict:
    if filled_by == "employee" and not employee_can_edit(s):
        raise ExitInterviewError("This exit interview can no longer be changed.")
    questions = _questions_for(db, tenant, s)
    st = _state(s)
    merged = {**(st.get("answers") or {}), **(answers or {})}
    st["answers"] = _validate(questions, merged, final=True)
    st["questions"] = questions  # frozen with the answers
    st["submitted_at"] = _now().isoformat()
    st["filled_by"] = filled_by
    if filled_by == "hr_call":
        st["filled_by_hr"] = {"actor": actor, "at": _now().isoformat()}
    s.exit_interview_json = st
    db.commit()
    log_action(db, "separation", s.id, "exit_interview_submitted" if filled_by == "employee" else "exit_interview_recorded_from_call", actor[:50],
               {"answered": len(st["answers"]), "of": len(questions)})
    if config(db, tenant)["ai_summary"]:
        summarize(db, tenant, s)
    return employee_view(db, tenant, s)


# ---- AI summary ----


def summarize(db: Session, tenant, s: Separation) -> dict:
    from app.platform.ai import governance

    st = _state(s)
    if not st.get("answers"):
        return {}
    if not governance.feature_enabled(db, tenant, "separation.exit_summary"):
        s.exit_interview_ai_summary_json = {"error": "AI summaries are switched off", "generated_at": _now().isoformat()}
        db.commit()
        return s.exit_interview_ai_summary_json
    qa = "\n".join(f"Q: {q['label'].get('en', q['id'])}\nA: {st['answers'].get(q['id'], '(no answer)')}" for q in st.get("questions") or _questions_for(db, tenant, s))
    system = ("Summarise this exit interview for HR in at most 5 short, neutral bullet points: main reasons for leaving, what could have "
              "retained the person, suggestions. Stars are 1 (poor) to 5 (great). Do not speculate beyond the answers.")
    try:
        r = governance.governed_complete(db, tenant, feature="separation.exit_summary", purpose="llm.judgment", system=system,
                                         messages=[{"role": "user", "content": qa}], input_refs={"separation_id": str(s.id)})
        s.exit_interview_ai_summary_json = {"summary": r.text.strip(), "source": "ai", "generated_at": _now().isoformat(), "reviewed": False}
    except Exception as exc:  # noqa: BLE001 -- shown on HR's card as "couldn't make a summary", never blocks the answers
        s.exit_interview_ai_summary_json = {"error": f"{type(exc).__name__}: {str(exc)[:150]}", "generated_at": _now().isoformat()}
    db.commit()
    return s.exit_interview_ai_summary_json


# ---- HR ----


def employee_cannot_answer(db: Session, s: Separation) -> bool:
    from app.models.core_hr import Employee
    from app.models.user import User

    if s.separation_type in CANNOT_ANSWER_TYPES:
        return True
    e = db.get(Employee, s.employee_id)
    user = db.get(User, e.user_id) if e is not None and e.user_id else None
    return user is None or user.deactivated_at is not None


def hr_view(db: Session, tenant, s: Separation) -> dict:
    st = _state(s)
    return {**employee_view(db, tenant, s), "ai_summary": s.exit_interview_ai_summary_json, "hr_notes": s.exit_interview_hr_notes or "",
            "filled_by": st.get("filled_by"), "filled_by_hr": st.get("filled_by_hr"), "reminders": st.get("reminders") or [],
            "can_record_call": employee_cannot_answer(db, s) and status_of(s) != "submitted", "ai_enabled": config(db, tenant)["ai_summary"]}


def set_notes(db: Session, s: Separation, notes: str, *, actor: str) -> None:
    s.exit_interview_hr_notes = (notes or "").strip()[:5000] or None
    db.commit()
    log_action(db, "separation", s.id, "exit_interview_hr_notes_saved", actor[:50], {})


def record_from_call(db: Session, tenant, s: Separation, answers: dict, *, actor: str) -> dict:
    if not employee_cannot_answer(db, s):
        raise ExitInterviewError("The employee can answer themselves - send them a reminder instead. HR records answers only when they can't "
                                 "(absconded, terminated or no app access).")
    if status_of(s) == "submitted":
        raise ExitInterviewError("The answers are already in and can't be changed.")
    submit(db, tenant, s, answers, actor=actor, filled_by="hr_call")
    return hr_view(db, tenant, s)


def send_reminder(db: Session, tenant, s: Separation, *, actor: str, automatic: bool = False) -> dict:
    from app.models.core_hr import Employee
    from app.models.user import User
    from app.platform.comms.defaults import send_default
    from app.platform.links import public_app_url

    if status_of(s) == "submitted":
        raise ExitInterviewError("The exit interview is already submitted.")
    e = db.get(Employee, s.employee_id)
    user = db.get(User, e.user_id) if e is not None and e.user_id else None
    to = [a for a in dict.fromkeys([(user.email if user else None), (e.company_email if e else None), (e.personal_email if e else None)]) if a]
    if not to:
        raise ExitInterviewError("There is no email address for this person.")
    d = deadline(s)
    m = send_default(db, tenant, "employee.exit_interview_reminder", to=to[:2], purpose="email.outbound.hr_letters", related_entity_type="separation",
                     related_entity_id=s.id, ctx={"first_name": (e.preferred_name or e.first_name) if e else "", "link": f"{public_app_url(db)}/exits",
                                                  "before": f"Before your last day ({d.strftime('%d %b %Y')})" if d else "Before your last working day"})
    st = _state(s)
    st["reminders"] = [*(st.get("reminders") or []), {"at": _now().isoformat(), "by": actor, "automatic": automatic, "email": m.status}]
    s.exit_interview_json = st
    db.commit()
    log_action(db, "separation", s.id, "exit_interview_reminder_sent", actor[:50], {"to": to[:2], "automatic": automatic, "email": m.status})
    return {"sent_to": to[:2], "status": m.status}


def run_reminders(db: Session, tenant, *, today: Optional[date] = None) -> int:
    """Hourly job: one automatic reminder when the last working day is `reminder_days` away (or closer) and
    nothing was submitted."""
    today = today or date.today()
    days = config(db, tenant)["reminder_days"]
    if days <= 0:
        return 0
    sent = 0
    for s in db.query(Separation).filter(Separation.tenant_id == tenant.tenant_id, Separation.status.in_(("submitted", "retention", "approved", "clearance"))).all():
        d = deadline(s)
        if d is None or not (today <= d <= today + timedelta(days=days)) or status_of(s) == "submitted" or employee_cannot_answer(db, s):
            continue
        if any(r.get("automatic") for r in (_state(s).get("reminders") or [])):
            continue
        try:
            send_reminder(db, tenant, s, actor="exit interview reminder", automatic=True)
            sent += 1
        except ExitInterviewError:
            continue
    return sent


# ---- report (aggregates only; no individual answers) ----


def report(db: Session, tenant) -> dict:
    from app.employees.directory import current_record, name_of
    from app.models.core_hr import Department, Employee

    deps = {d.id: d.name for d in db.query(Department).filter(Department.tenant_id == tenant.tenant_id).all()}
    rows = [s for s in db.query(Separation).filter(Separation.tenant_id == tenant.tenant_id).all() if status_of(s) == "submitted"]
    from app.models.metadata import MasterValue

    reasons = {v.code: (v.label_i18n or {}).get("en", v.code) for v in db.query(MasterValue).filter(MasterValue.tenant_id == tenant.tenant_id,
                                                                                                    MasterValue.type_code == "exit_reason").all()}

    def band(e: Optional[Employee], s: Separation) -> str:
        start = (e.joined_on if e else None)
        end = deadline(s) or date.today()
        if start is None:
            return "Unknown"
        years = (end - start).days / 365.25
        return "Under 1 year" if years < 1 else "1-3 years" if years < 3 else "3-5 years" if years < 5 else "5+ years"

    groups: dict = {"department": {}, "manager": {}, "tenure": {}}
    overall = {"count": 0, "stars": [], "recommend": {"yes": 0, "maybe": 0, "no": 0}, "return": {"yes": 0, "maybe": 0, "no": 0}, "reasons": {}}

    def add(bucket: dict, a: dict, reason: str):
        bucket["count"] = bucket.get("count", 0) + 1
        if isinstance(a.get("manager"), int):
            bucket.setdefault("stars", []).append(a["manager"])
        for k in ("recommend", "return"):
            if a.get(k) in ("yes", "maybe", "no"):
                bucket.setdefault(k, {"yes": 0, "maybe": 0, "no": 0})[a[k]] += 1
        bucket.setdefault("reasons", {})[reason] = bucket.get("reasons", {}).get(reason, 0) + 1

    for s in rows:
        a = _state(s).get("answers") or {}
        e = db.get(Employee, s.employee_id)
        r = current_record(db, e.id) if e else None
        reason = reasons.get(s.reason_code or "", s.reason_code or "Not given")
        mgr = db.get(Employee, r.manager_employee_id) if r is not None and r.manager_employee_id else None
        add(overall, a, reason)
        for key, val in (("department", deps.get(r.department_id) if r is not None and r.department_id else "No department"),
                         ("manager", name_of(mgr) if mgr else "No manager"), ("tenure", band(e, s))):
            add(groups[key].setdefault(val or "Unknown", {}), a, reason)

    def finish(b: dict) -> dict:
        stars = b.pop("stars", [])
        b["manager_rating_avg"] = round(sum(stars) / len(stars), 1) if stars else None
        b["manager_rating_n"] = len(stars)
        b["top_reasons"] = sorted(b.pop("reasons", {}).items(), key=lambda kv: -kv[1])[:5]
        return b

    return {"overall": finish(overall), "by_department": {k: finish(v) for k, v in groups["department"].items()},
            "by_manager": {k: finish(v) for k, v in groups["manager"].items()}, "by_tenure": {k: finish(v) for k, v in groups["tenure"].items()},
            "note": "Totals only - no individual answers."}
