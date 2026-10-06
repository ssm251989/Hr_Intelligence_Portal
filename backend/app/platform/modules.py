"""Module registry (docs/HRMS_COMPLETE_SPEC.txt section F + Part 14 section 3).

One place that says, per module: its nav entry, the permission that makes it visible, and
the API path prefixes it owns. `/api/me/bootstrap` builds the menu from this (the frontend
never hard-codes a menu), and ModuleGateMiddleware returns 404 for the APIs of a module
that is switched off -- off in the control plane's `tenant_modules` (the licence) or in
the tenant's own `platform.modules.enabled` setting.

The original 13 recruitment screens stay under the always-on "recruitment" module so
existing parity is untouched.
"""

from dataclasses import dataclass, field
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


@dataclass(frozen=True)
class NavItem:
    label_key: str
    path: str
    permission: Optional[str] = None  # None = any signed-in user
    # Part 15.6: pages that serve both staff and self-service (e.g. Helpdesk) show when the
    # user holds ANY of these; used instead of `permission` when set.
    any_of: tuple[str, ...] = ()
    # Part 15.6: shown ONLY to users with this flat `users.role` (the agency portal), and such
    # users see nothing else -- an agency login is not a member of staff.
    only_flat_role: Optional[str] = None
    # Part 15 app shell: sidebar section (today/hiring/people/insights/admin) and the
    # Fluent emoji name shown beside the label.
    group: str = "today"
    icon: str = "house"
    # Part 20.4: hidden when the user holds this permission (e.g. "My interviews" for people without the full Interviews menu)
    unless: Optional[str] = None


@dataclass(frozen=True)
class ModuleDef:
    code: str
    nav: tuple[NavItem, ...]
    api_prefixes: tuple[str, ...] = field(default_factory=tuple)
    always_on: bool = False


