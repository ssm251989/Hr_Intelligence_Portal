import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

USER_ROLES = ("recruiter", "hiring_manager", "interviewer", "admin")
PUBLIC_REGISTRABLE_ROLES = ("recruiter", "hiring_manager", "interviewer")


class UserRegister(BaseModel):
    email: str
    password: str = Field(min_length=8)
    full_name: Optional[str] = None
    role: Literal["recruiter", "hiring_manager", "interviewer"]


class AdminUserCreate(BaseModel):
    email: str
    password: str = Field(min_length=8)
    full_name: Optional[str] = None
    role: Literal["recruiter", "hiring_manager", "interviewer", "admin"]


class UserLogin(BaseModel):
    email: str
    password: str
    device_label: Optional[str] = None
    remember_device: bool = False


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: Optional[str] = None
    role: str
    created_at: datetime


class LoginResponse(BaseModel):
    """Either a real session (access_token/refresh_token set) or a step the client must
    complete first (mfa_required -> POST /auth/mfa/verify; mfa_enrollment_required -> the
    /auth/mfa/enroll/* endpoints, using mfa_enrollment_token as the Bearer credential)."""

    access_token: Optional[str] = None
    token_type: str = "bearer"
    refresh_token: Optional[str] = None
    device_id: Optional[uuid.UUID] = None
    mfa_required: bool = False
    mfa_challenge_id: Optional[uuid.UUID] = None
    mfa_methods: list[str] = []
    mfa_enrollment_required: bool = False
    mfa_enrollment_token: Optional[str] = None


class MfaVerifyRequest(BaseModel):
    challenge_id: uuid.UUID
    code: str
    remember_device: bool = False
    device_label: Optional[str] = None


class RefreshRequest(BaseModel):
    refresh_token: str


class TotpEnrollStartResponse(BaseModel):
    secret: str
    provisioning_uri: str


class TotpEnrollConfirmRequest(BaseModel):
    code: str


class TotpEnrollConfirmResponse(BaseModel):
    recovery_codes: list[str]


class DeviceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: Optional[str] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    last_seen_at: Optional[datetime] = None
    mfa_remembered_until: Optional[datetime] = None
