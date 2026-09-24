"""hrctl seed-workflows (docs/HRMS_COMPLETE_SPEC.txt Part 5B section 5): seeds the 9 named
default workflow_definitions as real, published, editable rows for tenant #1 -- generic,
approver-role-driven (never a literal person), matching this build's own "seed ahead of
the module that will actually wire it up" pattern already established by Part 4's own
message_templates (recruitment.application.received/rejected/shortlisted, system.*) for
events no current code emits yet. None of these 9 workflows' own `trigger_json.event_type`
is actually raised by any real code today -- the entities they'd trigger on (requisitions,
assets, onboarding checklists, exit clearance, ...) belong to Parts 7-10, not built yet.
What IS real: every one of these definitions is a genuinely valid, engine-executable graph
(passes definitions.publish()'s own graph validation), and two of the nine
(asset_request, offer_approval) are exercised end-to-end by tests/test_workflow_engine.py-
style fixtures proving the mechanism, not just eyeballed here.

Usage: python -m hrctl.seed_workflows [--dry-run]
"""

import argparse
import sys

from app.core.database import SessionLocal
from app.platform.iam.roles import sync_system_roles
from app.platform.tenancy.context import TENANT_1_ID, TenantContext, tenant_context
from app.platform.workflow import definitions

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="ctd-techs", isolation="dedicated_db")


def _approval_node(role_id, *, on_approve="approved_end", on_reject="rejected_end", mode="quorum", quorum=1) -> dict:
    return {"type": "approval", "mode": mode, "quorum": quorum, "approvers": [{"type": "role-in-scope", "role_id": str(role_id)}], "on_approve": on_approve, "on_reject": on_reject}


def _single_gate_graph(role_id) -> dict:
    return {
        "start_node": "gate",
        "nodes": {
            "gate": _approval_node(role_id),
            "approved_end": {"type": "end", "outcome": "approved"},
            "rejected_end": {"type": "end", "outcome": "rejected"},
        },
    }


def _sequential_graph(first_role_id, second_role_id) -> dict:
    return {
        "start_node": "gate",
        "nodes": {
            "gate": {
                "type": "approval", "mode": "sequential",
                "approvers": [{"type": "role-in-scope", "role_id": str(first_role_id)}, {"type": "role-in-scope", "role_id": str(second_role_id)}],
                "on_approve": "approved_end", "on_reject": "rejected_end",
            },
            "approved_end": {"type": "end", "outcome": "approved"},
            "rejected_end": {"type": "end", "outcome": "rejected"},
        },
    }


def _parallel_task_graph(role_ids: list) -> dict:
    return {
        "start_node": "gate",
        "nodes": {
            "gate": {
                "type": "task", "mode": "parallel",
                "approvers": [{"type": "role-in-scope", "role_id": str(r)} for r in role_ids],
                "on_approve": "approved_end", "on_reject": "rejected_end",
            },
            "approved_end": {"type": "end", "outcome": "approved"},
            "rejected_end": {"type": "end", "outcome": "rejected"},
        },
    }


def _definitions(roles_by_name: dict) -> list[dict]:
    hm = roles_by_name["Hiring Manager"].id
    hr_admin = roles_by_name["HR Admin"].id
    hrbp = roles_by_name["HRBP"].id
    manager = roles_by_name["Manager"].id
    helpdesk = roles_by_name["Helpdesk Agent"].id

    return [
        {"key": "recruitment.job_requisition_approval", "name": "Job Requisition Approval", "module": "recruitment", "trigger": {"type": "event", "event_type": "recruitment.requisition.submitted"}, "graph": _single_gate_graph(hm)},
        {"key": "recruitment.offer_approval", "name": "Offer Approval", "module": "recruitment", "trigger": {"type": "event", "event_type": "recruitment.offer.submitted"}, "graph": _sequential_graph(hm, hr_admin)},
        {"key": "recruitment.bgv_decision", "name": "BGV Decision", "module": "recruitment", "trigger": {"type": "event", "event_type": "recruitment.bgv.completed"}, "graph": _single_gate_graph(hr_admin)},
        {"key": "helpdesk.asset_request", "name": "Asset Request", "module": "helpdesk", "trigger": {"type": "manual"}, "graph": _single_gate_graph(manager)},
        {"key": "onboarding.checklist", "name": "Onboarding Checklist", "module": "onboarding", "trigger": {"type": "event", "event_type": "onboarding.hire.created"}, "graph": _single_gate_graph(hr_admin)},
        {"key": "core_hr.probation_confirmation", "name": "Probation Confirmation", "module": "core_hr", "trigger": {"type": "date_relative", "entity_field": "probation_end", "offset_days": -15}, "graph": _single_gate_graph(hrbp)},
        {"key": "core_hr.transfer_promotion", "name": "Transfer / Promotion", "module": "core_hr", "trigger": {"type": "manual"}, "graph": _sequential_graph(manager, hr_admin)},
        {"key": "exit.resignation_clearance", "name": "Resignation & Clearance", "module": "exit", "trigger": {"type": "event", "event_type": "exit.resignation.submitted"}, "graph": _parallel_task_graph([helpdesk, hr_admin])},
        {"key": "core_hr.profile_change_approval", "name": "Profile Change Approval", "module": "core_hr", "trigger": {"type": "event", "event_type": "employee.profile_change.submitted"}, "graph": _single_gate_graph(hrbp)},
    ]


def seed(dry_run: bool) -> None:
    with tenant_context(TENANT_1_ID):
        db = SessionLocal()
        try:
            roles_by_name = sync_system_roles(db, TENANT)
            defs = _definitions(roles_by_name)

            print("Seed plan:")
            for d in defs:
                print(f"  - workflow_definition: {d['key']} ({d['name']})")
            if dry_run:
                print("\n--dry-run: nothing written.")
                return

            for d in defs:
                existing = (
                    db.query(definitions.WorkflowDefinition)
                    .filter(definitions.WorkflowDefinition.tenant_id == TENANT_1_ID, definitions.WorkflowDefinition.key == d["key"])
                    .order_by(definitions.WorkflowDefinition.version.desc())
                    .first()
                )
                if existing is not None:
                    print(f"  {d['key']}: already exists (v{existing.version}, {existing.status}) -- left unchanged")
                    continue
                draft = definitions.create_draft(db, TENANT_1_ID, key=d["key"], name=d["name"], module=d["module"], trigger=d["trigger"], graph=d["graph"])
                definitions.publish(db, draft, actor="hrctl")
                print(f"  {d['key']}: created + published")

            print("\nSeeded successfully.")
        finally:
            db.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    seed(args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
