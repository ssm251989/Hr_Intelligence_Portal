"""Part 28.5 API: "Create your company" on the platform domain (no company / tenant yet - tenantless paths).

    GET  /api/v1/platform/signup/captcha            a new question (signed; 10 minutes)
    GET  /api/v1/platform/signup/slug?slug=acme     is <slug>.<PLATFORM_DOMAIN> free?
    POST /api/v1/platform/signup                    the form -> confirmation email (same answer for everyone)
    POST /api/v1/platform/signup/confirm            {token} -> the company is created in the background
    GET  /api/v1/platform/signup/status?token=      progress (confirmed -> provisioning -> waiting_approval -> active)
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.platform import signup
from app.platform.install.validate import InvalidInput

router = APIRouter(prefix="/api/v1/platform/signup", tags=["platform-signup"])


@router.get("/captcha")
def captcha():
    return signup.new_captcha()


@router.get("/modules")
def modules():
    """The modules a company can ask for (CTD Techs approves each request)."""
    from app.platform import module_registry as reg

    return [{"key": k, "name": reg.BY_KEY[k].name} for k in reg.CHOOSABLE]


@router.get("/slug")
def slug_check(slug: str):
    clean = (slug or "").strip().lower()
    return {"slug": clean, "host": signup.host_for(clean), "free": signup.slug_free(clean)}


class SignupIn(BaseModel):
    company_name: str = Field("", max_length=200)
    company_slug: str = Field("", max_length=63)
    admin_name: str = Field("", max_length=200)
    admin_email: str = Field("", max_length=255)
    password: str = Field("", max_length=200)
    password2: str = Field("", max_length=200)
    modules: list[str] = Field(default_factory=list)
    captcha_token: str = ""
    captcha_answer: str = ""


@router.post("")
def start(body: SignupIn, request: Request):
    try:
        return signup.start(company_name=body.company_name, company_slug=body.company_slug, admin_name=body.admin_name,
                            admin_email=body.admin_email, password=body.password, password2=body.password2, modules=body.modules,
                            captcha_token=body.captcha_token, captcha_answer=body.captcha_answer,
                            ip=request.client.host if request.client else None)
    except InvalidInput as exc:
        raise HTTPException(status_code=422, detail={"problems": exc.problems})
    except signup.SignupError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc), headers={"Retry-After": "3600"} if exc.status == 429 else None)


class ConfirmIn(BaseModel):
    token: str


@router.post("/confirm")
def confirm(body: ConfirmIn):
    try:
        return signup.confirm(body.token)
    except signup.SignupError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


@router.get("/status")
def status(token: str):
    try:
        return signup.status_by_token(token)
    except signup.SignupError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
