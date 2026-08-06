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
    created_by: Optional[uuid.UUID] = None
    created_at: datetime


# ---- publish-to-platforms (create-job wizard, final step) ----
#
# Naukri.com and LinkedIn have no real posting API access (no business
# partnership) -- checking those only records intent on the job_role, plus an
# optional URL the user pastes in after posting manually. Only
# "career_portal" actually flips job_roles.status, making the job appear on
# the public /careers site.


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
