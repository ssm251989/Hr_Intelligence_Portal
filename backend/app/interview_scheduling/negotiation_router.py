from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.integrations.google_calendar import format_ist_datetime
from app.interview_scheduling.negotiation import NegotiationOutcome, handle_negotiation_click

# No prefix, no auth -- these are the exact links an interviewer or candidate clicks from
# their email, same "public, no-auth" pattern as app/interview_scheduling/confirm_router.py.
router = APIRouter(tags=["interview-negotiation"])

_STATUS_COLORS = {
    "confirmed": "#1b8a5a",
    "recorded": "#1b8a5a",
    "declined": "#b8860b",
    "already_handled": "#b8860b",
    "expired": "#b8860b",
    "invalid": "#b23b3b",
}


def render_negotiation_page(outcome: NegotiationOutcome) -> str:
    """A small, self-contained HTML page -- no build step, no JS -- since this is the last
    stop for an interviewer or candidate coming straight from an email link, not part of the
    recruiter-facing SPA. Mirrors confirm_router.py's own render_confirmation_page."""
    color = _STATUS_COLORS.get(outcome.status, "#b23b3b")
    heading = "Interview Confirmed" if outcome.status == "confirmed" else "Interview Scheduling"

    details = ""
    if outcome.status == "confirmed" and outcome.scheduled_at:
        details = f"""
        <div class="details">
          <p><strong>Role:</strong> {outcome.job_title or ''}</p>
          <p><strong>Interviewer:</strong> {outcome.interviewer_name or ''}</p>
          <p><strong>Time:</strong> {format_ist_datetime(outcome.scheduled_at)}</p>
        </div>
        """

    links = ""
    if outcome.other_links:
        items = "\n".join(f'<li><a href="{link["url"]}">{link["label"]}</a></li>' for link in outcome.other_links)
        links = f'<ul class="links">{items}</ul>'

    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{heading}</title>
  <style>
    body {{ font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif; background: #f6f7f9;
            margin: 0; padding: 0; color: #1a1a1a; }}
    .card {{ max-width: 480px; margin: 64px auto; background: #ffffff; border-radius: 12px;
             padding: 32px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); text-align: center; }}
    h1 {{ font-size: 22px; color: {color}; margin-bottom: 12px; }}
    p {{ font-size: 15px; line-height: 1.5; color: #333333; }}
    .details {{ text-align: left; margin-top: 20px; padding-top: 16px; border-top: 1px solid #eeeeee; }}
    .details p {{ margin: 6px 0; }}
    .links {{ text-align: left; margin-top: 20px; padding: 0; list-style: none; }}
    .links li {{ margin: 10px 0; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>{heading}</h1>
    <p>{outcome.message}</p>
    {details}
    {links}
  </div>
</body>
</html>
"""


@router.get("/interview-negotiation/{token}", response_class=HTMLResponse)
def negotiate_interview_slot(token: str, db: Session = Depends(get_db)):
    outcome = handle_negotiation_click(db, token)
    return HTMLResponse(content=render_negotiation_page(outcome))
