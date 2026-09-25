"""Permissions registry (docs/HRMS_COMPLETE_SPEC.txt Part 5A section 2): a code
`"<module>.<resource>.<action>"` a module declares, once, the same way Part 2's
SettingDef/Part 4's purpose registries work -- `register_permission()` here, `authz.py`
resolves a user's effective set against it.

**Not retrofitted onto every existing router in this pass** (see docs/build_log.md's own
Part 5 note): the existing `require_roles(...)` calls across ~19 routers stay exactly as
they are -- a real, already-tested access-control layer this part doesn't touch. What's
seeded below is a representative permission set covering the modules this build has
actually reached so far (jobs, candidates, interviews, offers, settings, connections,
comms, plus IAM/workflow's own new endpoints) -- proof the registry/authz mechanism is
real and correctly wired, not an exhaustive enumeration of all 13 modules' every action.
"""

from dataclasses import dataclass
from typing import Optional

ACTIONS = ("view", "create", "edit", "delete", "approve", "export", "view_sensitive", "configure")


@dataclass(frozen=True)
class PermissionDef:
    code: str  # "<module>.<resource>.<action>"
    module: str
    resource: str
    action: str
    label: str = ""

    def __post_init__(self):
        if self.action not in ACTIONS:
            raise ValueError(f"{self.code}: unknown action {self.action!r}")
        expected = f"{self.module}.{self.resource}.{self.action}"
        if self.code != expected:
            raise ValueError(f"{self.code}: code must equal '{expected}'")


_REGISTRY: dict[str, PermissionDef] = {}


def register_permission(module: str, resource: str, action: str, *, label: str = "") -> PermissionDef:
    code = f"{module}.{resource}.{action}"
    existing = _REGISTRY.get(code)
    if existing is not None:
        return existing
    definition = PermissionDef(code, module, resource, action, label=label)
    _REGISTRY[code] = definition
    return definition


def get_permission(code: str) -> Optional[PermissionDef]:
    return _REGISTRY.get(code)


def all_permissions() -> list[PermissionDef]:
    return sorted(_REGISTRY.values(), key=lambda p: p.code)


def is_registered(code: str) -> bool:
    return code in _REGISTRY


_registered = False


def register_all() -> None:
    """Idempotent, same pattern as platform.settings.bootstrap_definitions.register_all."""
    global _registered
    if _registered:
        return

    for module, resource in (
        ("recruitment", "job"), ("recruitment", "candidate"), ("recruitment", "application"),
        ("recruitment", "screening"), ("recruitment", "shortlisting"), ("recruitment", "interview"),
        ("recruitment", "offer"), ("recruitment", "bgv"), ("recruitment", "salary"),
    ):
        for action in ("view", "create", "edit", "delete", "export"):
            register_permission(module, resource, action)
    register_permission("recruitment", "offer", "approve")
    register_permission("recruitment", "bgv", "approve")
    register_permission("recruitment", "salary", "view_sensitive")

    register_permission("platform", "settings", "view")
    register_permission("platform", "settings", "configure")
    register_permission("platform", "connections", "view")
    register_permission("platform", "connections", "configure")
    register_permission("platform", "comms", "view")
    register_permission("platform", "comms", "configure")
    register_permission("platform", "users", "view")
    register_permission("platform", "users", "create")
    register_permission("platform", "users", "edit")

    register_permission("iam", "roles", "view")
    register_permission("iam", "roles", "configure")
    register_permission("iam", "role_assignments", "view")
    register_permission("iam", "role_assignments", "configure")
    register_permission("iam", "field_security", "view")
    register_permission("iam", "field_security", "configure")
    register_permission("iam", "delegations", "view")
    register_permission("iam", "delegations", "create")
    register_permission("iam", "access_review", "view")
    register_permission("iam", "impersonation", "create")

    register_permission("workflow", "definitions", "view")
    register_permission("workflow", "definitions", "configure")
    register_permission("workflow", "instances", "view")
    register_permission("workflow", "instances", "approve")
    register_permission("workflow", "instances", "edit")

    for resource in ("employee", "employment", "org", "letter", "import"):
        for action in ("view", "create", "edit", "delete"):
            register_permission("core_hr", resource, action)
    register_permission("core_hr", "employee", "view_sensitive")

    # Part 8: configurable pipeline, requisitions, interviewer availability, prompt
    # registry -- new resources under the already-registered "recruitment" module.
    register_permission("recruitment", "pipeline", "view")
    register_permission("recruitment", "pipeline", "configure")
    register_permission("recruitment", "requisition", "view")
    register_permission("recruitment", "requisition", "create")
    register_permission("recruitment", "requisition", "approve")
    register_permission("recruitment", "availability", "view")
    register_permission("recruitment", "availability", "configure")
    register_permission("recruitment", "prompt", "view")
    register_permission("recruitment", "prompt", "configure")

    # Part 9: pre-boarding & onboarding.
    for resource in ("preboarding", "plan", "task", "bgv", "assignment_rule"):
        for action in ("view", "create", "edit"):
            register_permission("onboarding", resource, action)
    register_permission("onboarding", "bgv", "approve")
    register_permission("onboarding", "preboarding", "approve")  # conversion to employee
    register_permission("onboarding", "plan", "configure")
    register_permission("onboarding", "assignment_rule", "configure")
    register_permission("onboarding", "dashboard", "view")

    # Part 10: performance, goals, compensation planning, succession.
    for resource in ("goal", "feedback", "one_on_one", "review", "cycle", "calibration", "talent", "succession", "marketplace"):
        for action in ("view", "create", "edit"):
            register_permission("performance", resource, action)
    register_permission("performance", "cycle", "configure")
    register_permission("performance", "calibration", "approve")
    register_permission("performance", "review", "view_sensitive")  # peer identities where the cycle allows HR to see them
    register_permission("performance", "self", "view")  # own goals/reviews/feedback via /me endpoints
    register_permission("performance", "self", "edit")
    for action in ("view", "create", "edit", "approve", "configure", "export", "view_sensitive"):
        register_permission("compensation", "planning", action)

    _registered = True
