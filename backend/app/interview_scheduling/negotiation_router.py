from html import escape

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.integrations.google_calendar import APP_TIMEZONE, format_ist_datetime
from app.interview_scheduling.negotiation import (
    NegotiationPageState,
    TOKEN_EXPIRY_DAYS,
    _parse_slot_hours,
    _slot_times_for_day,
    get_negotiation_form,
    submit_negotiation_response,
)
from app.platform.comms.theme import get_theme_and_org_context
from app.platform.tenancy.context import require_current_tenant

# No prefix, no auth -- these are the exact links an interviewer or candidate clicks from
# their email, same "public, no-auth" pattern as app/interview_scheduling/confirm_router.py.
# GET renders the pick-2-of-3 form (or a terminal outcome); POST is that same form's submit
# (either "action=submit" with 2 checked "slots" values, or "action=decline").
router = APIRouter(tags=["interview-negotiation"])


# --- inline icons -- small monoline SVGs, currentColor stroke, no external icon font/CDN
# (this page is the last stop from an email link and must render on its own). ---

def _icon(path: str, size: int = 18) -> str:
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        f'class="icon" aria-hidden="true">{path}</svg>'
    )


ICON_CALENDAR = _icon('<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>')
ICON_CLOCK = _icon('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>')
ICON_CHECK = _icon('<path d="M20 6 9 17l-5-5"/>', size=16)
ICON_INFO = _icon('<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>')
ICON_MAIL = _icon('<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>')
ICON_SHIELD = _icon('<path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/><path d="m9 12 2 2 4-4"/>')
ICON_VIDEO = _icon('<rect x="3" y="6" width="13" height="12" rx="2"/><path d="m16 10 5-3v10l-5-3z"/>')


