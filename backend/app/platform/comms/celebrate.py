"""Part 22.6: the designed emails -- selection / offer, welcome / joining, and relieving / experience.

Every other email keeps the plain company header (theme.wrap_email_html). These get their own layout:
- table-based, 600px, inline styles: renders in Gmail, Outlook (desktop shows the GIF's first frame -- the
  first frame carries the full title, so that IS the static fallback; "animated off" sends the PNG instead)
  and on phones;
- a banner (6 bundled GIFs, or the company's own upload), emoji in the subject and heading (switchable);
- offer: big "Review & sign your offer" button; welcome: first-day card (date, time, address + map link,
  who to meet, what to bring), team contacts with initials, buddy card; exit letters: warm and calm, no
  confetti, the PDFs attached.
The plain-text part is the template's own text (always sent alongside).
"""

import html as _html
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

BANNER_DIR = Path(__file__).resolve().parent / "banners"
BANNERS = {
    "confetti": "Confetti", "fireworks": "Fireworks", "balloons": "Balloons",
    "welcome-wave": "Welcome wave", "welcome-sparkle": "Welcome sparkle", "welcome-confetti": "Welcome confetti",
}
OFFER_KEYS = ("recruitment.offer_letter_auto", "recruitment.offer_resend", "recruitment.offer_revised")
WELCOME_KEYS = ("recruitment.welcome_selected",)
EXIT_KEYS = ("employee.exit_letters",)
KEYS = OFFER_KEYS + WELCOME_KEYS + EXIT_KEYS


def handles(template_key: str) -> bool:
    return template_key in KEYS


def _e(v) -> str:
    return _html.escape(str(v if v is not None else ""), quote=True)


def _setting(db: Session, tenant, key: str, default=None):
    from app.platform.settings.resolver import SettingContext, SettingsService

    try:
        v = SettingsService(db).get(key, SettingContext(tenant=tenant))
    except Exception:  # noqa: BLE001
        v = None
    return default if v in (None, "") else v


def banner_url(db: Session, tenant, choice: Optional[str], animated: bool = True) -> Optional[str]:
    from app.platform.links import public_base_url

    if not choice or choice == "none":
        return None
    if choice.startswith("custom:"):
        return f"{public_base_url()}/api/v1/public/media/email.banner.{choice[7:]}"
    if choice not in BANNERS:
        return None
    return f"{public_base_url()}/api/v1/public/email-banners/{choice}.{'gif' if animated else 'png'}"


def _initials(name: str) -> str:
    parts = [p for p in (name or "").replace(".", " ").split() if p[:1].isalpha()]
    return ((parts[0][:1] + (parts[-1][:1] if len(parts) > 1 else "")) or "?").upper()


def _button(href: str, label: str, colour: str) -> str:
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" style="margin:22px auto"><tr>'
            f'<td align="center" bgcolor="{colour}" style="border-radius:12px">'
            f'<a href="{_e(href)}" target="_blank" style="display:inline-block;padding:16px 34px;font:700 18px Arial,sans-serif;color:#ffffff;'
            f'text-decoration:none;border-radius:12px">{_e(label)}</a></td></tr></table>')


def _card(title: str, inner: str, tint: str = "#F4F7FB") -> str:
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:14px 0;background:{tint};border-radius:14px">'
            f'<tr><td style="padding:16px 18px;font:14px/1.5 Arial,sans-serif;color:#1f2937">'
            f'<div style="font:700 15px Arial,sans-serif;margin-bottom:8px">{title}</div>{inner}</td></tr></table>')


def _text_to_html(text: str) -> str:
    import re

    out = []
    for para in [p for p in re.split(r"\n\s*\n", text or "") if p.strip()]:
        safe = _e(para).replace("\n", "<br>")
        safe = re.sub(r"(https?://[^\s<]+)", r'<a href="\1" style="color:#1d4ed8">\1</a>', safe)
        out.append(f'<p style="margin:0 0 12px;font:15px/1.6 Arial,sans-serif;color:#1f2937">{safe}</p>')
    return "".join(out)


