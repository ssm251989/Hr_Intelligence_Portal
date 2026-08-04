import uuid
from typing import Literal, Optional

from pydantic import BaseModel


class SalaryApprovalRequest(BaseModel):
    decision: Literal["approve", "reject"]
    approved_salary: Optional[float] = None
    notes: Optional[str] = None
    approved_by: Optional[str] = None


class SalaryStatusResponse(BaseModel):
    application_id: uuid.UUID
    status: str
    expected_salary: Optional[float] = None
    approved_salary: Optional[float] = None
    salary_band_min: Optional[float] = None
    salary_band_max: Optional[float] = None
