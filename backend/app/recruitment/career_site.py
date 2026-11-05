"""CareerSite (docs/HRMS_COMPLETE_SPEC.txt Part 8 section 3): DPDP consent capture at
apply time, tenant-defined knockout questions per job, and JSON-LD structured data for the
public job detail page (Google Jobs indexing). The public jobs list/search/apply flow
itself already exists (`app/public/router.py`, `frontend/src/careers/`, Part 1's own
parity checklist row 13) -- this module adds the 3 concrete section-3 capabilities that
didn't exist yet, without rebuilding the portal itself.

**Scope decision**: self-scheduling, document upload, and offer view & e-sign on the
candidate portal (also section 3) are deferred -- self-scheduling needs the negotiation
flow's own candidate-facing token page (already real, just not reachable pre-apply from
the portal); document upload/offer e-sign belong to Part 9's pre-boarding portal, which
this build hasn't reached yet."""

from typing import Optional

CURRENT_CONSENT_VERSION = "v1"


def evaluate_knockout_questions(knockout_questions: list[dict], answers: dict) -> Optional[str]:
    """Returns a disqualification reason string if any knockout question's answer matches
    its own `disqualify_on` value, else None. `knockout_questions` is `JobRole.
    knockout_questions_json`: [{"question": str, "disqualify_on": str}]; `answers` maps
    question text -> the candidate's own answer, submitted alongside the application."""
    for question in knockout_questions:
        text = question.get("question")
        disqualify_on = question.get("disqualify_on")
        if text and disqualify_on is not None and answers.get(text) == disqualify_on:
            return f"Disqualified by knockout question: {text!r}"
    return None


def job_structured_data(job, org_display_name: str, base_url: str) -> dict:
    """A schema.org JobPosting JSON-LD payload (Google Jobs' own indexing format) for one
    published job -- section 3's own "SEO + Google Jobs structured data." Only the fields
    this app actually has real data for are populated; omitted fields are simply absent
    from the payload (schema.org tolerates a partial JobPosting)."""
    payload = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": job.title,
        "description": job.jd_text or job.key_responsibilities or job.title,
        "datePosted": job.created_at.date().isoformat() if job.created_at else None,
        "employmentType": job.job_type.upper().replace("-", "_") if job.job_type else None,
        "hiringOrganization": {"@type": "Organization", "name": org_display_name},
        "url": f"{base_url}/careers/jobs/{job.id}",
    }
    if job.location:
        payload["jobLocation"] = {"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": job.location}}
    if job.salary_band_min is not None and job.salary_band_max is not None:
        payload["baseSalary"] = {
            "@type": "MonetaryAmount",
            "value": {"@type": "QuantitativeValue", "minValue": float(job.salary_band_min), "maxValue": float(job.salary_band_max), "unitText": "YEAR"},
        }
    return {k: v for k, v in payload.items() if v is not None}
