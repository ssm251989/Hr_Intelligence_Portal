"""Sanitizes a tenant-submitted custom CSS slot (docs/HRMS_COMPLETE_SPEC.txt Part 6
section 5) before it's ever stored on `brand_themes.custom_css` -- NOT a full CSS parser
(that's a much larger undertaking than this feature warrants), a targeted strip of the
specific constructs that turn "give an enterprise tenant a CSS override" into a real
injection vector once this string gets embedded inside a `<style>` tag on every visitor's
page:
  - `</style>`/`<script` (a breakout of the style tag itself, into raw HTML/script)
  - `@import` (loads an arbitrary external stylesheet -- effectively arbitrary CSS from
    a third party, plus a network fingerprinting vector)
  - `expression(...)` / `behavior:` (legacy IE JS-in-CSS constructs; still worth
    stripping since "which browsers a tenant's site visitors use" isn't this code's
    business to assume)
  - `javascript:`/`vbscript:` URLs inside `url(...)`
Never trust the RETURN VALUE of a previous sanitize as already-safe input to sanitize
again blindly -- `sanitize_css()` is idempotent (running it twice gives the same result
as running it once) specifically so a stored value can always be safely re-sanitized on
read, not just on write.
"""

import re

_DANGEROUS_PATTERNS = (
    re.compile(r"</style\s*>", re.IGNORECASE),
    re.compile(r"<script", re.IGNORECASE),
    re.compile(r"@import[^;]*;?", re.IGNORECASE),
    re.compile(r"expression\s*\([^)]*\)", re.IGNORECASE),
    re.compile(r"behavior\s*:[^;]*;?", re.IGNORECASE),
    re.compile(r"url\s*\(\s*['\"]?\s*(javascript|vbscript):[^)]*\)", re.IGNORECASE),
)

MAX_CUSTOM_CSS_LENGTH = 20_000


class CustomCssTooLargeError(Exception):
    pass


def sanitize_css(raw_css: str) -> str:
    if len(raw_css) > MAX_CUSTOM_CSS_LENGTH:
        raise CustomCssTooLargeError(f"Custom CSS exceeds {MAX_CUSTOM_CSS_LENGTH} characters")
    cleaned = raw_css
    for pattern in _DANGEROUS_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    return cleaned
