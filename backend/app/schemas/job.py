import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class JobRoleBase(BaseModel):
    title: str
    department: Optional[str] = None
    location: Optional[str] = None
    experience_level: Optional[str] = None
    skills: Optional[list[str]] = None
    salary_band_min: Optional[float] = None
    salary_band_max: Optional[float] = None
    positions_count: int = 1
    benefits: Optional[str] = None
    additional_notes: Optional[str] = None
    # No application-level enum validation, same as `status` -- the DB CheckConstraint
    # (JOB_TYPES in app/models/job_role.py) is the one source of truth.
    job_type: str = "Full-time"


class JobRoleCreate(JobRoleBase):
    hiring_manager_id: Optional[uuid.UUID] = None
    created_by: Optional[uuid.UUID] = None


class JobRoleUpdate(BaseModel):
    title: Optional[str] = None
    department: Optional[str] = None
    location: Optional[str] = None
    experience_level: Optional[str] = None
    skills: Optional[list[str]] = None
    salary_band_min: Optional[float] = None
    salary_band_max: Optional[float] = None
    positions_count: Optional[int] = None
    status: Optional[str] = None
    job_type: Optional[str] = None
    jd_text: Optional[str] = None
    benefits: Optional[str] = None
    additional_notes: Optional[str] = None
    posting_url_naukri: Optional[str] = None
    posting_url_linkedin: Optional[str] = None


class JobRoleRead(JobRoleBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hiring_manager_id: Optional[uuid.UUID] = None
    jd_text: Optional[str] = None
    status: str
    published_platforms: dict = {}
    publish_settings: dict = {}
    posting_url_naukri: Optional[str] = None
    posting_url_linkedin: Optional[str] = None
    # Set only when a real LinkedIn post was created via the API (see
    # app/jobs/router.py _try_post_to_linkedin). Null means either LinkedIn wasn't
    # toggled on, the publishing user wasn't connected, or the post attempt failed --
    # in all of those cases posting_url_linkedin (manual fallback) is what's used instead.
    linkedin_post_urn: Optional[str] = None
    created_by: Optional[uuid.UUID] = None
    created_at: datetime
    # Computed per-job stats for the jobs list table (see app/jobs/router.py list_jobs) --
    # not real columns, so every other endpoint that returns a bare JobRole (create/update/
    # publish/hold/resume/generate-jd) just gets these defaults rather than a real number.
    application_count: int = 0
    applications_pct_change: Optional[float] = None
    avg_time_to_hire_days: Optional[float] = None


# ---- publish-to-platforms (create-job wizard, final step) ----
#
# Naukri.com has no real posting API access (no business partnership) -- checking
# it only records intent on the job_role, plus an optional URL the user pastes in
# after posting manually. LinkedIn is real when the publishing user has connected
# their account (see app/jobs/router.py _try_post_to_linkedin): a real post is
# created via the API instead of asking for a manual URL. "career_portal" is
# always real -- it's the one flag that flips job_roles.status, making the job
# appear on the public /careers site.


class PublishPlatformsRequest(BaseModel):
    naukri: bool = False
    linkedin: bool = False
    career_portal: bool = False
    posting_url_naukri: Optional[str] = None
    posting_url_linkedin: Optional[str] = None
    # "sync_to_ats" was removed -- it had no real effect and no path to one.
    # email_notifications is real when the publishing user has Google connected
    # (see app/jobs/router.py); application_deadline is enforced on read (see
    # app/jobs/service.py close_job_if_deadline_passed).
    email_notifications: bool = False
    application_deadline: Optional[date] = None


class JobFieldSuggestionsResponse(BaseModel):
    departments: list[str]
    locations: list[str]
    skills: list[str]
