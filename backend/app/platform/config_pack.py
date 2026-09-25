"""Configuration packs (docs/HRMS_COMPLETE_SPEC.txt Part 2 section 4, Part 13 A/B:
"environments per client: dev / uat / prod -- config promoted via configuration packs,
never re-typed"; `hrctl config-pack export|import`).

A pack is one JSON document: tenant-scope settings (through SettingsService, so each value
is validated against its SettingDef on import) plus the rows of every CONFIGURATION table
-- templates, workflows, masters, forms, pipeline, prompts, plans, policies, dashboards.
Never business data (employees, candidates, tickets...) and never secrets: connections and
their credentials are per-environment and are re-entered, not promoted.

Ids are remapped deterministically on import (uuid5 of the target tenant id + the source
id), and every UUID value in a row that is one of the pack's own ids is rewritten the same
way -- so FKs inside the pack (stage -> template, role ids in a form layout) survive, the
same pack can be applied to two tenants in one database without PK collisions, and
re-importing the same pack is an idempotent upsert.
"""

import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.comms import BrandTheme, MessageLayout, MessageTemplate, NotificationRule
from app.models.core_hr import LetterTemplate
from app.models.iam import Role
from app.models.intelligence import Dashboard, PromptEvalFixture
from app.models.metadata import CustomFieldDef, FormLayout, I18nOverride, MasterValue, MetaForm, Sequence
from app.models.offer_component import OfferComponent
from app.models.onboarding import AssignmentRule, OnboardingPlanTemplate
from app.models.performance import MeritMatrix, RatingScale
from app.models.pipeline import PipelineStage, PipelineTemplate
from app.models.privacy import PrivacyNotice
from app.models.prompt import PromptTemplate
from app.models.service_desk import BusinessCalendar, KbArticle, SlaPolicy, TicketQueue
from app.models.workflow import WorkflowDefinition
from app.platform.tenancy.context import TenantContext

PACK_FORMAT = "hrms-config-pack/1"

# Order matters for FKs: parents before children.
CONFIG_MODELS = (
    BrandTheme, MessageLayout, MessageTemplate, NotificationRule,
    Role, CustomFieldDef, FormLayout, MetaForm, MasterValue, Sequence, I18nOverride,
    WorkflowDefinition, LetterTemplate, PipelineTemplate, PipelineStage, PromptTemplate, PromptEvalFixture, OfferComponent,
    OnboardingPlanTemplate, AssignmentRule, RatingScale, MeritMatrix,
    BusinessCalendar, SlaPolicy, TicketQueue, KbArticle, Dashboard, PrivacyNotice,
)
# Per-table columns that are runtime state, not configuration.
_RUNTIME_COLUMNS = {"sequences": {"current", "current_period"}, "kb_articles": {"helpful_count", "deflection_count"}}
_ALWAYS_SKIP = {"tenant_id"}


class ConfigPackError(ValueError):
    pass


def _jsonable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return {"$uuid": str(value)}
    if isinstance(value, (datetime, date)):
        return {"$dt": value.isoformat()}
    if isinstance(value, Decimal):
        return {"$dec": str(value)}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def _restore(value: Any, id_map: dict[str, uuid.UUID]) -> Any:
    if isinstance(value, dict) and len(value) == 1:
        if "$uuid" in value:
            return id_map.get(value["$uuid"], uuid.UUID(value["$uuid"]))
        if "$dt" in value:
            raw = value["$dt"]
            return datetime.fromisoformat(raw) if "T" in raw else date.fromisoformat(raw)
        if "$dec" in value:
            return Decimal(value["$dec"])
    if isinstance(value, list):
        return [_restore(v, id_map) for v in value]
    return value


def export_pack(db: Session, tenant: TenantContext, *, include_system_roles: bool = False) -> dict:
    from app.platform.settings.registry import all_definitions
    from app.platform.settings.resolver import SettingContext, SettingsService

    service = SettingsService(db)
    ctx = SettingContext(tenant=tenant)
    settings_bundle = {d.key: service.get(d.key, ctx) for d in all_definitions() if d.type != "secret_ref" and not d.sensitive}
    tables: dict[str, list[dict]] = {}
    for model in CONFIG_MODELS:
        table = model.__table__
        skip = _ALWAYS_SKIP | _RUNTIME_COLUMNS.get(table.name, set())
        query = db.query(model).filter(model.tenant_id == tenant.tenant_id)
        if model is Role and not include_system_roles:
            query = query.filter(Role.is_system.is_(False))  # system roles are re-synced from code on every install
        rows = []
        for obj in query.all():
            rows.append({c.name: _jsonable(getattr(obj, c.key)) for c in table.columns if c.name not in skip})
        tables[table.name] = rows
    return {"format": PACK_FORMAT, "exported_at": datetime.utcnow().isoformat() + "Z", "source_tenant": tenant.slug,
            "settings": settings_bundle, "tables": tables}


def _mapped_id(target_tenant_id: uuid.UUID, source_id: str) -> uuid.UUID:
    return uuid.uuid5(target_tenant_id, source_id)


def import_pack(db: Session, tenant: TenantContext, pack: dict, *, actor: str = "config-pack", dry_run: bool = False) -> dict:
    if pack.get("format") != PACK_FORMAT:
        raise ConfigPackError(f"unsupported pack format {pack.get('format')!r}")
    tables = pack.get("tables", {})
    known = {m.__table__.name: m for m in CONFIG_MODELS}
    unknown = sorted(set(tables) - set(known))
    id_map: dict[str, uuid.UUID] = {}
    for rows in tables.values():
        for row in rows:
            raw_id = (row.get("id") or {}).get("$uuid") if isinstance(row.get("id"), dict) else None
            if raw_id:
                id_map[raw_id] = _mapped_id(tenant.tenant_id, raw_id)

    report = {"settings": {"imported": 0, "skipped": []}, "tables": {}, "unknown_tables": unknown, "dry_run": dry_run}
    for model in CONFIG_MODELS:
        rows = tables.get(model.__table__.name, [])
        report["tables"][model.__table__.name] = len(rows)
        if dry_run or not rows:
            continue
        columns = {c.name for c in model.__table__.columns}
        for row in rows:
            values = {k: _restore(v, id_map) for k, v in row.items() if k in columns}
            values["tenant_id"] = tenant.tenant_id
            stmt = pg_insert(model.__table__).values(**values)
            update_cols = {k: stmt.excluded[k] for k in values if k != "id"}
            db.execute(stmt.on_conflict_do_update(index_elements=["id"], set_=update_cols))
    if not dry_run:
        db.commit()

    from app.platform.settings.registry import UnknownSettingError, get_definition
    from app.platform.settings.resolver import SettingsService

    service = SettingsService(db)
    for key, value in (pack.get("settings") or {}).items():
        try:
            definition = get_definition(key)
        except UnknownSettingError:
            report["settings"]["skipped"].append({"key": key, "reason": "unknown setting"})
            continue
        if definition.type == "secret_ref" or definition.sensitive:
            report["settings"]["skipped"].append({"key": key, "reason": "secrets are never imported"})
            continue
        if definition.default == value:
            continue  # nothing to override
        if dry_run:
            report["settings"]["imported"] += 1
            continue
        try:
            service.set(key, value, scope_type="tenant", scope_id=None, actor=actor, tenant=tenant)
            report["settings"]["imported"] += 1
        except ValueError as exc:
            report["settings"]["skipped"].append({"key": key, "reason": str(exc)})
    return report


def dumps(pack: dict) -> str:
    return json.dumps(pack, indent=2, ensure_ascii=False, default=str)
