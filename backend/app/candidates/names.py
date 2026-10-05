"""Fix 2026-10-05: a candidate's first / last / preferred name.

Resumes give one line ("Gunda Kishore"), and in many Indian names the family name comes first, so
"first word = first name" greets people by their surname. Nothing reliable can be guessed from the
name or the email address alone (gkishore@ and rkumar@ look alike but mean opposite things), so only
trusted sources are used, in this order:
1. what HR set on the profile (candidates.first_name / last_name / preferred_name);
2. the resume parser's given_name / family_name (it knows naming customs);
otherwise there is no first name and greetings use the full name -- never a guess.
(The joiner's own joining-details form wins over all of these on the welcome portal.)
"""

from typing import Optional


def _clean(v) -> str:
    return " ".join(str(v or "").split())


def names_of(cand) -> dict:
    """{"first_name", "last_name", "preferred_name", "source": "hr" | "resume" | "none"}"""
    preferred = _clean(getattr(cand, "preferred_name", None))
    first, last = _clean(getattr(cand, "first_name", None)), _clean(getattr(cand, "last_name", None))
    if first:
        return {"first_name": first, "last_name": last, "preferred_name": preferred, "source": "hr"}
    parsed = getattr(cand, "parsed_fields", None) or {}
    given, family = _clean(parsed.get("given_name")), _clean(parsed.get("family_name"))
    full = _clean(getattr(cand, "full_name", None)).lower()
    if given and given.lower() in full:  # only a name that really is part of the full name
        return {"first_name": given, "last_name": last or family, "preferred_name": preferred, "source": "resume"}
    return {"first_name": "", "last_name": last, "preferred_name": preferred, "source": "none"}


def given_name(cand) -> str:
    """What we call them: preferred name, else first name, else the full name ("" when there is none)."""
    if cand is None:
        return ""
    n = names_of(cand)
    return n["preferred_name"] or n["first_name"] or _clean(getattr(cand, "full_name", None)).replace("Demo - ", "")


def split_for_record(cand) -> tuple[str, Optional[str]]:
    """(first, last) for a pre-hire record: the trusted split, else the full name as the first name."""
    n = names_of(cand)
    if n["first_name"]:
        return n["first_name"], n["last_name"] or None
    return _clean(getattr(cand, "full_name", None)) or (getattr(cand, "email", None) or ""), None
