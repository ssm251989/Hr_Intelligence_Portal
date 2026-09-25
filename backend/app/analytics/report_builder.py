"""ReportBuilder (docs/HRMS_COMPLETE_SPEC.txt Part 12 section A.2, named in this part's
CHECKS): dataset -> columns (incl. custom fields) -> filters -> group/pivot -> chart,
compiled to ONE SQL query per run (server-side filtering/grouping/pagination -- Part 14's
"list pages < 1.5s p95 on 10k rows" applies to reports too), then exported CSV/XLSX.

Security is not optional here: every run is as a specific user, with the dataset's
permission checked, their org data-scope applied as a WHERE on the dataset's employee
column, and field security enforced (hidden/masked fields can't be filtered, grouped or
aggregated on -- that would leak them -- and are masked in plain row output).
"""

import csv
import io
from datetime import date
from typing import Any, Optional

from sqlalchemy import asc, desc, false, func, select
from sqlalchemy.orm import Session

from app.analytics.datasets import BuiltDataset, DatasetDef, get_dataset
from app.models.user import User
from app.platform.iam.authz import has_permission
from app.platform.iam.field_security import _field_access_map
from app.platform.iam.org_scope import employee_ids_in_scope
from app.platform.tenancy.context import TenantContext

OPS = ("eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "contains", "between", "is_null", "not_null")
AGGS = ("count", "count_distinct", "sum", "avg", "min", "max")
MAX_ROWS = 10_000
DEFAULT_LIMIT = 500


class ReportError(ValueError):
    pass


class ReportPermissionError(PermissionError):
    pass


def _filter_clause(field_expr, op: str, value: Any):
    if op == "eq":
        return field_expr == value
    if op == "ne":
        return field_expr != value
    if op == "in":
        return field_expr.in_(list(value or []))
    if op == "not_in":
        return ~field_expr.in_(list(value or []))
    if op == "gt":
        return field_expr > value
    if op == "gte":
        return field_expr >= value
    if op == "lt":
        return field_expr < value
    if op == "lte":
        return field_expr <= value
    if op == "contains":
        return field_expr.ilike(f"%{value}%")
    if op == "between":
        low, high = value
        return field_expr.between(low, high)
    if op == "is_null":
        return field_expr.is_(None)
    if op == "not_null":
        return field_expr.isnot(None)
    raise ReportError(f"unknown operator {op!r}")


def _agg(fn: str, expr):
    return {
        "count": func.count(expr), "count_distinct": func.count(func.distinct(expr)), "sum": func.sum(expr),
        "avg": func.avg(expr), "min": func.min(expr), "max": func.max(expr),
    }[fn]


def _json_safe(value):
    if isinstance(value, (date,)):
        return value.isoformat()
    if hasattr(value, "hex") and not isinstance(value, (bytes, str)):  # UUID
        return str(value)
    if value.__class__.__name__ == "Decimal":
        return float(value)
    return value


class ReportBuilder:
    def __init__(self, db: Session, tenant: TenantContext, user: User):
        self.db = db
        self.tenant = tenant
        self.user = user

    # ---- validation / security ----

    def _authorize(self, dataset: DatasetDef) -> None:
        if not has_permission(self.db, self.tenant, self.user, dataset.permission):
            raise ReportPermissionError(f"missing permission {dataset.permission} for dataset {dataset.code}")

    def _restricted_fields(self, dataset: DatasetDef) -> dict[str, str]:
        if not dataset.field_security_entity:
            return {}
        return {k: v for k, v in _field_access_map(self.db, self.tenant, self.user, dataset.field_security_entity).items() if v in ("hidden", "masked")}

    def validate(self, dataset: DatasetDef, built: BuiltDataset, definition: dict) -> None:
        known = built.fields
        restricted = self._restricted_fields(dataset)
        used_structurally = [f["field"] for f in definition.get("filters", [])] + list(definition.get("group_by", [])) + [m["field"] for m in definition.get("measures", []) if m.get("field") != "*"]
        for key in list(definition.get("columns", [])) + used_structurally + [s["field"] for s in definition.get("sort", [])]:
            if key not in known and not any(key == m.get("as") for m in definition.get("measures", [])):
                raise ReportError(f"unknown field {key!r} in dataset {dataset.code}")
        for key in used_structurally:
            if key in restricted:
                raise ReportPermissionError(f"field {key!r} is not available to you for filtering or grouping")
        for f in definition.get("filters", []):
            if f.get("op") not in OPS:
                raise ReportError(f"unknown operator {f.get('op')!r}")
        for m in definition.get("measures", []):
            if m.get("agg") not in AGGS:
                raise ReportError(f"unknown aggregation {m.get('agg')!r}")
        if definition.get("as_of") and not dataset.as_of_supported:
            raise ReportError(f"dataset {dataset.code} is not effective-dated; as_of is not supported")
        if definition.get("pivot") and not definition.get("group_by"):
            raise ReportError("pivot needs group_by")

    # ---- compile + run ----

    def _base(self, dataset: DatasetDef, built: BuiltDataset, definition: dict, columns):
        query = select(*columns).select_from(built.from_clause)
        for clause in built.base_filters:
            query = query.where(clause)
        scope = employee_ids_in_scope(self.db, self.tenant, self.user, dataset.permission)
        if scope is not None and built.employee_column is not None:
            query = query.where(built.employee_column.in_(list(scope)) if scope else false())
        for f in definition.get("filters", []):
            query = query.where(_filter_clause(built.fields[f["field"]].expr, f["op"], f.get("value")))
        return query

    def run(self, dataset_code: str, definition: dict, *, offset: int = 0) -> dict:
        try:
            dataset = get_dataset(dataset_code)
        except KeyError:
            raise ReportError(f"unknown dataset {dataset_code!r}")
        self._authorize(dataset)
        as_of = date.fromisoformat(definition["as_of"]) if definition.get("as_of") else date.today()
        built = dataset.build(self.db, self.tenant, as_of)
        self.validate(dataset, built, definition)
        limit = min(int(definition.get("limit") or DEFAULT_LIMIT), MAX_ROWS)
        group_by = list(definition.get("group_by", []))
        measures = list(definition.get("measures", []))

        if group_by or measures:
            columns = [built.fields[g].expr.label(g) for g in group_by]
            for m in measures:
                expr = func.count() if m.get("field") in (None, "*") and m["agg"] == "count" else _agg(m["agg"], built.fields[m["field"]].expr)
                columns.append(expr.label(m.get("as") or f"{m['agg']}_{m.get('field', 'rows')}"))
            query = self._base(dataset, built, definition, columns)
            if group_by:
                query = query.group_by(*[built.fields[g].expr for g in group_by])
            out_columns = [c.key for c in columns]
        else:
            keys = list(definition.get("columns") or list(built.fields.keys())[:12])
            columns = [built.fields[k].expr.label(k) for k in keys]
            query = self._base(dataset, built, definition, columns)
            out_columns = keys

        total = self.db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
        for s in definition.get("sort", []):
            target = s["field"]
            direction = desc if s.get("dir") == "desc" else asc
            query = query.order_by(direction(target if target in out_columns else built.fields[target].expr))
        rows = [dict(zip(out_columns, (_json_safe(v) for v in r))) for r in self.db.execute(query.offset(max(offset, 0)).limit(limit)).all()]

        restricted = self._restricted_fields(dataset)
        if restricted and not (group_by or measures):
            rows = [{k: ("***" if restricted.get(k) == "masked" else v) for k, v in row.items() if restricted.get(k) != "hidden"} for row in rows]
            out_columns = [c for c in out_columns if restricted.get(c) != "hidden"]

        result = {"dataset": dataset.code, "columns": out_columns, "rows": rows, "total": total, "offset": offset, "limit": limit,
                  "as_of": as_of.isoformat() if dataset.as_of_supported else None, "chart": definition.get("chart")}
        if definition.get("pivot"):
            result = {**result, **self.pivot(rows, group_by, definition["pivot"])}
        return result

    @staticmethod
    def pivot(rows: list[dict], group_by: list[str], spec: dict) -> dict:
        on, value = spec["on"], spec["value"]
        if on not in group_by:
            raise ReportError("pivot 'on' must be one of the group_by fields")
        keys = [g for g in group_by if g != on]
        pivot_values = sorted({str(r[on]) for r in rows})
        table: dict[tuple, dict] = {}
        for r in rows:
            k = tuple(r[g] for g in keys)
            table.setdefault(k, {g: r[g] for g in keys})[str(r[on])] = r.get(value)
        return {"pivot_columns": keys + pivot_values, "pivot_rows": list(table.values())}


# ---- export ----


def to_csv(result: dict) -> bytes:
    columns = result.get("pivot_columns") or result["columns"]
    rows = result.get("pivot_rows") or result["rows"]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8")


def to_xlsx(result: dict, *, title: str = "Report") -> bytes:
    from openpyxl import Workbook

    columns = result.get("pivot_columns") or result["columns"]
    rows = result.get("pivot_rows") or result["rows"]
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31] or "Report"
    ws.append(columns)
    for row in rows:
        ws.append([row.get(c) for c in columns])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def export(result: dict, fmt: str, *, title: str = "Report") -> tuple[bytes, str, str]:
    """-> (content, media type, extension). PDF is deferred: no PDF renderer is installed
    in this image (same gap Part 7 documented for letters)."""
    if fmt == "csv":
        return to_csv(result), "text/csv", "csv"
    if fmt == "xlsx":
        return to_xlsx(result, title=title), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    raise ReportError(f"unsupported export format {fmt!r} (csv, xlsx)")
