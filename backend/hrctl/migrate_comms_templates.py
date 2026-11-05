"""hrctl migrate-comms-templates (docs/HRMS_COMPLETE_SPEC.txt Part 4 section 5): seeds the
9 named templates as real, published, editable message_templates rows for tenant #1, and
tenant #1's own brand_theme (the navy->blue gradient, moved out of negotiation.py's own
hardcoded HTML per section 5's own instruction). Content matches
app/interview_scheduling/negotiation.py's current hardcoded builders exactly (parity
proven by tests/test_template_render_parity.py, not just eyeballed here) -- this script
is what those functions get DELETED in favor of, once negotiation.py itself is rewired to
render from these instead (see docs/build_log.md's own Part 4 note for the exact scope of
that rewire).

Usage: python -m hrctl.migrate_comms_templates [--dry-run]
"""

import argparse
import sys

from app.core.database import SessionLocal
from app.models.comms import BrandTheme, MessageTemplate
from app.platform.settings.bootstrap_definitions import register_all as register_settings_definitions
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import TENANT_1_ID, TenantContext, tenant_context

register_settings_definitions()

EMAIL_FONT_FAMILY = "-apple-system, Segoe UI, Roboto, Arial, sans-serif"

# Every field a negotiation-family email template needs from tenant #1's own brand_theme
# (section 5: "The navy->blue gradient moves into tenant #1's brand_theme") -- the exact
# values app/interview_scheduling/negotiation.py's _negotiation_email_html currently
# hardcodes.
_TENANT_1_THEME = {
    "name": "Default",
    "primary_color": "#1d5fd6",
    "secondary_color": "#0b1f4d",
    "gradient_from": "#0b1f4d",
    "gradient_to": "#1d5fd6",
    "font_family": EMAIL_FONT_FAMILY,
    "is_default": True,
}

_NEGOTIATION_SHELL_OPEN = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Interview Scheduling</title>
</head>
<body style="margin:0; padding:0; background-color:#eef1f6;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#eef1f6;">
<tr><td align="center" style="padding:32px 16px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px; width:100%; background-color:#ffffff; border-radius:12px;">
<tr>
<td bgcolor="{{ theme.primary_color }}" style="background-color:{{ theme.primary_color }}; background-image:linear-gradient(120deg, {{ theme.gradient_from }}, {{ theme.gradient_to }}); border-radius:12px 12px 0 0; padding:22px 32px;">
<table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td bgcolor="#5b7cff" style="width:30px; height:30px; border-radius:8px; background-color:#5b7cff; background-image:linear-gradient(135deg, #4f9dff, #7b5cff); font-size:0; line-height:0;">&nbsp;</td>
<td style="padding-left:10px; font-family:{{ theme.font_family }}; font-size:15px; font-weight:700; letter-spacing:0.04em; color:#f5f8ff;">{{ org.display_name|upper }}</td>
</tr></table>
</td>
</tr>
<tr>
<td style="padding:32px;">
"""

_NEGOTIATION_SHELL_CLOSE = """</td>
</tr>
<tr>
<td style="padding:16px 32px; background-color:#f6f8fc; border-top:1px solid #e6eaf3; border-radius:0 0 12px 12px; font-family:{{ theme.font_family }}; font-size:13px; color:#5b6478;">
This link expires in {{ token_expiry_days }} days.<br>
Need help? Reply to this email or contact your recruiter.
</td>
</tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def _negotiation_html(heading: str, body_copy: str) -> str:
    return (
        _NEGOTIATION_SHELL_OPEN
        + f'<h1 style="margin:0 0 12px; font-family:{{{{ theme.font_family }}}}; font-size:22px; font-weight:800; color:{{{{ theme.gradient_from }}}};">{heading}</h1>\n'
        + f'<p style="margin:0 0 26px; font-family:{{{{ theme.font_family }}}}; font-size:15px; line-height:1.6; color:#3a4257;">{body_copy}</p>\n'
        + "{{ button(picker_url, \"Choose Your Available Slots\", theme.primary_color) }}\n"
        + '<p style="margin:22px 0 0; font-family:{{ theme.font_family }}; font-size:12px; line-height:1.5; color:#8a93a6;">Or copy and paste this link into your browser:<br>\n'
        + '<a href="{{ picker_url }}" style="color:{{ theme.primary_color }}; word-break:break-all;">{{ picker_url }}</a></p>\n'
        + _NEGOTIATION_SHELL_CLOSE
    )


