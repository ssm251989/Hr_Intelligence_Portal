from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.integrations.google_calendar import format_ist_datetime
from app.interview_scheduling.confirmation import ConfirmationOutcome, confirm_token

# No prefix, no auth -- this is the exact link a candidate clicks from their email, so it
# has to be reachable directly (same "public, no-auth" pattern as app/public/router.py's
# Career Portal endpoints). Registered at the bare path in app/main.py.
router = APIRouter(tags=["interview-confirmation"])

_STATUS_COLORS = {
    "confirmed": "#1b8a5a",
    "used": "#b8860b",
    "invalidated": "#b8860b",
    "expired": "#b8860b",
    "invalid": "#b23b3b",
}


def render_confirmation_page(outcome: ConfirmationOutcome) -> str:
    """A small, self-contained HTML page -- no build step, no JS -- since this is the last
    stop for a candidate coming straight from an email link, not part of the recruiter-
    facing SPA."""
    color = _STATUS_COLORS.get(outcome.status, "#b23b3b")
    heading = "Interview Confirmed" if outcome.status == "confirmed" else "Interview Scheduling"

    details = ""
    if outcome.status == "confirmed":
        details = f"""
        <div class="details">
          <p><strong>Role:</strong> {outcome.job_title or ''}</p>
          <p><strong>Interviewer:</strong> {outcome.interviewer_name or ''}</p>
          <p><strong>Time:</strong> {format_ist_datetime(outcome.scheduled_at) if outcome.scheduled_at else ''}</p>
        </div>
        """

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
  </style>
</head>
<body>
  <div class="card">
    <h1>{heading}</h1>
    <p>{outcome.message}</p>
    {details}
  </div>
</body>
</html>
"""


@router.get("/interview-confirm/{token}", response_class=HTMLResponse)
def confirm_interview_slot(token: str, db: Session = Depends(get_db)):
    outcome = confirm_token(db, token)
    return HTMLResponse(content=render_confirmation_page(outcome))
