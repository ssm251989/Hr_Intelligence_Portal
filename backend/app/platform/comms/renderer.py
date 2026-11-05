"""Template rendering (docs/HRMS_COMPLETE_SPEC.txt Part 4 section 2): Jinja2
SandboxedEnvironment + StrictUndefined, so a template referencing an unset variable fails
loudly at render time rather than silently rendering "None" or an empty string into an
email a candidate/employee receives. Variables are validated against a template's own
variables_schema_json separately (validate_variables below) -- StrictUndefined alone only
catches a MISSING variable, not a wrong-shaped one.
"""

import html
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from jinja2.exceptions import TemplateError
from jinja2.sandbox import SandboxedEnvironment
from jinja2 import StrictUndefined


class TemplateRenderError(Exception):
    pass


class VariablesValidationError(Exception):
    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(f"Missing required template variables: {', '.join(missing)}")


def _filter_datetime(value: datetime, tz: str = "Asia/Kolkata", fmt: str = "%d %b %Y, %I:%M %p") -> str:
    if value.tzinfo is None:
        from datetime import timezone

        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo(tz)).strftime(fmt)


def _filter_currency(value: float, currency: str = "INR") -> str:
    symbols = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}
    symbol = symbols.get(currency, currency + " ")
    return f"{symbol}{value:,.2f}"


def _i18n_t(key: str, default: Optional[str] = None, **_kwargs) -> str:
    """Identity passthrough until Part 6's real i18n_overrides table exists -- returns
    `default` (or the key itself, so a template author immediately sees which key is
    unresolved rather than an empty string) never a lookup against tenant data yet."""
    return default if default is not None else key


def _button(url: str, label: str, color: Optional[str] = None) -> str:
    """A bulletproof table-based button (section 2's own requirement) -- the standard
    HTML-email pattern that survives Outlook's Word rendering engine, which mangles a
    plain <a> or <button> styled with CSS the way a normal browser would render.
    `url`/`label` are HTML-escaped -- this helper is marked safe below (it emits HTML
    itself), so anything interpolated INTO it must be escaped here, not left to the
    environment's own autoescaping (which only covers the template's own {{ }} output).
    `color` is a template's own {{ theme.primary_color }} (a tenant's real brand_theme
    row) -- the literal default below is only the no-color-passed-at-all scaffold
    fallback, never a specific tenant's brand."""
    safe_url = html.escape(url, quote=True)
    safe_label = html.escape(label)
    button_color = color or "#2563eb"  # allowlisted: generic no-theme-passed fallback
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr><td '
        f'style="border-radius:8px; background-color:{button_color};">'
        f'<a href="{safe_url}" target="_blank" '
        f'style="display:inline-block; padding:12px 24px; font-family:Arial,sans-serif; '
        f'font-size:14px; font-weight:700; color:#ffffff; text-decoration:none; border-radius:8px;">'
        f"{safe_label}</a></td></tr></table>"
    )


def _build_environment() -> SandboxedEnvironment:
    env = SandboxedEnvironment(undefined=StrictUndefined, autoescape=True)
    env.filters["datetime"] = _filter_datetime
    env.filters["currency"] = _filter_currency
    env.globals["t"] = _i18n_t
    env.globals["button"] = lambda url, label, color=None: _mark_safe(_button(url, label, color))
    return env


def _mark_safe(html_str: str):
    from markupsafe import Markup

    return Markup(html_str)


_ENV = _build_environment()


def render_string(template_str: str, context: dict) -> str:
    if not template_str:
        return ""
    try:
        return _ENV.from_string(template_str).render(**context)
    except TemplateError as exc:
        # Covers UndefinedError (a missing variable), TemplateSyntaxError (compiling a
        # malformed template -- from_string above, not just .render()), and the sandbox's
        # own SecurityError -- every one of these is a template-authoring mistake a
        # publish()/preview() caller needs turned into a clean, catchable error, not an
        # unhandled 500.
        raise TemplateRenderError(f"Template error: {exc}") from exc


def validate_variables(variables_schema: Optional[dict], context: dict) -> None:
    """Checked against variables_schema_json (section 2's own requirement) -- a minimal
    subset of JSON Schema (just "required"), not a full validator dependency, since every
    current template's schema is a flat list of required top-level variable names."""
    if not variables_schema:
        return
    required = variables_schema.get("required", [])
    missing = [key for key in required if key not in context]
    if missing:
        raise VariablesValidationError(missing)


def render_template(
    *, subject_tpl: Optional[str], html_tpl: Optional[str], text_tpl: Optional[str],
    variables_schema: Optional[dict], context: dict,
) -> dict:
    """Returns {"subject": str, "html": str, "text": str} -- text auto-derived from html
    (a crude tag-stripper) if text_tpl is empty, per section 2's own requirement, since
    every plain-text-only mail client (and every client that fails to render the HTML
    part) needs SOME text to show."""
    validate_variables(variables_schema, context)
    subject = render_string(subject_tpl or "", context)
    html_body = render_string(html_tpl or "", context)
    text_body = render_string(text_tpl, context) if text_tpl else _strip_tags(html_body)
    return {"subject": subject, "html": html_body, "text": text_body}


def _strip_tags(html_str: str) -> str:
    import re

    text = re.sub(r"<br\s*/?>", "\n", html_str, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()