TEMPLATES = [
    {
        "key": "recruitment.negotiation.interviewer_offer",
        "subject_tpl": "Interview scheduling for {{ job_title }}",
        "text_tpl": (
            "Hi,\n\nWe'd like you to interview {{ candidate_name }} for the {{ job_title }} role, "
            "on {{ round_day }}. Please pick exactly {{ required_picks }} of the 3 time options that "
            "work for you:\n\n{{ picker_url }}\n\nThis link expires in {{ token_expiry_days }} days.\n\nThanks!"
        ),
        "html_tpl": _negotiation_html(
            "Hi,",
            'We\'d like you to interview <strong style="color:{{ theme.primary_color }};">{{ candidate_name }}</strong> '
            "for the {{ job_title }} role, on {{ round_day }}. Please pick exactly {{ required_picks }} of the 3 "
            "time options that work for you.",
        ),
        "variables_schema": {"required": ["candidate_name", "job_title", "round_day", "picker_url", "required_picks", "token_expiry_days"]},
    },
    {
        "key": "recruitment.negotiation.candidate_offer",
        "subject_tpl": "Interview scheduling for {{ job_title }}",
        "text_tpl": (
            "Hi {{ candidate_name }},\n\nWe'd like to schedule your interview for the {{ job_title }} position. "
            "Please pick exactly {{ required_picks }} of the 3 time options that work best for you:\n\n{{ picker_url }}\n\n"
            "This link expires in {{ token_expiry_days }} days. Thanks!"
        ),
        "html_tpl": _negotiation_html(
            "Hi {{ candidate_name }},",
            'We\'d like to schedule your interview for the <strong style="color:{{ theme.primary_color }};">{{ job_title }}</strong> '
            "position. Please pick exactly {{ required_picks }} of the 3 time options that work best for you.",
        ),
        "variables_schema": {"required": ["candidate_name", "job_title", "picker_url", "required_picks", "token_expiry_days"]},
    },
    {
        # Identical content to candidate_offer today -- a distinct template key (per
        # spec's own list) since the reprompt is a materially different moment
        # (the candidate's first 2 picks didn't overlap the interviewer's), even though
        # the wording happens to coincide right now. An admin can edit them independently
        # from here on.
        "key": "recruitment.negotiation.candidate_reprompt",
        "subject_tpl": "Interview scheduling for {{ job_title }}",
        "text_tpl": (
            "Hi {{ candidate_name }},\n\nWe'd like to schedule your interview for the {{ job_title }} position. "
            "Please pick exactly {{ required_picks }} of the 3 time options that work best for you:\n\n{{ picker_url }}\n\n"
            "This link expires in {{ token_expiry_days }} days. Thanks!"
        ),
        "html_tpl": _negotiation_html(
            "Hi {{ candidate_name }},",
            'We\'d like to schedule your interview for the <strong style="color:{{ theme.primary_color }};">{{ job_title }}</strong> '
            "position. Please pick exactly {{ required_picks }} of the 3 time options that work best for you.",
        ),
        "variables_schema": {"required": ["candidate_name", "job_title", "picker_url", "required_picks", "token_expiry_days"]},
    },
    {
        "key": "recruitment.interview.confirmation",
        "subject_tpl": "Interview confirmed: {{ job_title }}",
        "text_tpl": (
            "Hi,\n\nThis confirms the interview for {{ candidate_name }} for the {{ job_title }} role with "
            "{{ interviewer_name }}.\n\nDate/Time: {{ scheduled_at }}\nDuration: {{ duration_minutes }} minutes\n"
            "Mode: Video call (link in the attached calendar invite)\n\nA calendar invite is attached -- open it "
            "to add this to your calendar.\n\nThanks!"
        ),
        "html_tpl": None,  # matches current behavior exactly: plain-text only, .ics attached separately
        "variables_schema": {"required": ["candidate_name", "job_title", "interviewer_name", "scheduled_at", "duration_minutes"]},
    },
    # The remaining 5 (application received/rejected/shortlisted, offer.released,
    # system.password_reset/otp/welcome) have no current hardcoded equivalent anywhere in
    # this app to migrate FROM -- seeded here as real, generic, publishable starting
    # points instead (section 5's own "Seed as DEFAULT, generic, editable templates"),
    # ready for whichever later part actually triggers them.
    {
        "key": "recruitment.application.received",
        "subject_tpl": "We've received your application -- {{ job_title }}",
        "text_tpl": "Hi {{ candidate_name }},\n\nThanks for applying to {{ job_title }} at {{ org.display_name }}. We'll be in touch once your application has been reviewed.\n\nThanks!",
        "html_tpl": None,
        "variables_schema": {"required": ["candidate_name", "job_title"]},
    },
    {
        "key": "recruitment.application.rejected",
        "subject_tpl": "Update on your application -- {{ job_title }}",
        "text_tpl": "Hi {{ candidate_name }},\n\nThank you for your interest in the {{ job_title }} role at {{ org.display_name }}. After careful review, we won't be moving forward with your application at this time. We wish you the best in your search.\n\nThanks!",
        "html_tpl": None,
        "variables_schema": {"required": ["candidate_name", "job_title"]},
    },
    {
        "key": "recruitment.application.shortlisted",
        "subject_tpl": "You've been shortlisted -- {{ job_title }}",
        "text_tpl": "Hi {{ candidate_name }},\n\nGood news -- you've been shortlisted for the {{ job_title }} role at {{ org.display_name }}. We'll be reaching out shortly about next steps.\n\nThanks!",
        "html_tpl": None,
        "variables_schema": {"required": ["candidate_name", "job_title"]},
    },
    {
        "key": "recruitment.offer.released",
        "subject_tpl": "Your offer from {{ org.display_name }} -- {{ job_title }}",
        "text_tpl": "Hi {{ candidate_name }},\n\nWe're delighted to offer you the {{ job_title }} position at {{ org.display_name }}. Please review the attached offer letter.\n\nCongratulations!",
        "html_tpl": None,
        "variables_schema": {"required": ["candidate_name", "job_title"]},
    },
    {
        "key": "system.password_reset",
        "subject_tpl": "Reset your {{ org.display_name }} password",
        "text_tpl": "Hi,\n\nUse this link to reset your password:\n\n{{ reset_url }}\n\nIf you didn't request this, you can ignore this email.\n\nThanks!",
        "html_tpl": None,
        "variables_schema": {"required": ["reset_url"]},
    },
    {
        "key": "system.otp",
        "subject_tpl": "Your {{ org.display_name }} verification code",
        "text_tpl": "Hi,\n\nYour verification code is: {{ otp_code }}\n\nThis code expires in {{ expiry_minutes }} minutes.\n\nThanks!",
        "html_tpl": None,
        "variables_schema": {"required": ["otp_code", "expiry_minutes"]},
    },
    {
        "key": "system.welcome",
        "subject_tpl": "Welcome to {{ org.display_name }}",
        "text_tpl": "Hi {{ full_name }},\n\nWelcome to {{ org.display_name }}! Your account has been created.\n\nThanks!",
        "html_tpl": None,
        "variables_schema": {"required": ["full_name"]},
    },
]