def _shell(db: Session, tenant, *, colour: str, banner: Optional[str], banner_alt: str, heading: str, inner: str) -> str:
    from app.platform.comms.theme import get_theme_and_org_context

    ctx = get_theme_and_org_context(db, tenant)
    name = _e(ctx["org"]["display_name"])
    logo = ctx["theme"]["logo_url"]
    brand = (f'<img src="{_e(logo)}" alt="{name}" height="40" style="max-height:40px;max-width:200px;border:0;display:block">' if logo
             else f'<span style="font:700 20px Arial,sans-serif;color:{colour}">{name}</span>')
    banner_html = (f'<tr><td style="padding:0"><img src="{_e(banner)}" alt="{_e(banner_alt)}" width="600" '
                   f'style="width:100%;max-width:600px;height:auto;display:block;border:0;border-radius:0"></td></tr>' if banner else "")
    return (
        '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="x-apple-disable-message-reformatting"></head>'
        '<body style="margin:0;padding:0;background:#eef2f7">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#eef2f7"><tr><td align="center" style="padding:20px 10px">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;background:#ffffff;border-radius:18px;overflow:hidden">'
        f'<tr><td style="padding:18px 24px;border-bottom:4px solid {colour}">{brand}</td></tr>'
        f'{banner_html}'
        f'<tr><td style="padding:26px 28px 8px"><h1 style="margin:0 0 14px;font:800 24px/1.3 Arial,sans-serif;color:{colour}">{heading}</h1>{inner}</td></tr>'
        f'<tr><td style="padding:16px 28px 24px;font:12px/1.5 Arial,sans-serif;color:#6b7280;border-top:1px solid #e5e7eb">{name} HR</td></tr>'
        '</table></td></tr></table></body></html>'
    )


