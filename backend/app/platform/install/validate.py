"""Every value a person types during installation is checked here first.

Rules for passwords (the person chooses them, the app stores them):
- 10 to 128 characters, at least one letter and one digit;
- NO line breaks, tabs or other control characters (they broke .env files before), and no
  leading/trailing spaces (invisible, impossible to type again);
- not the same as the user name / email.
Any printable character is allowed otherwise (@ # : / % and spaces in the middle are fine:
envfile.py URL-encodes them).
"""

import re
from dataclasses import dataclass, field
from typing import Optional

PASSWORD_MIN = 10
PASSWORD_MAX = 128
_CONTROL = re.compile(r"[\x00-\x1f\x7f\u0085  ]")
_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}$")


class InvalidInput(ValueError):
    def __init__(self, problems: dict[str, str]):
        super().__init__("; ".join(f"{k}: {v}" for k, v in problems.items()))
        self.problems = problems


def password_problem(value: Optional[str], *, label: str = "Password", not_like: tuple[str, ...] = ()) -> Optional[str]:
    """None when fine, otherwise one plain sentence saying what to change."""
    if value is None or value == "":
        return f"{label} is required."
    if _CONTROL.search(value):
        return f"{label} must not contain line breaks, tabs or other invisible characters."
    if value != value.strip():
        return f"{label} must not start or end with a space."
    if len(value) < PASSWORD_MIN:
        return f"{label} must be at least {PASSWORD_MIN} characters."
    if len(value) > PASSWORD_MAX:
        return f"{label} must be at most {PASSWORD_MAX} characters."
    if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        return f"{label} must contain at least one letter and one digit."
    lowered = value.lower()
    for other in not_like:
        if other and (lowered == other.lower() or lowered == other.split("@")[0].lower()):
            return f"{label} must not be the same as the user name or email."
    return None


def text_problem(value: Optional[str], *, label: str, max_len: int = 120, required: bool = True) -> Optional[str]:
    if value is None or not value.strip():
        return f"{label} is required." if required else None
    if _CONTROL.search(value):
        return f"{label} must be on one line, without tabs or invisible characters."
    if len(value.strip()) > max_len:
        return f"{label} must be at most {max_len} characters."
    return None


@dataclass
class Answers:
    """What the installer asks. Defaults suit a single-machine install."""

    company_name: str
    company_slug: str
    admin_name: str
    admin_email: str
    admin_password: str
    pg_superuser_password: str  # the PostgreSQL 'postgres' password (chosen when PostgreSQL was installed)
    app_db_password: str  # password for the app's own login (hr_app); the person chooses it
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_superuser: str = "postgres"
    app_db_user: str = "hr_app"
    db_name: str = "hr_automation"
    control_plane_db_name: str = "hr_automation_control_plane"
    frontend_url: str = "http://localhost:5173"
    app_base_url: str = ""  # where the API is reached from outside, e.g. http://localhost:8080/_api (the Windows package)
    modules: list[str] = field(default_factory=list)  # empty = all
    activate_modules: bool = False
    new_postgres: bool = False  # True when the installer installed PostgreSQL with this password  # False = request activation from CTD Techs (normal); True = dev / CTD-internal

    @classmethod
    def from_dict(cls, data: dict) -> "Answers":
        known = {f for f in cls.__dataclass_fields__}
        unknown = sorted(set(data) - known)
        if unknown:
            raise InvalidInput({k: "Unknown setting." for k in unknown})
        try:
            return cls(**data)
        except TypeError as exc:
            raise InvalidInput({"answers": str(exc)}) from None


def check(a: Answers) -> None:
    """Raises InvalidInput with EVERY problem at once (so a form can mark all fields)."""
    p: dict[str, str] = {}

    def put(key, problem):
        if problem:
            p[key] = problem

    put("company_name", text_problem(a.company_name, label="Company name"))
    if not _SLUG.match(a.company_slug or ""):
        p["company_slug"] = "Short name: 1-40 lower-case letters, digits or '-', e.g. ctd-techs."
    put("admin_name", text_problem(a.admin_name, label="Your name"))
    if not _EMAIL.match((a.admin_email or "").strip()) or _CONTROL.search(a.admin_email or ""):
        p["admin_email"] = "Enter a valid email address, e.g. name@company.com."
    put("admin_password", password_problem(a.admin_password, label="Admin password", not_like=(a.admin_email,)))
    # The PostgreSQL password: the full rules when this installer sets it up (new_postgres),
    # otherwise it already exists -- only "one line, no outer spaces, not empty" applies.
    if a.new_postgres:
        put("pg_superuser_password", password_problem(a.pg_superuser_password, label="PostgreSQL password"))
    elif not a.pg_superuser_password or _CONTROL.search(a.pg_superuser_password) or a.pg_superuser_password != a.pg_superuser_password.strip():
        p["pg_superuser_password"] = "Enter the PostgreSQL password exactly, on one line, without spaces at the start or end."
    put("app_db_password", password_problem(a.app_db_password, label="App database password", not_like=(a.app_db_user,)))
    if a.app_db_password and a.app_db_password in (a.pg_superuser_password, a.admin_password):
        p["app_db_password"] = "Use a different password from the PostgreSQL and admin passwords."
    if not _HOST.match(a.pg_host or ""):
        p["pg_host"] = "Database server: a host name or IP address, e.g. localhost."
    if not isinstance(a.pg_port, int) or not 1 <= a.pg_port <= 65535:
        p["pg_port"] = "Port must be a number from 1 to 65535 (PostgreSQL uses 5432)."
    for key in ("pg_superuser", "app_db_user", "db_name", "control_plane_db_name"):
        if not _IDENT.match(getattr(a, key) or ""):
            p[key] = "Use lower-case letters, digits and _ only, starting with a letter (max 63)."
    if a.app_db_user == a.pg_superuser:
        p["app_db_user"] = "The app needs its own database login, not the PostgreSQL admin (security rules need it)."
    if a.db_name == a.control_plane_db_name:
        p["control_plane_db_name"] = "Must be different from the main database name."
    if not re.match(r"^https?://[^\s]+$", a.frontend_url or ""):
        p["frontend_url"] = "Address people open the app at, e.g. http://localhost:5173."
    if a.app_base_url and not re.match(r"^https?://[^\s]+$", a.app_base_url):
        p["app_base_url"] = "API address, e.g. http://localhost:8080/_api."
    if p:
        raise InvalidInput(p)