MODULES: tuple[ModuleDef, ...] = (
    ModuleDef("home", (NavItem("nav.overview", "/", group="today", icon="house"),
                       NavItem("nav.approvals", "/approvals", group="today", icon="check"),
                       # Part 20.3: the employee's own profile, documents, assets, change requests
                       NavItem("nav.my_profile", "/me", any_of=("separation.self.view", "assets.self.view", "performance.self.view"), group="today", icon="id_card"),
                       # Part 20.4: an employee who interviews -- their interviews + availability only (HR has them under Interviews)
                       NavItem("nav.my_interviews", "/interviews/my", "recruitment.availability.view", group="today", icon="calendar",
                               unless="recruitment.interview.view")),
             always_on=True),
    # Part 20.3: every hiring item needs its own recruitment permission -- an Employee-only login saw them all before
    ModuleDef("recruitment", (
        NavItem("nav.jobs", "/jobs", "recruitment.job.view", group="hiring", icon="briefcase"),
        NavItem("nav.candidates", "/candidates/dashboard", "recruitment.candidate.view", group="hiring", icon="technologist"),
        NavItem("nav.screening", "/screening/dashboard", "recruitment.screening.view", group="hiring", icon="magnifier"),
        NavItem("nav.shortlisting", "/shortlisting/dashboard", "recruitment.shortlisting.view", group="hiring", icon="star"),
        NavItem("nav.interviews", "/interviews/dashboard", "recruitment.interview.view", group="hiring", icon="calendar"),
        NavItem("nav.hr_inbox", "/hr-inbox", "recruitment.candidate.view", group="hiring", icon="inbox"),
        NavItem("nav.salary", "/salary", "recruitment.salary.view", group="hiring", icon="money"),
        NavItem("nav.bgv", "/bgv", "recruitment.bgv.view", group="hiring", icon="shield"),
        NavItem("nav.offers", "/offers", "recruitment.offer.view", group="hiring", icon="envelope"),
        NavItem("nav.agencies", "/agencies", "recruitment.agency.view", group="hiring", icon="handshake"),
        NavItem("nav.agency_portal", "/agency", "agency.portal.view", group="today", icon="handshake", only_flat_role="agency"),
        # the original Reports page (13-module parity); the builder lives on it too
        NavItem("nav.reports", "/reports", any_of=("recruitment.job.view", "analytics.report.view"), group="insights", icon="bar_chart"),
    ), always_on=True),
    # Part 20.1: the Employees list -- always on (first in People; not the older People module below, which a company can hide)
    ModuleDef("employees", (NavItem("nav.employees", "/employees", "core_hr.employee.view", group="people", icon="id_card"),), always_on=True),
    ModuleDef("onboarding", (NavItem("nav.onboarding", "/onboarding", "onboarding.preboarding.view", group="people", icon="waving_hand"),),
              ("/api/v1/onboarding", "/api/v1/public/onboarding", "/api/v1/ui/onboarding", "/api/v1/public/ui/onboarding")),
    ModuleDef("core_hr", (
        # Part 17.9: one "People" entry (Directory for everyone, HR view inside for HR).
        NavItem("nav.people", "/people", group="people", icon="people"),
        NavItem("nav.org_chart", "/org-chart", "core_hr.org.view", group="people", icon="building"),
    ), ("/api/v1/ui/people",)),
    ModuleDef("performance", (
        NavItem("nav.performance", "/performance", any_of=("performance.goal.view", "performance.self.view", "performance.cycle.view"), group="people", icon="target"),
        NavItem("nav.compensation", "/compensation", "compensation.planning.view", group="people", icon="money"),
        NavItem("nav.succession", "/succession", "performance.succession.view", group="people", icon="trophy"),
    ), ("/api/v1/performance", "/api/v1/ui/performance")),
    ModuleDef("helpdesk", (NavItem("nav.helpdesk", "/helpdesk", any_of=("helpdesk.ticket.view", "helpdesk.self.view"), group="people", icon="ring_buoy"),),
              ("/api/v1/service-desk/tickets", "/api/v1/service-desk/me/tickets", "/api/v1/service-desk/kb", "/api/v1/service-desk/queues",
               "/api/v1/service-desk/sla-policies", "/api/v1/service-desk/calendars", "/api/v1/service-desk/assignment-rules", "/api/v1/service-desk/inbound")),
    ModuleDef("assets", (NavItem("nav.assets", "/assets", any_of=("assets.asset.view", "assets.self.view"), group="people", icon="laptop"),),
              ("/api/v1/service-desk/assets", "/api/v1/service-desk/allocations", "/api/v1/service-desk/asset-requests",
               "/api/v1/service-desk/me/assets", "/api/v1/service-desk/me/asset-requests", "/api/v1/service-desk/me/allocations")),
    ModuleDef("separation", (NavItem("nav.exits", "/exits", any_of=("separation.case.view", "separation.self.create"), group="people", icon="door"),),
              ("/api/v1/service-desk/separations", "/api/v1/service-desk/separations-export", "/api/v1/service-desk/clearance-items",
               "/api/v1/service-desk/me/resignation")),
    ModuleDef("analytics", (NavItem("nav.analytics", "/analytics", "analytics.report.view", group="insights", icon="chart_up"),),
              ("/api/v1/intelligence/datasets", "/api/v1/intelligence/reports", "/api/v1/intelligence/metrics",
               "/api/v1/intelligence/dashboards", "/api/v1/intelligence/predictive", "/api/v1/intelligence/warehouse-export", "/api/v1/ui/insights")),
    ModuleDef("copilot", (), ("/api/v1/intelligence/copilot",)),
    ModuleDef("settings", (NavItem("nav.genai_usage", "/genai-usage", "platform.settings.view", group="insights", icon="robot"),  # Part 18.24
                           NavItem("nav.setup", "/setup", "platform.settings.configure", group="admin", icon="rocket"),
                           NavItem("nav.settings", "/settings", "platform.settings.view", group="admin", icon="gear")), always_on=True),
)
_BY_CODE = {m.code: m for m in MODULES}