def apply(db: Session, tenant, template_key: str, ctx: dict, rendered: dict) -> dict:
    """Subject with emoji + the designed HTML. The text part (rendered["text"]) is left as it is."""
    from app.platform.comms.theme import get_theme_and_org_context

    emoji = bool(_setting(db, tenant, "emails.emoji", True))
    animated = bool(_setting(db, tenant, "emails.animated", True))
    colour = _e(get_theme_and_org_context(db, tenant)["theme"]["primary_color"] or "#0E7C66")
    first = _e(ctx.get("candidate_first_name") or ctx.get("first_name") or "")
    company = _e(ctx.get("company_name") or "")
    subject = rendered.get("subject") or ""
    body_text = rendered.get("text") or ""

    if template_key in OFFER_KEYS:
        icon = "\U0001F389 " if emoji else ""  # party popper
        heading = f"{icon}Congratulations{', ' + first if first else ''}! You're selected"
        sign = ctx.get("sign_link")
        facts = "".join(f'<div><b>{label}:</b> {_e(v)}</div>' for label, v in (("Role", ctx.get("job_title")), ("Joining date", ctx.get("joining_date")),
                                                                                 ("Please sign by", ctx.get("expiry_date"))) if v)
        inner = (f'<p style="margin:0 0 12px;font:16px/1.6 Arial,sans-serif;color:#1f2937">We are thrilled to offer you '
                 f'{("the role of <b>" + _e(ctx.get("job_title")) + "</b>") if ctx.get("job_title") else "a role"} at {company}. Your offer letter is ready.</p>'
                 + (_card("Your offer at a glance", facts) if facts else "")
                 + (_button(sign, "Review & sign your offer", colour) if sign else "")
                 + '<div style="margin-top:8px">' + _text_to_html(body_text) + "</div>")
        html = _shell(db, tenant, colour=colour, banner=banner_url(db, tenant, _setting(db, tenant, "emails.banner_offer", "confetti"), animated),
                      banner_alt="Congratulations!", heading=heading, inner=inner)
        if emoji and not subject.startswith("\U0001F389"):
            subject = f"\U0001F389 {subject}"
        return {**rendered, "subject": subject, "html": html}

    if template_key in WELCOME_KEYS:
        icon = "\U0001F44B " if emoji else ""  # waving hand
        heading = f"{icon}Welcome to {company or 'the team'}{', ' + first if first else ''}!"
        day = ctx.get("day_one") or {}
        rows = []
        if ctx.get("joining_date"):
            rows.append(("\U0001F4C5" if emoji else "", "Date", _e(ctx["joining_date"])))
        if day.get("start_time"):
            rows.append(("⏰" if emoji else "", "Time", _e(day["start_time"])))
        if day.get("address"):
            addr = _e(day["address"]) + (f' &middot; <a href="{_e(day["map_url"])}" style="color:#1d4ed8">Open map</a>' if day.get("map_url") else "")
            rows.append(("\U0001F4CD" if emoji else "", "Where", addr))
        if day.get("meet"):
            rows.append(("\U0001F91D" if emoji else "", "Who to meet", _e(day["meet"])))
        if day.get("what_to_bring"):
            rows.append(("\U0001F392" if emoji else "", "What to bring", ", ".join(_e(x) for x in day["what_to_bring"])))
        first_day = "".join(f'<div style="margin:3px 0">{ic} <b>{k}:</b> {v}</div>' for ic, k, v in rows)
        people = ctx.get("people") or []
        team = "".join(
            f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:6px 0"><tr>'
            f'<td width="40" valign="top"><div style="width:36px;height:36px;border-radius:18px;background:{colour};color:#fff;font:700 14px/36px Arial,sans-serif;text-align:center">{_e(_initials(p.get("name", "")))}</div></td>'
            f'<td style="padding-left:10px;font:14px/1.4 Arial,sans-serif;color:#1f2937"><b>{_e(p.get("name"))}</b>{(" - " + _e(p.get("role"))) if p.get("role") else ""}<br>'
            f'<span style="color:#4b5563">{" &middot; ".join(_e(x) for x in (p.get("email"), p.get("phone")) if x)}</span></td></tr></table>'
            for p in people if p.get("name"))
        buddy = ctx.get("buddy") or {}
        buddy_html = (_card(("\U0001F91D " if emoji else "") + "Your buddy",
                            f'<b>{_e(buddy.get("name"))}</b>{(" - " + _e(buddy.get("role"))) if buddy.get("role") else ""}<br>'
                            f'<span style="color:#4b5563">{_e(buddy.get("email") or "")}</span><br>They will help you settle in during your first weeks.', "#FFF7E6")
                      if buddy.get("name") else "")
        steps = _text_to_html(ctx.get("steps") or "")
        inner = (f'<p style="margin:0 0 12px;font:16px/1.6 Arial,sans-serif;color:#1f2937">We are so happy you are joining us'
                 f'{(" as <b>" + _e(ctx.get("job_title")) + "</b>") if ctx.get("job_title") else ""}. Here is everything for a great start.</p>'
                 + (_card(("\U0001F680 " if emoji else "") + "Your first day", first_day, "#ECFDF5") if first_day else "")
                 + (_button(ctx["portal_link"], "Open your welcome portal", colour) if ctx.get("portal_link") else "")
                 + (_card(("✅ " if emoji else "") + "Your next steps", steps) if steps else "")
                 + (_card(("\U0001F465 " if emoji else "") + "Your team contacts", team) if team else "")
                 + buddy_html
                 + '<p style="margin:16px 0 0;font:15px/1.6 Arial,sans-serif;color:#1f2937">We can\'t wait to work with you!</p>')
        html = _shell(db, tenant, colour=colour, banner=banner_url(db, tenant, _setting(db, tenant, "emails.banner_welcome", "welcome-wave"), animated),
                      banner_alt="Welcome!", heading=heading, inner=inner)
        if emoji and not subject.startswith("\U0001F44B"):
            subject = f"\U0001F44B {subject}"
        return {**rendered, "subject": subject, "html": html}

    # relieving / experience: warm, professional, no confetti
    icon = "\U0001F64F " if emoji else ""  # folded hands
    heading = f"{icon}Thank you for your contributions{', ' + first if first else ''}"
    inner = (_text_to_html(body_text)
             + _card("Your letters", "Your relieving letter and experience certificate are attached as PDFs. Each has a QR code anyone can scan to check it is genuine.", "#F3F4F6"))
    html = _shell(db, tenant, colour=colour, banner=None, banner_alt="", heading=heading, inner=inner)
    if emoji and not subject.startswith("\U0001F64F"):
        subject = f"\U0001F64F {subject}"
    return {**rendered, "subject": subject, "html": html}