# Brand-tied rules (gradient, primary accent, wordmark) use {{TOKEN}} placeholders filled
# in by _page_css() from the tenant's own brand_theme row -- see
# app.platform.comms.theme.get_theme_and_org_context. Everything else here
# is this page's own generic, non-client-specific design-system palette (status greens/
# ambers/reds, neutral grays) -- same class of exclusion as frontend/src/theme's own
# already-neutral palette (see backend/tests/test_no_hardcoded_tenant_values.py's own
# scoping note), not a per-tenant value.
_PAGE_CSS_TEMPLATE = """
  * { box-sizing: border-box; }
  body { font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif; background: #eef1f6;
         margin: 0; padding: 0 0 32px; color: #1a1f36; }
  .icon { display: inline-block; vertical-align: -3px; flex-shrink: 0; }
  .shell { max-width: 900px; margin: 0 auto; background: #ffffff; box-shadow: 0 4px 24px rgba(20,30,60,0.08); }
  .topbar { display: flex; align-items: center; justify-content: space-between; padding: 18px 32px;
            background: linear-gradient(120deg, {{GRADIENT_FROM}}, {{GRADIENT_TO}}); color: #ffffff; }
  .brand { display: flex; align-items: center; gap: 10px; }
  .logo-cube { width: 30px; height: 30px; border-radius: 8px;
               background: linear-gradient(135deg, #4f9dff, #7b5cff); flex-shrink: 0; }
  .brand-name { font-weight: 700; letter-spacing: 0.04em; font-size: 15px; color: #f5f8ff; }
  .badge { display: flex; align-items: center; gap: 6px; background: rgba(255,255,255,0.16);
           border: 1px solid rgba(255,255,255,0.3); border-radius: 999px; padding: 6px 14px;
           font-size: 13px; font-weight: 600; color: #ffffff; white-space: nowrap; }
  .page-body { display: grid; grid-template-columns: 1fr 260px; gap: 28px; padding: 32px; }
  @media (max-width: 720px) { .page-body { grid-template-columns: 1fr; padding: 24px 20px; } }
  h1.heading { font-size: 24px; font-weight: 800; margin: 0 0 10px; color: {{GRADIENT_FROM}}; }
  p.copy { font-size: 15px; line-height: 1.6; color: #3a4257; margin: 0 0 26px; }
  p.copy strong.job { color: {{PRIMARY}}; }
  .section-label { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 700;
                   text-transform: uppercase; letter-spacing: 0.04em; color: #5b6478; margin-bottom: 12px; }
  .slot-row { display: flex; align-items: center; gap: 14px; border: 1.5px solid #dde2ee; border-radius: 12px;
              padding: 14px 16px; margin-bottom: 12px; cursor: pointer; transition: border-color .15s, background .15s; }
  .slot-row:hover { border-color: #adc4f5; }
  .slot-row.selected { border-color: {{PRIMARY}}; background: #eef4ff; }
  .slot-row input[type=checkbox] { width: 18px; height: 18px; accent-color: {{PRIMARY}}; flex-shrink: 0; }
  .slot-info { display: flex; flex-direction: column; gap: 4px; }
  .slot-date, .slot-time { display: flex; align-items: center; gap: 6px; font-size: 14px; color: #3a4257; }
  .slot-time strong { color: {{PRIMARY}}; font-weight: 700; }
  .error-banner { background: #fdecec; border: 1px solid #f3b4b4; color: #9a2b2b; border-radius: 10px;
                  padding: 10px 14px; font-size: 14px; margin-bottom: 18px; }
  .action-bar { margin-top: 24px; padding-top: 20px; border-top: 1px solid #eef0f5; display: flex;
                flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 16px; }
  .action-info { display: flex; align-items: flex-start; gap: 8px; font-size: 13px; color: #5b6478;
                 max-width: 320px; }
  .action-buttons { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
  .btn { display: inline-flex; align-items: center; gap: 8px; border-radius: 10px; padding: 11px 20px;
         font-size: 14px; font-weight: 700; cursor: pointer; border: none; }
  .btn-solid { background: {{PRIMARY}}; color: #ffffff; }
  .btn-solid:disabled { background: #b9c8ea; cursor: not-allowed; }
  .btn-outline { background: #ffffff; color: {{PRIMARY}}; border: 1.5px solid {{PRIMARY}}; }
  .confirm-group { display: flex; flex-direction: column; align-items: center; gap: 4px; }
  .confirm-subtext { font-size: 12px; color: #8a93a6; }
  .side-col { display: flex; flex-direction: column; gap: 16px; }
  .info-card, .secure-card { border-radius: 12px; padding: 16px; font-size: 13px; }
  .info-card { background: #f6f8fc; border: 1px solid #e6eaf3; }
  .info-row { display: flex; align-items: flex-start; gap: 10px; }
  .info-row + .info-row { margin-top: 14px; }
  .info-row strong { display: block; font-size: 13px; color: #1a1f36; }
  .info-row span.value { color: #5b6478; }
  .secure-card { background: #eafaf1; border: 1px solid #bfe9d2; display: flex; align-items: flex-start;
                 gap: 10px; color: #1d6b45; }
  .secure-card strong { display: block; color: #14532d; }
  .footer-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; padding: 16px 32px;
                background: #f6f8fc; border-top: 1px solid #e6eaf3; font-size: 13px; color: #5b6478; }
  .footer-bar .sep { color: #cbd2e0; }
  .outcome { padding: 12px 0 32px; text-align: left; }
  .outcome h1 { font-size: 22px; margin-bottom: 10px; }
  .outcome p { font-size: 15px; line-height: 1.6; color: #3a4257; }
  .outcome.tone-success h1 { color: #1b8a5a; }
  .outcome.tone-warning h1 { color: #b8860b; }
  .outcome.tone-error h1 { color: #b23b3b; }
  .details { margin-top: 18px; padding-top: 16px; border-top: 1px solid #eef0f5; }
  .details p { margin: 6px 0; }
"""


def _page_css(theme: dict) -> str:
    return (
        _PAGE_CSS_TEMPLATE.replace("{{PRIMARY}}", theme["primary_color"])
        .replace("{{GRADIENT_FROM}}", theme["gradient_from"])
        .replace("{{GRADIENT_TO}}", theme["gradient_to"])
    )

_SLOT_JS = """
function ctdUpdateSlots() {
  var boxes = document.querySelectorAll('.slot-checkbox');
  var checked = 0;
  boxes.forEach(function (cb) {
    if (cb.checked) checked += 1;
    var row = cb.closest('.slot-row');
    if (row) row.classList.toggle('selected', cb.checked);
  });
  var submitBtn = document.getElementById('submit-btn');
  if (submitBtn) submitBtn.disabled = (checked !== REQUIRED_PICKS);
  var countEl = document.getElementById('slot-count');
  if (countEl) countEl.textContent = checked + ' of ' + REQUIRED_PICKS + ' selected';
}
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('.slot-checkbox').forEach(function (cb) {
    cb.addEventListener('change', ctdUpdateSlots);
  });
  ctdUpdateSlots();
});
"""


