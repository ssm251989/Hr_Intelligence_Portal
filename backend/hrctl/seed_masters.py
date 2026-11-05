"""hrctl seed-masters (docs/HRMS_COMPLETE_SPEC.txt Part 6 section 3): registers all 25
master_types, then seeds a REPRESENTATIVE set of real master_values for the types this
app has genuine current data/usage for -- `source_of_hire` mirrors `Candidate.
CANDIDATE_SOURCES` exactly (the codes here match those constants 1:1) so the masters
catalog reflects the same reality the DB-level CheckConstraint already enforces.
**Deliberately does NOT remove that CheckConstraint or rewire candidates/router.py's
existing source validation onto masters** -- `source_of_hire` becomes real, editable
master DATA a tenant could add new source codes to, but the existing enum stays as a
defense-in-depth safety net on an already-tested, actively-used code path; swapping the
enforcement mechanism itself wasn't a requirement this part's own spec text named (unlike
Part 4's explicit "MIGRATE CURRENT EMAILS" instruction), so it's not attempted here. The
other seeded types (education_level, document_type, relationship, blood_group, notice_
period) are generic reference data with no current hardcoded equivalent to migrate FROM --
seeded ahead of whichever future part's forms actually consume them (Part 7's Employee
Master, Part 9's BGV), same "seed ahead of the real caller" pattern as several of this
build's own earlier parts.

Usage: python -m hrctl.seed_masters [--dry-run]
"""

import argparse
import sys

from app.core.database import SessionLocal
from app.models.metadata import MasterValue
from app.platform.metadata.masters import create_value, register_master_types
from app.platform.tenancy.context import TENANT_1_ID, TenantContext, tenant_context

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="ctd-techs", isolation="dedicated_db")

# type_code -> [(code, {"en": label}, sort), ...]
_SEED_VALUES = {
    # Mirrors app/models/candidate.py's own CANDIDATE_SOURCES constant exactly.
    "source_of_hire": [
        ("career_portal", "Career Portal", 1), ("manual", "Manually Added", 2), ("local_import", "Local Import", 3),
        ("linkedin", "LinkedIn", 4), ("naukri", "Naukri", 5), ("indeed", "Indeed", 6),
        ("monster", "Monster", 7), ("shine", "Shine", 8),
    ],
    "education_level": [
        ("any", "Any", 1), ("bachelors", "Bachelor's", 2), ("masters", "Master's", 3),
        ("phd", "PhD", 4), ("diploma", "Diploma", 5),
    ],
    "document_type": [
        ("pan", "PAN Card", 1), ("aadhaar", "Aadhaar", 2), ("passport", "Passport", 3),
        ("driving_licence", "Driving Licence", 4), ("degree_certificate", "Degree Certificate", 5),
    ],
    "relationship": [
        ("spouse", "Spouse", 1), ("parent", "Parent", 2), ("sibling", "Sibling", 3), ("child", "Child", 4),
    ],
    "blood_group": [(g, g, i) for i, g in enumerate(("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"), start=1)],
    "notice_period": [
        ("immediate", "Immediate", 1), ("15_days", "15 Days", 2), ("30_days", "30 Days", 3),
        ("60_days", "60 Days", 4), ("90_days", "90 Days", 5),
    ],
}


def seed(dry_run: bool) -> None:
    with tenant_context(TENANT_1_ID):
        db = SessionLocal()
        try:
            print("Seed plan: register all master_types, then values for:")
            for type_code, values in _SEED_VALUES.items():
                print(f"  - {type_code}: {len(values)} value(s)")
            if dry_run:
                print("\n--dry-run: nothing written.")
                return

            register_master_types(db)
            print("master_types registered.")

            for type_code, values in _SEED_VALUES.items():
                existing_codes = {
                    v.code for v in db.query(MasterValue).filter(MasterValue.tenant_id == TENANT_1_ID, MasterValue.type_code == type_code).all()
                }
                for code, label, sort in values:
                    if code in existing_codes:
                        continue
                    create_value(db, TENANT, type_code=type_code, code=code, label_i18n={"en": label}, sort=sort)
                print(f"  {type_code}: seeded (skipping any already-present codes)")

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
