import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

USER_ROLES = ("recruiter", "hiring_manager", "interviewer", "admin")


class UserRegister(BaseModel):
    email: str
    password: str = Field(min_length=8)
    full_name: Optional[str] = None
    role: Literal["recruiter", "hiring_manager", "interviewer", "admin"]


class UserLogin(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: Optional[str] = None
    role: str
    created_at: datetime
