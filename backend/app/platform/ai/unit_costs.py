"""Phase 0 unit costs: what AI costs per resume, per job and per hire.

Built only from ai_usage_records (each call's cost in ai.currency, already priced by
governance._cost) and what each record was for (`ai_subject(...)`):
- "candidate"   -- resume reading (candidates/router.py)
- "application" -- screening / ranking / documents (screening/service.py)
- "job"         -- JD drafting (jobs/router.py)

`compute()` is pure (plain rows in, a dict out) so it is tested without a database; the
API endpoint (experience/ui_genai_router.py GET /unit-costs) loads the rows and calls it.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Optional
from uuid import UUID

# The features that make up "handling one resume": reading it, scoring it, ranking it,
# explaining the shortlist decision.
RESUME_FEATURES = frozenset({"recruitment.resume_parsing", "recruitment.screening", "recruitment.ranking", "recruitment.shortlist_feedback"})

# An application that reached these has been hired (offer accepted and joining under way or done).
HIRED_STATUSES = ("onboarding_started", "onboarding_completed", "left_after_joining")


@dataclass(frozen=True)
class UsageRow:
    feature: Optional[str]
    cost: float
    tokens: int
    entity_type: Optional[str]
    entity_id: Optional[UUID]


@dataclass(frozen=True)
class AppRow:
    id: UUID
    job_id: Optional[UUID]
    candidate_id: Optional[UUID]
    status: Optional[str]


def _r(v: float) -> float:
    return round(v, 4)


def compute(usage: Iterable[UsageRow], applications: Iterable[AppRow], jobs: dict, hires_in_period: Optional[int] = None) -> dict:
    """`applications` = every application of the candidates/jobs that appear in `usage`;
    `jobs` = {job_id: title}. `hires_in_period` = applications that became hires in the
    window (None = count the hired applications among `applications`)."""
    usage, applications = list(usage), list(applications)
    apps = {a.id: a for a in applications}
    apps_of_candidate: dict = defaultdict(list)
    for a in applications:
        if a.candidate_id:
            apps_of_candidate[a.candidate_id].append(a)

    total = sum(u.cost for u in usage)
    job_cost: dict = defaultdict(float)
    resume_cost = 0.0
    resumes: set = set()
    unattributed = 0.0

    for u in usage:
        if u.feature in RESUME_FEATURES:
            if u.entity_type == "candidate" and u.entity_id:
                resume_cost += u.cost
                resumes.add(u.entity_id)
            elif u.entity_type == "application" and u.entity_id in apps:
                resume_cost += u.cost
                if apps[u.entity_id].candidate_id:
                    resumes.add(apps[u.entity_id].candidate_id)
        # cost per job: a candidate's resume reading is shared across the jobs they applied to
        if u.entity_type == "job" and u.entity_id:
            job_cost[u.entity_id] += u.cost
        elif u.entity_type == "application" and u.entity_id in apps and apps[u.entity_id].job_id:
            job_cost[apps[u.entity_id].job_id] += u.cost
        elif u.entity_type == "candidate" and apps_of_candidate.get(u.entity_id):
            share = u.cost / len(apps_of_candidate[u.entity_id])
            for a in apps_of_candidate[u.entity_id]:
                if a.job_id:
                    job_cost[a.job_id] += share
        else:
            unattributed += u.cost

    per_job_apps: dict = defaultdict(int)
    per_job_hires: dict = defaultdict(int)
    for a in applications:
        if a.job_id:
            per_job_apps[a.job_id] += 1
            if a.status in HIRED_STATUSES:
                per_job_hires[a.job_id] += 1

    rows = []
    for job_id, cost in job_cost.items():
        n_apps, n_hires = per_job_apps.get(job_id, 0), per_job_hires.get(job_id, 0)
        rows.append({"job_id": str(job_id), "title": jobs.get(job_id) or "—", "ai_cost": _r(cost), "applications": n_apps, "hires": n_hires,
                     "cost_per_application": _r(cost / n_apps) if n_apps else None, "cost_per_hire": _r(cost / n_hires) if n_hires else None})
    rows.sort(key=lambda r: -r["ai_cost"])

    hires = hires_in_period if hires_in_period is not None else sum(per_job_hires.values())
    return {
        "total_cost": _r(total),
        "unattributed_cost": _r(unattributed),
        "per_resume": {"resumes": len(resumes), "ai_cost": _r(resume_cost), "avg": _r(resume_cost / len(resumes)) if resumes else None},
        "per_job": {"jobs": len(rows), "avg": _r(sum(r["ai_cost"] for r in rows) / len(rows)) if rows else None, "rows": rows},
        "per_hire": {"hires": hires, "avg": _r(total / hires) if hires else None},
    }
