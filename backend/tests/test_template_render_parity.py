"""Parity: the new message_templates render the SAME content the old hardcoded
app/interview_scheduling/negotiation.py builders used to (docs/HRMS_COMPLETE_SPEC.txt
Part 4 section 5's own explicit requirement: "render old vs new for the same fixture and
compare text content", before those old functions could be deleted -- they now are).

The "old" side below is a FROZEN, test-only copy of exactly what those now-deleted
functions returned -- not a live import (they no longer exist in negotiation.py, on
purpose: this is the regression test that keeps proving the new template-rendered output
never silently drifts from what a recipient used to see, not a one-time migration gate).
Plain-text bodies are compared byte-exact (trivial to keep exact -- no reason not to);
HTML is compared on its STRIPPED VISIBLE TEXT, not raw markup -- the new HTML uses
platform/comms/renderer.py's own button() helper (a real, reusable, slightly different
bulletproof-button markup) instead of the old function's own hand-written table, which a
byte-exact comparison would wrongly fail on despite a recipient seeing identical
information.
"""

import re
from datetime import date, datetime, timezone
from typing import Optional

from app.models.comms import MessageTemplate
from app.platform.comms.renderer import render_template
from app.platform.settings.bootstrap_definitions import register_all as register_settings_definitions
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

register_settings_definitions()

REQUIRED_PICKS = 2
TOKEN_EXPIRY_DAYS = 5


def _old_interviewer_email_body(candidate_name: Optional[str], job_title: str, round_day: date, picker_url: str) -> str:
    return (
        f"Hi,\n\n"
        f"We'd like you to interview {candidate_name or 'a candidate'} for the {job_title} role, "
        f"on {round_day.strftime('%d %b %Y')}. Please pick exactly {REQUIRED_PICKS} of the 3 time "
        f"options that work for you:\n\n{picker_url}\n\n"
        f"This link expires in {TOKEN_EXPIRY_DAYS} days.\n\nThanks!"
    )


def _old_candidate_email_body(candidate_name: Optional[str], job_title: str, picker_url: str) -> str:
    return (
        f"Hi {candidate_name or 'there'},\n\n"
        f"We'd like to schedule your interview for the {job_title} position. Please pick exactly "
        f"{REQUIRED_PICKS} of the 3 time options that work best for you:\n\n{picker_url}\n\n"
        f"This link expires in {TOKEN_EXPIRY_DAYS} days. Thanks!"
    )


def _old_confirmation_email_body(candidate_name: Optional[str], job_title: str, interviewer_name: Optional[str], scheduled_at_formatted: str, duration_minutes: int) -> str:
    return (
        f"Hi,\n\n"
        f"This confirms the interview for {candidate_name or 'the candidate'} for the {job_title} "
        f"role with {interviewer_name or 'the interviewer'}.\n\n"
        f"Date/Time: {scheduled_at_formatted}\n"
        f"Duration: {duration_minutes} minutes\n"
        f"Mode: Video call (link in the attached calendar invite)\n\n"
        f"A calendar invite is attached -- open it to add this to your calendar.\n\nThanks!"
    )


# Visible text only, from the old hand-written HTML shell -- <title> + header wordmark +
# heading + body copy + the CTA button's own label + footer, exactly what
# _strip_tags(new_html) below is compared against (the <title> tag and the logo cell's
# &nbsp; both leave visible TEXT behind even once their own tags are stripped, same as the
# new template's shell does -- this must include them too, or the comparison is comparing
# two different scopes of "visible text", not a real parity check).
_OLD_HEADER_TEXT = "Interview Scheduling &nbsp; CTD TECHS"
_OLD_FOOTER_TEXT = f"This link expires in {TOKEN_EXPIRY_DAYS} days. Need help? Reply to this email or contact your recruiter."


def _old_interviewer_email_visible_text(candidate_name: str, job_title: str, round_day: date) -> str:
    date_str = round_day.strftime("%d %b %Y")
    return (
        f"{_OLD_HEADER_TEXT} Hi, We'd like you to interview {candidate_name} for the {job_title} role, on {date_str}. "
        f"Please pick exactly {REQUIRED_PICKS} of the 3 time options that work for you. "
        f"Choose Your Available Slots Or copy and paste this link into your browser: {{picker_url}} {_OLD_FOOTER_TEXT}"
    )


def _old_candidate_email_visible_text(candidate_name: str, job_title: str) -> str:
    return (
        f"{_OLD_HEADER_TEXT} Hi {candidate_name}, We'd like to schedule your interview for the {job_title} position. "
        f"Please pick exactly {REQUIRED_PICKS} of the 3 time options that work best for you. "
        f"Choose Your Available Slots Or copy and paste this link into your browser: {{picker_url}} {_OLD_FOOTER_TEXT}"
    )


