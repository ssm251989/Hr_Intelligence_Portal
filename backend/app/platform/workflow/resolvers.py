"""Approver/assignee resolvers (docs/HRMS_COMPLETE_SPEC.txt Part 5B section 1's own list).
Each resolver spec is `{"type": <name>, ...params}`; `resolve(...)` returns the set of
user_ids it names for THIS instance's context. Only resolvers that mean something with
data this build actually has are implemented for real: `user` (a literal user_id),
`role-in-scope` (every user holding a role_assignment for a given role_id -- reuses
platform.iam's own tables), `expression` (JSONLogic against the instance context,
returning a user_id string or list), `skip-if-same-as-requester` (wraps another resolver,
drops the requester from its result), `auto-approve` (not a person at all -- a node-level
flag the engine checks directly, not something resolve() returns users for).

`manager(level n)`, `department_head`, `hrbp_of(employee)`, `position_holder` all need
Part 7's Core HR org model (employees, managers, departments, positions) to mean
anything -- same honest gap as platform.iam.authz's own org-hierarchy scope types.
resolve() raises ResolverNotSupportedError for these rather than silently resolving to
nobody (an approval node with zero resolved approvers would otherwise hang forever with
no way for anyone to act on it)."""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.iam import RoleAssignment
from app.platform.tenancy.context import TenantContext

_ORG_HIERARCHY_RESOLVERS = {"manager", "department_head", "hrbp_of", "position_holder"}


class ResolverNotSupportedError(Exception):
    pass


def resolve(db: Session, tenant: TenantContext, spec: dict, context: dict) -> set[UUID]:
    resolver_type = spec.get("type")

    if resolver_type == "user":
        return {UUID(spec["user_id"])}

    if resolver_type == "role-in-scope":
        role_id = UUID(spec["role_id"])
        rows = db.query(RoleAssignment).filter(RoleAssignment.tenant_id == tenant.tenant_id, RoleAssignment.role_id == role_id).all()
        return {row.user_id for row in rows}

    if resolver_type == "expression":
        from json_logic import jsonLogic

        result = jsonLogic(spec["jsonlogic"], context)
        if result is None:
            return set()
        values = result if isinstance(result, list) else [result]
        return {UUID(v) for v in values}

    if resolver_type == "skip-if-same-as-requester":
        inner = resolve(db, tenant, spec["resolver"], context)
        requester = context.get("started_by_user_id")
        if requester:
            inner.discard(UUID(requester))
        return inner

    if resolver_type in _ORG_HIERARCHY_RESOLVERS:
        raise ResolverNotSupportedError(f"This approval step picks the approver by {resolver_type.replace('_', ' ')}, which needs employee records (People). Choose a named person or a role instead.")

    raise ResolverNotSupportedError(f"Unknown approver resolver type: {resolver_type!r}")


def auto_approve_condition_met(spec: dict, context: dict) -> bool:
    """A node-level shortcut (section 1's own "auto-approve rule") -- checked by the
    engine BEFORE resolving any human approvers at all, so a matching rule skips the
    approval node entirely rather than creating a pending step nobody needs to act on."""
    condition = spec.get("auto_approve_condition")
    if condition is None:
        return False
    from json_logic import jsonLogic

    return bool(jsonLogic(condition, context))
