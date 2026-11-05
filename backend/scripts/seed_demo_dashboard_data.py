"""One-off script: seeds backdated demo data so the Jobs Dashboard sparklines show real
month-to-month variation instead of a flat line (all real data right now is from this
calendar month only).

Everything created here is labeled "Demo Seed" in job titles and candidate names --
filter on that prefix to find and delete it later (see the DELETE statements printed at
the end of this script's output). This goes straight to the DB on purpose: the normal API
endpoints stamp created_at at insert time and have no way to backdate an
onboarding_completed transition, but the dashboard's monthly trends read real historical
created_at / audit_log timestamps.

Run once from backend/: `.venv/Scripts/python.exe scripts/seed_demo_dashboard_data.py`
"""

import calendar
from datetime import datetime, timedelta, timezone

from app.core.database import SessionLocal
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.reports import stats

DEMO_PREFIX = "Demo Seed"
DEPARTMENTS = ["Engineering", "AI", "Automation Anywhere", "Sales"]
LOCATIONS = ["Hyderabad", "chennai", "kurnool", "Bangalore"]
STATUS_CYCLE = ["published", "published", "draft", "closed"]  # weighted toward published
APP_STATUS_CYCLE = ["received", "screened", "hr_selected", "interview_scheduled", "salary_ok", "offer_sent"]

# months back from "now" -> how many demo jobs to create that month (0 included on purpose)
JOB_PLAN = [(-8, 2), (-7, 0), (-6, 3), (-5, 1), (-4, 0), (-3, 2), (-2, 1), (-1, 3)]
# months back -> how many ordinary (non-hire) applications to create that month
APPLICATION_PLAN = [(-8, 2), (-7, 1), (-6, 4), (-5, 1), (-4, 1), (-3, 3), (-2, 2), (-1, 4)]
# offsets with 0 jobs planned above -- fall back to the nearest month that has one
JOB_FALLBACK = {-7: -8, -4: -5}
# (month the hire completed, time-to-hire in days) -- deliberately uneven across months
HIRE_PLAN = [(-6, 45), (-4, 30), (-4, 60), (-3, 50), (-1, 20), (-1, 40)]


def _month_boundary(offset: int) -> datetime:
    now = datetime.now(timezone.utc)
    return stats.shift_months(stats.month_start(now), offset)


def month_instant(offset: int, day: int = 15) -> datetime:
    """A timestamp safely inside the IST calendar month `offset` months from now."""
    return _month_boundary(offset) + timedelta(days=day - 1, hours=12)


def month_label(offset: int) -> str:
    ist = _month_boundary(offset) + stats._IST_OFFSET
    return f"{calendar.month_abbr[ist.month]} {ist.year}"


def main() -> None:
    db = SessionLocal()
    created_job_ids = []
    created_candidate_ids = []
    created_application_ids = []
    created_audit_ids = []

    try:
        jobs_by_offset: dict[int, list[JobRole]] = {}
        counter = 0
        for offset, count in JOB_PLAN:
            jobs_this_month = []
            for i in range(count):
                counter += 1
                job = JobRole(
                    title=f"{DEMO_PREFIX} - {month_label(offset)} - Role {i + 1}",
                    department=DEPARTMENTS[counter % len(DEPARTMENTS)],
                    location=LOCATIONS[counter % len(LOCATIONS)],
                    positions_count=1 + (counter % 3),
                    status=STATUS_CYCLE[counter % len(STATUS_CYCLE)],
                    created_at=month_instant(offset, day=5 + i * 3),
                )
                db.add(job)
                jobs_this_month.append(job)
            jobs_by_offset[offset] = jobs_this_month
        db.commit()
        for jobs in jobs_by_offset.values():
            for job in jobs:
                db.refresh(job)
                created_job_ids.append(job.id)
        print(f"Created {len(created_job_ids)} demo jobs.")

        def job_pool_for(offset: int) -> list[JobRole]:
            resolved = JOB_FALLBACK.get(offset, offset)
            return jobs_by_offset.get(resolved) or next(iter(jobs_by_offset.values()))

        counter = 0
        for offset, count in APPLICATION_PLAN:
            pool = job_pool_for(offset)
            for i in range(count):
                counter += 1
                created_at = month_instant(offset, day=6 + i * 5)
                candidate = Candidate(
                    full_name=f"{DEMO_PREFIX} Candidate - {month_label(offset)} #{i + 1}",
                    created_at=created_at,
                )
                db.add(candidate)
                db.commit()
                db.refresh(candidate)
                created_candidate_ids.append(candidate.id)

                application = Application(
                    job_role_id=pool[counter % len(pool)].id,
                    candidate_id=candidate.id,
                    status=APP_STATUS_CYCLE[counter % len(APP_STATUS_CYCLE)],
                    created_at=created_at,
                )
                db.add(application)
                db.commit()
                db.refresh(application)
                created_application_ids.append(application.id)
        print(f"Created {len(created_application_ids)} ordinary demo applications (with matching candidates).")

        for idx, (completion_offset, time_to_hire_days) in enumerate(HIRE_PLAN, start=1):
            completed_at = month_instant(completion_offset, day=20)
            created_at = completed_at - timedelta(days=time_to_hire_days)
            pool = job_pool_for(completion_offset)

            candidate = Candidate(
                full_name=f"{DEMO_PREFIX} Hire Candidate - {month_label(completion_offset)} #{idx}",
                created_at=created_at,
            )
            db.add(candidate)
            db.commit()
            db.refresh(candidate)
            created_candidate_ids.append(candidate.id)

            application = Application(
                job_role_id=pool[idx % len(pool)].id,
                candidate_id=candidate.id,
                status="onboarding_completed",
                created_at=created_at,
            )
            db.add(application)
            db.commit()
            db.refresh(application)
            created_application_ids.append(application.id)

            audit_entry = AuditLog(
                entity_type="application",
                entity_id=application.id,
                action="onboarding_completed",
                actor="demo-seed",
                created_at=completed_at,
            )
            db.add(audit_entry)
            db.commit()
            db.refresh(audit_entry)
            created_audit_ids.append(audit_entry.id)
            print(
                f"  Hire {idx}: completed {month_label(completion_offset)}, "
                f"time-to-hire {time_to_hire_days}d (applied {created_at.date()})"
            )
        print(f"Created {len(HIRE_PLAN)} backdated onboarding_completed hires.")

        print()
        print("=" * 70)
        print(f"Total: {len(created_job_ids)} jobs, {len(created_candidate_ids)} candidates, "
              f"{len(created_application_ids)} applications, {len(created_audit_ids)} audit entries.")
        print("All labeled with the prefix:", repr(DEMO_PREFIX))
        print()
        print("To remove this demo data later, run (in this order):")
        print(f"""
DELETE FROM audit_log WHERE entity_id IN (
  SELECT id FROM applications WHERE candidate_id IN (
    SELECT id FROM candidates WHERE full_name LIKE '{DEMO_PREFIX}%'
  )
);
DELETE FROM applications WHERE candidate_id IN (
  SELECT id FROM candidates WHERE full_name LIKE '{DEMO_PREFIX}%'
);
DELETE FROM candidates WHERE full_name LIKE '{DEMO_PREFIX}%';
DELETE FROM job_roles WHERE title LIKE '{DEMO_PREFIX}%';
""")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