def _shell(inner_html: str, theme: dict, org_display_name: str, expiry_days: int = TOKEN_EXPIRY_DAYS) -> str:
    brand_name = escape(org_display_name.upper())
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Interview Scheduling</title>
  <style>{_page_css(theme)}</style>
</head>
<body>
  <div class="shell">
    <div class="topbar">
      <div class="brand">
        <div class="logo-cube"></div>
        <span class="brand-name">{brand_name}</span>
      </div>
      <div class="badge">{ICON_CALENDAR} Interview Scheduling</div>
    </div>
    {inner_html}
    <div class="footer-bar">
      {ICON_CLOCK} These links expire in {expiry_days} days
      <span class="sep">|</span>
      {ICON_MAIL} Need help? Reply to this email or contact your recruiter.
    </div>
  </div>
</body>
</html>
"""


def _copy_for(row, slot_count: int) -> tuple[str, str]:
    """(heading, body copy) -- candidate sees the job title prominently; interviewer sees
    the candidate's name plus the job title. `slot_count`/`row.required_picks` (Part 8
    section 6 -- both are real, per-row-snapshotted tenant settings now, not always 3/2)."""
    job_title = escape(row.job_title or "this role")
    required_picks = row.required_picks
    if row.role == "candidate":
        name = escape(row.candidate_name or "there")
        return (
            f"Hi {name},",
            f"We'd like to schedule your interview for the <strong class=\"job\">{job_title}</strong> "
            f"position. Please pick exactly {required_picks} of the {slot_count} times below that work best for you.",
        )
    name = escape(row.interviewer_name or "there")
    candidate_name = escape(row.candidate_name or "the candidate")
    return (
        f"Hi {name},",
        f"Please pick exactly {required_picks} of the {slot_count} times below when you're available to interview "
        f"<strong class=\"job\">{candidate_name}</strong> for the {job_title} role.",
    )


def _render_form(state: NegotiationPageState) -> str:
    row = state.row
    slot_times = _slot_times_for_day(row.round_day, _parse_slot_hours(row.slot_hours_json))
    heading, copy = _copy_for(row, len(slot_times))
    checked = set(state.checked_isos)

    rows_html = []
    for slot_time in slot_times:
        iso = slot_time.isoformat()
        local = slot_time.astimezone(APP_TIMEZONE)
        date_label = local.strftime("%d %b %Y, %A")
        time_label = local.strftime("%I:%M %p IST")
        is_checked = iso in checked
        rows_html.append(
            f'<label class="slot-row{" selected" if is_checked else ""}">'
            f'<input type="checkbox" class="slot-checkbox" name="slots" value="{escape(iso)}" '
            f'{"checked" if is_checked else ""} />'
            f'<span class="slot-info">'
            f'<span class="slot-date">{ICON_CALENDAR} {date_label}</span>'
            f'<span class="slot-time">{ICON_CLOCK} <strong>{time_label}</strong></span>'
            f'</span></label>'
        )

    error_html = f'<div class="error-banner">{escape(state.error)}</div>' if state.error else ""
    duration = row.duration_minutes or 60

    inner = f"""
    <div class="page-body">
      <div class="main-col">
        <h1 class="heading">{heading}</h1>
        <p class="copy">{copy}</p>
        {error_html}
        <div class="section-label">{ICON_CALENDAR} Available Time Slots</div>
        <form method="post" action="">
          {''.join(rows_html)}
          <div class="action-bar">
            <div class="action-info">{ICON_INFO} Can't make these times? No problem! Let us know and we'll find
              another time that works for you.</div>
            <div class="action-buttons">
              <button type="submit" name="action" value="decline" class="btn btn-outline">
                {ICON_CALENDAR} None of these work for me</button>
              <div class="confirm-group">
                <button type="submit" name="action" value="submit" id="submit-btn" class="btn btn-solid" disabled>
                  {ICON_CHECK} Submit My Selections</button>
                <div class="confirm-subtext" id="slot-count">{len(checked)} of {row.required_picks} selected</div>
              </div>
            </div>
          </div>
        </form>
      </div>
      <div class="side-col">
        <div class="info-card">
          <div class="info-row">{ICON_CLOCK}<div><strong>Duration</strong><span class="value">{duration} Minutes</span></div></div>
          <div class="info-row">{ICON_VIDEO}<div><strong>Interview Mode</strong><span class="value">Video Call (link in your calendar invite)</span></div></div>
        </div>
        <div class="secure-card">
          {ICON_SHIELD}
          <div><strong>Your Information is Secure</strong>Your details and interview preferences are safe with us.</div>
        </div>
      </div>
    </div>
    <script>var REQUIRED_PICKS = {row.required_picks};{_SLOT_JS}</script>
    """
    return inner


_OUTCOME_COPY = {
    "invalid": ("error", "Link not recognized", "We can't find this link. Please use the newest email from us, or contact the recruiter."),
    "expired": ("warning", "Link expired", "This link has expired. Please contact the recruiter to arrange a new time."),
    "expired_resent": ("warning", "Link expired - new one sent", "This link has expired - we've sent you a new one. Please use the newest email from us."),
    "expired_rearranging": ("warning", "Link expired - new times coming", "This link has expired. We're arranging new times and will email you shortly - please use that newest email."),
    "picked": ("success", "Already done", "You've already picked your times. We'll email you once the interview is confirmed."),
    "cancelled": ("warning", "Interview cancelled", "This interview was cancelled, so this link no longer works. If you think this is a mistake, please contact the recruiter."),
    "replaced": ("warning", "There's a newer email", "This link was replaced by a newer email from us. Please use the newest one."),
    "already_handled": ("warning", "Already handled", "This has already been handled. If you didn't do this yourself, please contact the recruiter."),
    "declined": ("warning", "Thanks -- Noted", "We've recorded that none of these times work. We'll follow up with another option."),
    "interviewer_submitted": ("success", "Thanks!", "We'll now ask the candidate for their availability and follow up once a time is confirmed."),
    "candidate_reprompted": ("success", "Thanks!", "We need to double-check one more thing -- you'll receive a follow-up email shortly with a couple of different options."),
}


def _render_outcome(state: NegotiationPageState) -> str:
    if state.status == "confirmed":
        tone, heading, message = "success", "Interview Confirmed", "Your interview is confirmed! We look forward to speaking with you."
    else:
        tone, heading, message = _OUTCOME_COPY.get(state.status, ("error", "Interview Scheduling", "Something went wrong."))

    details_html = ""
    row = state.row
    if state.status == "picked" and state.scheduled_at:  # fix 2026-10-04: "You've already picked a time: <time>"
        message = f"You've already picked a time: {format_ist_datetime(state.scheduled_at)}. The calendar invite and meeting link are in your email."
    if state.status == "confirmed" and row is not None and state.scheduled_at:
        details_html = f"""
        <div class="details">
          <p><strong>Role:</strong> {escape(row.job_title or "")}</p>
          <p><strong>Interviewer:</strong> {escape(row.interviewer_name or "")}</p>
          <p><strong>Time:</strong> {escape(format_ist_datetime(state.scheduled_at))}</p>
        </div>
        """

    return f"""
    <div class="page-body">
      <div class="main-col outcome tone-{tone}">
        <h1>{escape(heading)}</h1>
        <p>{escape(message)}</p>
        {details_html}
      </div>
    </div>
    """


def render_negotiation_page(state: NegotiationPageState, theme: dict, org_display_name: str) -> str:
    """The one page every interviewer/candidate email link lands on, GET (to view) or POST
    (to submit) alike -- pick-2-of-3 checkboxes plus a decline option while `state.status`
    is "form" (including a re-render with `state.error` set after an invalid submission),
    or one of the terminal outcome states otherwise."""
    if state.status == "form":
        return _shell(_render_form(state), theme, org_display_name)
    return _shell(_render_outcome(state), theme, org_display_name)


def _theme_and_org(db: Session) -> tuple[dict, str]:
    ctx = get_theme_and_org_context(db, require_current_tenant())
    return ctx["theme"], ctx["org"]["display_name"]


@router.get("/interview-negotiation/{token}", response_class=HTMLResponse)
def negotiate_interview_slot(token: str, db: Session = Depends(get_db)):
    state = get_negotiation_form(db, token)
    theme, org_display_name = _theme_and_org(db)
    return HTMLResponse(content=render_negotiation_page(state, theme, org_display_name))


@router.post("/interview-negotiation/{token}", response_class=HTMLResponse)
def submit_interview_negotiation(
    token: str,
    action: str = Form(...),
    slots: list[str] = Form([]),
    db: Session = Depends(get_db),
):
    state = submit_negotiation_response(db, token, action=action, selected_isos=slots)
    theme, org_display_name = _theme_and_org(db)
    return HTMLResponse(content=render_negotiation_page(state, theme, org_display_name))
