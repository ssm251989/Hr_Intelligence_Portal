"""Version history + revert for every versioned configurable object (docs/HRMS_COMPLETE_SPEC.txt
Part 14 section 7: "draft -> preview/simulate -> publish -> version history -> revert").

Templates, workflows, letters and prompts already carry (key, version, status). Revert never
edits history: it copies the chosen version into a NEW draft (latest + 1), which then goes
through the object's normal preview/simulate + publish path. Settings have their own
history/revert endpoint (platform/settings/router.py)."""

from sqlalchemy.orm import Session

from app.models.comms import MessageTemplate
from app.models.core_hr import LetterTemplate
from app.models.prompt import PromptTemplate
from app.models.workflow import WorkflowDefinition
from app.platform.tenancy.context import TenantContext

KINDS = {
    "message_template": (MessageTemplate, "platform.comms.configure"),
    "workflow_definition": (WorkflowDefinition, "workflow.definitions.configure"),
    "letter_template": (LetterTemplate, "core_hr.letter.edit"),
    "prompt_template": (PromptTemplate, "recruitment.prompt.configure"),
}
_NEVER_COPY = {"id", "tenant_id", "version", "status", "created_at", "published_at", "published_by", "created_by"}


class VersioningError(ValueError):
    pass


def _model(kind: str):
    if kind not in KINDS:
        raise VersioningError(f"unknown kind {kind!r}; one of {sorted(KINDS)}")
    return KINDS[kind][0]


def history(db: Session, tenant: TenantContext, kind: str, key: str) -> list[dict]:
    model = _model(kind)
    rows = db.query(model).filter(model.tenant_id == tenant.tenant_id, model.key == key).order_by(model.version.desc()).all()
    return [{"id": str(r.id), "version": r.version, "status": r.status,
             "created_at": r.created_at.isoformat() if getattr(r, "created_at", None) else None,
             "channel": getattr(r, "channel", None), "locale": getattr(r, "locale", None)} for r in rows]


def revert(db: Session, tenant: TenantContext, kind: str, key: str, version: int, *, actor: str) -> dict:
    model = _model(kind)
    source = db.query(model).filter(model.tenant_id == tenant.tenant_id, model.key == key, model.version == version).first()
    if source is None:
        raise VersioningError(f"{kind} {key!r} has no version {version}")
    query = db.query(model).filter(model.tenant_id == tenant.tenant_id, model.key == key)
    if hasattr(model, "channel"):  # message templates are versioned per channel + locale
        query = query.filter(model.channel == source.channel, model.locale == source.locale)
    latest = query.order_by(model.version.desc()).first()
    values = {c.key: getattr(source, c.key) for c in model.__table__.columns if c.key not in _NEVER_COPY and hasattr(source, c.key)}
    draft = model(tenant_id=tenant.tenant_id, **values)
    draft.version = latest.version + 1
    draft.status = "draft"
    if hasattr(draft, "created_by"):
        draft.created_by = f"{actor} (revert of v{version})"
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return {"id": str(draft.id), "version": draft.version, "status": draft.status, "reverted_from": version,
            "next_step": "preview/simulate, then publish the new draft"}