def enabled_modules(db, tenant) -> set[str]:
    """Always-on modules + those enabled in BOTH the licence (tenant_modules rows, if any
    exist for this tenant) and the tenant's own setting."""
    from app.platform.settings.resolver import SettingContext, SettingsService

    from app.platform import module_registry, module_status

    wanted = set(SettingsService(db).get("platform.modules.enabled", SettingContext(tenant=tenant)) or [])
    # Part 19.1: a module of the "Choose what you use" registry (onboarding) is on only when
    # it is active for the company (activation code), not through this setting
    wanted = {c for c in wanted if c not in module_registry.BY_KEY} | (module_status.active_modules(db, tenant) & set(_BY_CODE))
    licensed = _licensed_modules(tenant)
    return {m.code for m in MODULES if m.always_on or (m.code in wanted and (licensed is None or m.code in licensed))}


def _licensed_modules(tenant) -> Optional[set[str]]:
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
    from app.platform.tenancy.models_cp import TenantModule

    cp_db = ControlPlaneSessionLocal()
    try:
        rows = cp_db.query(TenantModule).filter(TenantModule.tenant_id == tenant.tenant_id).all()
    finally:
        cp_db.close()
    if not rows:
        return None  # no licence rows yet = unrestricted (MODE 1 before a licence is issued)
    return {r.module_code for r in rows if r.enabled}


def nav_for(db, tenant, user, permissions: set[str]) -> list[dict]:
    from app.platform import module_registry, module_status

    on = enabled_modules(db, tenant)
    active = module_status.active_modules(db, tenant)
    items = []
    for module in MODULES:
        if module.code not in on:
            continue
        for item in module.nav:
            if (item.only_flat_role or getattr(user, "role", None) == "agency") and item.only_flat_role != getattr(user, "role", None):
                continue
            allowed = any(p in permissions for p in item.any_of) if item.any_of else (item.permission is None or item.permission in permissions)
            if item.unless and item.unless in permissions:
                allowed = False
            key = module_registry.module_for_page(item.path)  # Part 19.1: hidden when its module isn't active
            if allowed and (key is None or key in active):
                items.append({"label_key": item.label_key, "path": item.path, "module": module.code, "group": item.group, "icon": item.icon,
                              "module_key": key})
    return items


def home_path(permissions: set[str]) -> str:
    """L-N2 role-based home: HR/recruiters land on the overview; an employee-only user on
    their approvals/tasks (pending items first, L-O1)."""
    if "agency.portal.view" in permissions and not any(p.startswith("recruitment.") for p in permissions):
        return "/agency"
    hr_like = any(p.startswith(("recruitment.", "core_hr.", "onboarding.", "helpdesk.ticket")) for p in permissions)
    return "/" if hr_like else "/approvals"


def module_for_path(path: str) -> Optional[str]:
    best = None
    for module in MODULES:
        for prefix in module.api_prefixes:
            if path.startswith(prefix) and (best is None or len(prefix) > len(best[1])):
                best = (module.code, prefix)
    return best[0] if best else None


class ModuleGateMiddleware(BaseHTTPMiddleware):
    """404 for the APIs of a disabled module (section F: 'Routers of disabled modules
    return 404')."""

    async def dispatch(self, request: Request, call_next):
        code = module_for_path(request.url.path)
        if code is not None:
            from app.core.database import SessionLocal
            from app.platform.tenancy.context import get_current_tenant

            tenant = get_current_tenant()
            if tenant is not None:
                db = SessionLocal()
                try:
                    on = enabled_modules(db, tenant)
                finally:
                    db.close()
                if code not in on:
                    return JSONResponse(status_code=404, content={"detail": {"code": "MODULE_DISABLED", "message": "This module isn't enabled for your organisation.",
                                                                              "fix_path": "/settings#modules"}})
        return await call_next(request)
