"""Prompt registry (docs/HRMS_COMPLETE_SPEC.txt Part 8 section 4) -- same versioned
draft->published lifecycle as Part 4's `message_templates`/Part 7's `letter_templates`.
`app/ai_services/candidate_ranker.py` is the one call site migrated onto this registry +
`ai.gateway.complete()` in this pass (see docs/build_log.md's own Part 8 note on why the
other 7 ai_services/*.py modules aren't migrated yet)."""

from typing import Optional

from sqlalchemy.orm import Session

from app.models.prompt import PromptTemplate
from app.platform.tenancy.context import TenantContext


class PromptNotFoundError(Exception):
    pass


def get_published_prompt(db: Session, tenant: TenantContext, key: str) -> PromptTemplate:
    prompt = (
        db.query(PromptTemplate)
        .filter(PromptTemplate.tenant_id == tenant.tenant_id, PromptTemplate.key == key, PromptTemplate.status == "published")
        .order_by(PromptTemplate.version.desc())
        .first()
    )
    if prompt is None:
        raise PromptNotFoundError(f"No published prompt_template for key: {key}")
    return prompt


def create_draft(
    db: Session, tenant: TenantContext, *, key: str, name: str, system_prompt: str,
    purpose: Optional[str] = None, variables_schema: Optional[dict] = None,
) -> PromptTemplate:
    latest = (
        db.query(PromptTemplate)
        .filter(PromptTemplate.tenant_id == tenant.tenant_id, PromptTemplate.key == key)
        .order_by(PromptTemplate.version.desc())
        .first()
    )
    prompt = PromptTemplate(
        tenant_id=tenant.tenant_id, key=key, name=name, version=(latest.version + 1) if latest else 1,
        status="draft", purpose=purpose, system_prompt=system_prompt, variables_schema_json=variables_schema or {},
    )
    db.add(prompt)
    db.commit()
    db.refresh(prompt)
    return prompt


def publish(db: Session, prompt: PromptTemplate) -> PromptTemplate:
    prompt.status = "published"
    db.commit()
    db.refresh(prompt)
    return prompt


def list_prompts(db: Session, tenant: TenantContext) -> list[PromptTemplate]:
    return db.query(PromptTemplate).filter(PromptTemplate.tenant_id == tenant.tenant_id).order_by(PromptTemplate.key, PromptTemplate.version.desc()).all()


def get_or_seed_published_prompt(db: Session, tenant: TenantContext, *, key: str, name: str, default_system_prompt: str, purpose: Optional[str] = None) -> PromptTemplate:
    """Used by a migrated ai_services call site instead of get_published_prompt directly:
    self-heals a tenant with no prompt_templates row yet for this key by seeding one from
    the call site's own CURRENT hardcoded prompt text (published immediately) -- so
    migrating a call site onto the registry never breaks a tenant that hasn't run
    hrctl.seed_prompts, and behavior is unchanged the very first time this runs."""
    try:
        return get_published_prompt(db, tenant, key)
    except PromptNotFoundError:
        draft = create_draft(db, tenant, key=key, name=name, system_prompt=default_system_prompt, purpose=purpose)
        return publish(db, draft)
