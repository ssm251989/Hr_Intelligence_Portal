"""hrctl seed-pipeline (docs/HRMS_COMPLETE_SPEC.txt Part 8 section 1): seeds tenant #1's
default pipeline_template -- one stage per Application.APPLICATION_STATUSES value, proving
"pipeline template parity" for real, not just in tests. Idempotent (see
app.recruitment.pipeline.seed_default_template's own docstring).

Usage: python -m hrctl.seed_pipeline [--dry-run]
"""

import argparse
import sys

from app.core.database import SessionLocal
from app.models.application import APPLICATION_STATUSES
from app.platform.tenancy.context import TENANT_1_ID, TenantContext, tenant_context
from app.recruitment import pipeline

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="ctd-techs", isolation="dedicated_db")


def seed(dry_run: bool) -> None:
    with tenant_context(TENANT_1_ID):
        db = SessionLocal()
        try:
            print(f"Seed plan: default pipeline_template with {len(APPLICATION_STATUSES)} stages ({', '.join(APPLICATION_STATUSES)})")
            if dry_run:
                print("\n--dry-run: nothing written.")
                return

            template = pipeline.seed_default_template(db, TENANT)
            stages = pipeline.list_stages(db, TENANT, template.id)
            print(f"\nSeeded pipeline_template {template.id} ({template.name}) with {len(stages)} stages.")
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
