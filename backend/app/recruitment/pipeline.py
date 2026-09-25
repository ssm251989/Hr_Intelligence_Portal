"""Configurable hiring pipeline (docs/HRMS_COMPLETE_SPEC.txt Part 8 section 1) --
`seed_default_template()` is this part's own TESTS requirement ("pipeline template
parity"): one stage per `Application.APPLICATION_STATUSES` value, in that tuple's own
order, so the seeded default template reproduces today's real lifecycle exactly.

**Scope decision** (docs/build_log.md's own Part 8 note): the pipeline_stages CRUD below
is real and tested, but `applications.status` transitions themselves are NOT retrofitted
onto these stages in this pass -- every existing screening/shortlisting/scheduling/salary/
bgv/offers router keeps writing `Application.status` exactly as it already does (the same
"don't retrofit onto every existing, already-tested router" discipline Part 5 applied to
authz and Part 7 applied to lifecycle events). A Kanban/list view generated from
`pipeline_stages` is real future work once a tenant wants to actually diverge from the
default template's stage set.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.application import APPLICATION_STATUSES
from app.models.pipeline import PipelineStage, PipelineTemplate
from app.platform.tenancy.context import TenantContext

DEFAULT_TEMPLATE_NAME = "Default Hiring Pipeline"

# code -> category. Every APPLICATION_STATUSES value is covered (order below matches that
# tuple's own order, which is already the real chronological flow). "on_hold" isn't a real
# lifecycle position (it's an orthogonal suspend-flag any application can carry -- see
# Application.previous_status) -- approximated as "withdrawn" (closer in spirit than
# "applied") rather than invented as a 10th category the CheckConstraint doesn't allow.
_STAGE_CATEGORY = {
    "received": "applied",
    "screened": "screening",
    "hr_selected": "screening",
    "hr_rejected": "rejected",
    "interview_scheduled": "interview",
    "interview_selected": "interview",
    "interview_rejected": "rejected",
    "salary_ok": "offer",
    "salary_above_band": "offer",
    "salary_approved": "offer",
    "salary_rejected": "rejected",
    "bgv_requested": "preboarding",
    "bgv_pending": "preboarding",
    "bgv_cleared": "preboarding",
    "bgv_rejected": "rejected",
    "offer_sent": "offer",
    "onboarding_started": "preboarding",
    "onboarding_completed": "hired",
    "on_hold": "withdrawn",
}


def seed_default_template(db: Session, tenant: TenantContext) -> PipelineTemplate:
    """Idempotent -- returns the existing default template unchanged if one already exists
    for this tenant (matched by `is_default`), never creates a second one."""
    existing = (
        db.query(PipelineTemplate)
        .filter(PipelineTemplate.tenant_id == tenant.tenant_id, PipelineTemplate.is_default.is_(True))
        .first()
    )
    if existing is not None:
        return existing

    template = PipelineTemplate(tenant_id=tenant.tenant_id, name=DEFAULT_TEMPLATE_NAME, is_default=True)
    db.add(template)
    db.flush()

    for order, code in enumerate(APPLICATION_STATUSES):
        db.add(PipelineStage(
            tenant_id=tenant.tenant_id, template_id=template.id, code=code,
            name_i18n={"en": code.replace("_", " ").title()}, order=order, category=_STAGE_CATEGORY[code],
        ))
    db.commit()
    db.refresh(template)
    return template


def list_templates(db: Session, tenant: TenantContext) -> list[PipelineTemplate]:
    return db.query(PipelineTemplate).filter(PipelineTemplate.tenant_id == tenant.tenant_id).order_by(PipelineTemplate.name).all()


def list_stages(db: Session, tenant: TenantContext, template_id: UUID) -> list[PipelineStage]:
    return (
        db.query(PipelineStage)
        .filter(PipelineStage.tenant_id == tenant.tenant_id, PipelineStage.template_id == template_id)
        .order_by(PipelineStage.order)
        .all()
    )


def create_template(db: Session, tenant: TenantContext, *, name: str, is_default: bool = False) -> PipelineTemplate:
    if is_default:
        db.query(PipelineTemplate).filter(PipelineTemplate.tenant_id == tenant.tenant_id, PipelineTemplate.is_default.is_(True)).update({"is_default": False})
    template = PipelineTemplate(tenant_id=tenant.tenant_id, name=name, is_default=is_default)
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def add_stage(
    db: Session, tenant: TenantContext, *, template_id: UUID, code: str, category: str, order: int,
    name_i18n: Optional[dict] = None, sla_days: Optional[int] = None, candidate_visible_name: Optional[str] = None,
) -> PipelineStage:
    stage = PipelineStage(
        tenant_id=tenant.tenant_id, template_id=template_id, code=code, category=category, order=order,
        name_i18n=name_i18n or {"en": code.replace("_", " ").title()}, sla_days=sla_days,
        candidate_visible_name=candidate_visible_name,
    )
    db.add(stage)
    db.commit()
    db.refresh(stage)
    return stage
