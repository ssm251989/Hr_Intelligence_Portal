"""Scheduled report delivery (docs/HRMS_COMPLETE_SPEC.txt Part 12 section A.2): a saved
report runs AS ITS OWNER (so the owner's scope and field security apply, never a wider
system identity), is exported CSV/XLSX, and sent through a comms template on the
`email.outbound.reports` purpose. `run_due_schedules()` is what a beat task calls."""

from calendar import monthrange
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.analytics.report_builder import ReportBuilder, ReportError, export
from app.models.intelligence import ReportDelivery, ReportSchedule, SavedReport
from app.models.user import User
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import TenantContext


class ScheduleError(ValueError):
    pass


def _tz(db: Session, tenant: TenantContext) -> ZoneInfo:
    return ZoneInfo(SettingsService(db).get("org.timezone", SettingContext(tenant=tenant)) or "UTC")


def next_run_after(schedule: ReportSchedule, after: datetime, tz: ZoneInfo) -> datetime:
    local = after.astimezone(tz)
    candidate = local.replace(hour=schedule.hour, minute=0, second=0, microsecond=0)
    if schedule.frequency == "daily":
        if candidate <= local:
            candidate += timedelta(days=1)
    elif schedule.frequency == "weekly":
        target = schedule.day_of_week or 0
        candidate += timedelta(days=(target - candidate.weekday()) % 7)
        if candidate <= local:
            candidate += timedelta(days=7)
    elif schedule.frequency == "monthly":
        day = min(schedule.day_of_month or 1, 28)
        candidate = candidate.replace(day=day)
        if candidate <= local:
            year, month = (candidate.year + 1, 1) if candidate.month == 12 else (candidate.year, candidate.month + 1)
            candidate = candidate.replace(year=year, month=month, day=min(day, monthrange(year, month)[1]))
    else:
        raise ScheduleError(f"unknown frequency {schedule.frequency!r}")
    return candidate.astimezone(timezone.utc)


def create_schedule(db: Session, tenant: TenantContext, report: SavedReport, *, frequency: str, hour: int, recipients: list[str], template_key: str,
                    fmt: str = "csv", day_of_week: Optional[int] = None, day_of_month: Optional[int] = None, now: Optional[datetime] = None) -> ReportSchedule:
    if not recipients:
        raise ScheduleError("a schedule needs at least one recipient")
    if not 0 <= hour <= 23:
        raise ScheduleError("hour is 0-23")
    schedule = ReportSchedule(tenant_id=tenant.tenant_id, report_id=report.id, frequency=frequency, hour=hour, recipients_json=recipients,
                              template_key=template_key, format=fmt, day_of_week=day_of_week, day_of_month=day_of_month)
    schedule.next_run_at = next_run_after(schedule, now or datetime.now(timezone.utc), _tz(db, tenant))
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


def deliver(db: Session, tenant: TenantContext, schedule: ReportSchedule, *, now: Optional[datetime] = None) -> ReportDelivery:
    from app.platform.comms.service import send

    now = now or datetime.now(timezone.utc)
    report = db.get(SavedReport, schedule.report_id)
    owner = db.get(User, report.owner_user_id) if report else None
    delivery = ReportDelivery(tenant_id=tenant.tenant_id, schedule_id=schedule.id, run_at=now)
    try:
        if report is None or owner is None:
            raise ScheduleError("report or its owner no longer exists")
        result = ReportBuilder(db, tenant, owner).run(report.dataset_code, report.definition_json)
        content, media_type, ext = export(result, schedule.format, title=report.name)
        maintype, subtype = media_type.split("/", 1)
        send(
            db, tenant, template_key=schedule.template_key, to=list(schedule.recipients_json), purpose="email.outbound.reports",
            ctx={"report": {"name": report.name, "row_count": result["total"], "run_at": now.isoformat()}},
            related_entity_type="report_schedule", related_entity_id=schedule.id,
            attachments=[{"content": content, "maintype": maintype, "subtype": subtype, "filename": f"{report.name}.{ext}"}],
        )
        delivery.status = "sent" if result["total"] else "empty"
        delivery.row_count = result["total"]
    except (ReportError, ScheduleError, PermissionError) as exc:
        delivery.status, delivery.error = "failed", str(exc)
    except Exception as exc:  # delivery failures are recorded, never crash the beat loop
        delivery.status, delivery.error = "failed", type(exc).__name__
    schedule.last_run_at = now
    schedule.next_run_at = next_run_after(schedule, now, _tz(db, tenant))
    db.add(delivery)
    db.commit()
    db.refresh(delivery)
    return delivery


def run_due_schedules(db: Session, tenant: TenantContext, *, now: Optional[datetime] = None) -> list[ReportDelivery]:
    now = now or datetime.now(timezone.utc)
    due = db.query(ReportSchedule).filter(ReportSchedule.tenant_id == tenant.tenant_id, ReportSchedule.enabled.is_(True), ReportSchedule.next_run_at <= now).all()
    return [deliver(db, tenant, s, now=now) for s in due]
