import uuid
from datetime import datetime
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


class JobRoleRead(JobRoleBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hiring_manager_id: Optional[uuid.UUID] = None
    jd_text: Optional[str] = None
    status: str
    created_by: Optional[uuid.UUID] = None
    created_at: datetime
