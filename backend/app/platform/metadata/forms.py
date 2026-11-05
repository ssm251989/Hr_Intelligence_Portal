"""Form layouts + free-standing forms (docs/HRMS_COMPLETE_SPEC.txt Part 6 section 2).
`get_effective_layout()` merges a `form_layouts` row's own `sections_json` with that
entity's active `custom_field_defs` -- the shape `<DynamicForm>` (frontend) renders
directly, so the frontend never has to separately fetch+merge custom field defs itself.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.metadata import CustomFieldDef, FormLayout, MetaForm
from app.platform.metadata.custom_fields import active_defs
from app.platform.tenancy.context import TenantContext


def get_layout(db: Session, tenant: TenantContext, entity: str, context: str, *, role_id: Optional[UUID] = None) -> Optional[FormLayout]:
    query = db.query(FormLayout).filter(FormLayout.tenant_id == tenant.tenant_id, FormLayout.entity == entity, FormLayout.context == context)
    rows = query.all()
    if not rows:
        return None
    # A role-scoped layout (role_ids contains role_id) wins over the general one
    # (role_ids IS NULL) when both exist for the same entity/context.
    scoped = [r for r in rows if r.role_ids and role_id is not None and role_id in r.role_ids]
    return scoped[0] if scoped else next((r for r in rows if not r.role_ids), rows[0])


def get_effective_layout(db: Session, tenant: TenantContext, entity: str, context: str, *, role_id: Optional[UUID] = None) -> dict:
    layout = get_layout(db, tenant, entity, context, role_id=role_id)
    defs = active_defs(db, tenant, entity)
    return {
        "entity": entity,
        "context": context,
        "sections": layout.sections_json if layout else [],
        "custom_fields": [_field_def_dict(d) for d in defs],
    }


def _field_def_dict(d: CustomFieldDef) -> dict:
    return {
        "code": d.code, "label_i18n": d.label_i18n, "type": d.type, "validation": d.validation_json,
        "default": d.default, "required_condition": d.required_condition_jsonlogic,
        "visible_condition": d.visible_condition_jsonlogic, "section": d.section, "order": d.order,
        "sensitive": d.sensitive,
    }


def upsert_layout(db: Session, tenant: TenantContext, *, entity: str, context: str, sections: list, role_ids: Optional[list[UUID]] = None) -> FormLayout:
    existing = get_layout(db, tenant, entity, context)
    if existing is not None and (existing.role_ids or []) == (role_ids or []):
        existing.sections_json = sections
        db.commit()
        db.refresh(existing)
        return existing
    row = FormLayout(tenant_id=tenant.tenant_id, entity=entity, context=context, sections_json=sections, role_ids=role_ids)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_form(db: Session, tenant: TenantContext, key: str) -> Optional[MetaForm]:
    return db.query(MetaForm).filter(MetaForm.tenant_id == tenant.tenant_id, MetaForm.key == key).first()


def upsert_form(db: Session, tenant: TenantContext, *, key: str, name: str, schema: dict, ui_schema: Optional[dict] = None) -> MetaForm:
    existing = get_form(db, tenant, key)
    if existing is not None:
        existing.name = name
        existing.schema_json = schema
        existing.ui_schema_json = ui_schema or {}
        db.commit()
        db.refresh(existing)
        return existing
    row = MetaForm(tenant_id=tenant.tenant_id, key=key, name=name, schema_json=schema, ui_schema_json=ui_schema or {})
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