def _strip_tags(html_str: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", html_str, flags=re.IGNORECASE)
    text = re.sub(r"</p>|</h1>", " ", html_str, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _get_template(db_session, key: str) -> MessageTemplate:
    template = (
        db_session.query(MessageTemplate)
        .filter(MessageTemplate.tenant_id == TENANT_1_ID, MessageTemplate.key == key, MessageTemplate.status == "published")
        .order_by(MessageTemplate.version.desc())
        .first()
    )
    assert template is not None, f"{key}: run hrctl.migrate_comms_templates first"
    return template


def _theme_and_org_context(db_session) -> dict:
    from app.models.comms import BrandTheme

    theme = db_session.query(BrandTheme).filter(BrandTheme.tenant_id == TENANT_1_ID, BrandTheme.is_default.is_(True)).first()
    service = SettingsService(db_session)
    ctx = SettingContext(tenant=TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db"))
    org_display_name = service.get("org.display_name", ctx) or "CTD Techs"
    return {
        "theme": {
            "primary_color": theme.primary_color, "gradient_from": theme.gradient_from,
            "gradient_to": theme.gradient_to, "font_family": theme.font_family,
        },
        "org": {"display_name": org_display_name},
    }


def test_interviewer_offer_template_matches_the_old_builder(db_session):
    template = _get_template(db_session, "recruitment.negotiation.interviewer_offer")
    candidate_name, job_title, round_day, picker_url = "Jane Doe", "Backend Engineer", date(2026, 10, 5), "https://example.com/pick/abc"

    old_text = _old_interviewer_email_body(candidate_name, job_title, round_day, picker_url)

    ctx = {
        "candidate_name": candidate_name, "job_title": job_title, "round_day": round_day.strftime("%d %b %Y"),
        "picker_url": picker_url, "required_picks": REQUIRED_PICKS, "token_expiry_days": TOKEN_EXPIRY_DAYS,
        **_theme_and_org_context(db_session),
    }
    rendered = render_template(subject_tpl=template.subject_tpl, html_tpl=template.html_tpl, text_tpl=template.text_tpl, variables_schema=template.variables_schema_json, context=ctx)

    assert rendered["text"] == old_text
    expected_visible = _old_interviewer_email_visible_text(candidate_name, job_title, round_day).replace("{picker_url}", picker_url)
    assert _strip_tags(rendered["html"]) == expected_visible


def test_candidate_offer_template_matches_the_old_builder(db_session):
    template = _get_template(db_session, "recruitment.negotiation.candidate_offer")
    candidate_name, job_title, picker_url = "Jane Doe", "Backend Engineer", "https://example.com/pick/xyz"

    old_text = _old_candidate_email_body(candidate_name, job_title, picker_url)

    ctx = {
        "candidate_name": candidate_name, "job_title": job_title, "picker_url": picker_url,
        "required_picks": REQUIRED_PICKS, "token_expiry_days": TOKEN_EXPIRY_DAYS,
        **_theme_and_org_context(db_session),
    }
    rendered = render_template(subject_tpl=template.subject_tpl, html_tpl=template.html_tpl, text_tpl=template.text_tpl, variables_schema=template.variables_schema_json, context=ctx)

    assert rendered["text"] == old_text
    expected_visible = _old_candidate_email_visible_text(candidate_name, job_title).replace("{picker_url}", picker_url)
    assert _strip_tags(rendered["html"]) == expected_visible


def test_candidate_reprompt_template_matches_the_old_builder(db_session):
    """The reprompt path reused the exact same old builder functions as the first offer
    (see negotiation.py's own history, _reprompt_candidate) -- so its parity check is
    against the same frozen reference text, just rendered through the DIFFERENT
    (candidate_reprompt) template key."""
    template = _get_template(db_session, "recruitment.negotiation.candidate_reprompt")
    candidate_name, job_title, picker_url = "Jane Doe", "Backend Engineer", "https://example.com/pick/reprompt"

    old_text = _old_candidate_email_body(candidate_name, job_title, picker_url)

    ctx = {
        "candidate_name": candidate_name, "job_title": job_title, "picker_url": picker_url,
        "required_picks": REQUIRED_PICKS, "token_expiry_days": TOKEN_EXPIRY_DAYS,
        **_theme_and_org_context(db_session),
    }
    rendered = render_template(subject_tpl=template.subject_tpl, html_tpl=template.html_tpl, text_tpl=template.text_tpl, variables_schema=template.variables_schema_json, context=ctx)

    assert rendered["text"] == old_text
    expected_visible = _old_candidate_email_visible_text(candidate_name, job_title).replace("{picker_url}", picker_url)
    assert _strip_tags(rendered["html"]) == expected_visible


def test_interview_confirmation_template_matches_the_old_builder(db_session):
    from app.integrations.google_calendar import format_ist_datetime

    template = _get_template(db_session, "recruitment.interview.confirmation")
    chosen_time = datetime(2026, 10, 6, 10, 30, tzinfo=timezone.utc)
    scheduled_at_formatted = format_ist_datetime(chosen_time)

    old_text = _old_confirmation_email_body("Jane Doe", "Backend Engineer", "Kishore", scheduled_at_formatted, 60)

    ctx = {
        "candidate_name": "Jane Doe", "job_title": "Backend Engineer", "interviewer_name": "Kishore",
        "scheduled_at": scheduled_at_formatted, "duration_minutes": 60,
    }
    rendered = render_template(subject_tpl=template.subject_tpl, html_tpl=template.html_tpl, text_tpl=template.text_tpl, variables_schema=template.variables_schema_json, context=ctx)

    assert rendered["text"] == old_text


def test_subjects_match_the_old_hardcoded_f_strings(db_session):
    interviewer_tpl = _get_template(db_session, "recruitment.negotiation.interviewer_offer")
    candidate_tpl = _get_template(db_session, "recruitment.negotiation.candidate_offer")
    confirmation_tpl = _get_template(db_session, "recruitment.interview.confirmation")

    job_title = "Backend Engineer"
    assert render_template(subject_tpl=interviewer_tpl.subject_tpl, html_tpl=None, text_tpl="x", variables_schema=None, context={"job_title": job_title})["subject"] == f"Interview scheduling for {job_title}"
    assert render_template(subject_tpl=candidate_tpl.subject_tpl, html_tpl=None, text_tpl="x", variables_schema=None, context={"job_title": job_title})["subject"] == f"Interview scheduling for {job_title}"
    assert render_template(subject_tpl=confirmation_tpl.subject_tpl, html_tpl=None, text_tpl="x", variables_schema=None, context={"job_title": job_title})["subject"] == f"Interview confirmed: {job_title}"
