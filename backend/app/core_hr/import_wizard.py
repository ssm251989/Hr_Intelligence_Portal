"""Data import / migration toolkit (docs/HRMS_COMPLETE_SPEC.txt Part 7 section 6) --
upload -> column mapping -> validation preview -> dry run -> commit -> rollback, scoped to
the one entity this part actually has a real target table for (`employee`) rather than a
fully generic importer for arbitrary future entities -- extending `IMPORT_ENTITY_TYPES`
(app.models.core_hr) plus one new `_commit_row`/`_validate_row` branch is what a future
part's own entity would need, not a rewrite of this module.

No background job queue actually runs `commit()` asynchronously (same "no live Celery
worker" gap as everywhere else in this build) -- it runs synchronously inline, same as
Part 2's own `TenantTask.apply_for_tenant` under `task_always_eager`.
"""

from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.core_hr import EMPLOYEE_STATUSES, WORKER_TYPES, Employee, ImportBatch, ImportRow
from app.platform.tenancy.context import TenantContext

REQUIRED_EMPLOYEE_COLUMNS = ("first_name",)


class ImportBatchStateError(Exception):
    pass


def _validate_employee_row(raw: dict[str, Any]) -> list[str]:
    errors = []
    if not raw.get("first_name"):
        errors.append("first_name is required")
    status = raw.get("status", "pre_hire")
    if status not in EMPLOYEE_STATUSES:
        errors.append(f"status must be one of {EMPLOYEE_STATUSES}")
    worker_type = raw.get("worker_type", "employee")
    if worker_type not in WORKER_TYPES:
        errors.append(f"worker_type must be one of {WORKER_TYPES}")
    return errors


_VALIDATORS = {"employee": _validate_employee_row}


def create_batch(db: Session, tenant: TenantContext, *, entity: str, rows: list[dict], column_mapping: dict, created_by: Optional[str] = None) -> ImportBatch:
    """Applies `column_mapping` (source-column -> target-field) to every raw row, then
    validates each one -- the batch lands in status="preview" with every row already
    scored valid/invalid, so a caller sees the full validation preview from the first
    call (section 6's own "validation preview (row errors)"), not a separate step."""
    if entity not in _VALIDATORS:
        raise ValueError(f"Unsupported import entity: {entity!r} (supported: {sorted(_VALIDATORS)})")
    validator = _VALIDATORS[entity]

    batch = ImportBatch(tenant_id=tenant.tenant_id, entity=entity, column_mapping_json=column_mapping, status="preview", created_by=created_by)
    db.add(batch)
    db.commit()
    db.refresh(batch)

    error_count = 0
    for i, raw_row in enumerate(rows, start=1):
        mapped = {target: raw_row.get(source) for source, target in column_mapping.items()}
        errors = validator(mapped)
        if errors:
            error_count += 1
        db.add(ImportRow(tenant_id=tenant.tenant_id, batch_id=batch.id, row_number=i, raw_json=mapped, status="invalid" if errors else "valid", errors_json=errors or None))

    batch.row_count = len(rows)
    batch.error_count = error_count
    db.commit()
    db.refresh(batch)
    return batch


def mark_dry_run(db: Session, tenant: TenantContext, batch_id: UUID) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if batch is None or batch.tenant_id != tenant.tenant_id:
        raise ImportBatchStateError("Batch not found")
    if batch.status != "preview":
        raise ImportBatchStateError(f"Batch must be in 'preview' to mark dry_run (is {batch.status!r})")
    batch.status = "dry_run"
    db.commit()
    db.refresh(batch)
    return batch


def commit_batch(db: Session, tenant: TenantContext, batch_id: UUID, *, created_by: Optional[str] = None) -> dict:
    from app.core_hr.employees import create_employee

    batch = db.get(ImportBatch, batch_id)
    if batch is None or batch.tenant_id != tenant.tenant_id:
        raise ImportBatchStateError("Batch not found")
    if batch.status not in ("preview", "dry_run"):
        raise ImportBatchStateError(f"Batch must be in 'preview' or 'dry_run' to commit (is {batch.status!r})")

    rows = db.query(ImportRow).filter(ImportRow.tenant_id == tenant.tenant_id, ImportRow.batch_id == batch_id, ImportRow.status == "valid").all()
    committed = 0
    for row in rows:
        if batch.entity == "employee":
            employee = create_employee(db, tenant, **row.raw_json)
            row.committed_entity_id = employee.id
            row.status = "committed"
            committed += 1

    batch.status = "committed"
    db.commit()
    return {"committed": committed, "skipped_invalid": batch.error_count}


def rollback_batch(db: Session, tenant: TenantContext, batch_id: UUID) -> int:
    """Deletes ONLY the rows this specific batch itself created (via `committed_entity_
    id`) -- never touches any other data, bounded and safe by construction."""
    batch = db.get(ImportBatch, batch_id)
    if batch is None or batch.tenant_id != tenant.tenant_id:
        raise ImportBatchStateError("Batch not found")
    if batch.status != "committed":
        raise ImportBatchStateError(f"Batch must be 'committed' to roll back (is {batch.status!r})")

    rows = db.query(ImportRow).filter(ImportRow.tenant_id == tenant.tenant_id, ImportRow.batch_id == batch_id, ImportRow.status == "committed").all()
    deleted = 0
    for row in rows:
        if batch.entity == "employee" and row.committed_entity_id:
            employee = db.get(Employee, row.committed_entity_id)
            if employee is not None:
                db.delete(employee)
                deleted += 1
        row.committed_entity_id = None
        row.status = "valid"

    batch.status = "rolled_back"
    db.commit()
    return deleted