def migrate(dry_run: bool) -> None:
    print("Migration plan:")
    print(f"  - brand_theme: {_TENANT_1_THEME['name']} (primary={_TENANT_1_THEME['primary_color']})")
    for t in TEMPLATES:
        print(f"  - message_template: {t['key']}")
    if dry_run:
        print("\n--dry-run: nothing written.")
        return

    with tenant_context(TENANT_1_ID):
        db = SessionLocal()
        try:
            theme = db.query(BrandTheme).filter(BrandTheme.is_default.is_(True)).first()
            if theme is None:
                theme = BrandTheme(tenant_id=TENANT_1_ID, **_TENANT_1_THEME)
                db.add(theme)
                db.commit()
                db.refresh(theme)
                print(f"Created brand_theme {theme.id}")
            else:
                print(f"brand_theme already exists ({theme.id}) -- left unchanged")

            for t in TEMPLATES:
                existing = (
                    db.query(MessageTemplate)
                    .filter(MessageTemplate.tenant_id == TENANT_1_ID, MessageTemplate.key == t["key"], MessageTemplate.channel == "email", MessageTemplate.locale == "en")
                    .order_by(MessageTemplate.version.desc())
                    .first()
                )
                if existing is not None:
                    print(f"  {t['key']}: already exists (v{existing.version}, {existing.status}) -- left unchanged")
                    continue
                from datetime import datetime, timezone

                row = MessageTemplate(
                    tenant_id=TENANT_1_ID, key=t["key"], channel="email", locale="en", version=1,
                    status="published", subject_tpl=t["subject_tpl"], html_tpl=t["html_tpl"], text_tpl=t["text_tpl"],
                    variables_schema_json=t["variables_schema"], published_by="hrctl", published_at=datetime.now(timezone.utc),
                )
                db.add(row)
                db.commit()
                print(f"  {t['key']}: created + published")

            print("\nMigrated successfully.")
        finally:
            db.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="hrctl migrate-comms-templates")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    migrate(args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
