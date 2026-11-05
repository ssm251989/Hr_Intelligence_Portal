"""Logs, metrics, traces, errors (docs/HRMS_COMPLETE_SPEC.txt Part 13 section C).

- JSON logs (`LOG_FORMAT=json`) with `tenant_id` / `tenant_slug` / `request_id` on every
  record, via a stdlib logging filter (structlog-compatible output without making it a hard
  dependency).
- Prometheus text exposition at /metrics: request count + latency histogram by method,
  route template and status, with a `tenant` label that is BOUNDED -- after
  `_MAX_TENANT_LABELS` distinct tenants, further ones report as "other" so a multi-tenant
  installation can't blow up the metrics cardinality.
- Sentry / OpenTelemetry are initialised only when their env vars are set AND the package
  is installed; otherwise skipped silently (dev images don't carry them).
"""

import json
import logging
import threading
import time
import uuid
from contextvars import ContextVar
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.config import settings
from app.platform.tenancy.context import get_current_tenant

request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)

_BUCKETS = (0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 1.5, 2.5, 5.0, 10.0)
_MAX_TENANT_LABELS = 50


# ---- logging ----


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        tenant = get_current_tenant()
        record.tenant_id = str(tenant.tenant_id) if tenant else None
        record.tenant_slug = tenant.slug if tenant else None
        record.request_id = request_id_var.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"), "level": record.levelname, "logger": record.name, "event": record.getMessage(),
            "tenant_id": getattr(record, "tenant_id", None), "tenant_slug": getattr(record, "tenant_slug", None), "request_id": getattr(record, "request_id", None),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL.upper())
    handler = logging.StreamHandler()
    handler.addFilter(_ContextFilter())
    handler.setFormatter(_JsonFormatter() if settings.LOG_FORMAT == "json" else logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(tenant_slug)s] %(message)s"))
    root.handlers = [handler]


# ---- metrics ----


class _Metrics:
    def __init__(self):
        self._lock = threading.Lock()
        self.requests: dict[tuple, int] = {}
        self.latency_buckets: dict[tuple, list[int]] = {}
        self.latency_sum: dict[tuple, float] = {}
        self._tenants: set[str] = set()

    def tenant_label(self, slug: Optional[str]) -> str:
        if not slug:
            return "none"
        with self._lock:
            if slug in self._tenants or len(self._tenants) < _MAX_TENANT_LABELS:
                self._tenants.add(slug)
                return slug
        return "other"

    def observe(self, method: str, route: str, status: int, tenant: str, seconds: float) -> None:
        key = (method, route, str(status), tenant)
        lkey = (method, route, tenant)
        with self._lock:
            self.requests[key] = self.requests.get(key, 0) + 1
            buckets = self.latency_buckets.setdefault(lkey, [0] * (len(_BUCKETS) + 1))
            for i, bound in enumerate(_BUCKETS):
                if seconds <= bound:
                    buckets[i] += 1
            buckets[-1] += 1  # +Inf
            self.latency_sum[lkey] = self.latency_sum.get(lkey, 0.0) + seconds

    def render(self) -> str:
        def labels(**kv) -> str:
            return "{" + ",".join(f'{k}="{str(v).replace(chr(34), "")}"' for k, v in kv.items()) + "}"

        lines = ["# HELP hrms_http_requests_total HTTP requests", "# TYPE hrms_http_requests_total counter"]
        with self._lock:
            for (method, route, status, tenant), n in sorted(self.requests.items()):
                lines.append(f"hrms_http_requests_total{labels(method=method, route=route, status=status, tenant=tenant)} {n}")
            lines += ["# HELP hrms_http_request_seconds Request latency", "# TYPE hrms_http_request_seconds histogram"]
            for (method, route, tenant), buckets in sorted(self.latency_buckets.items()):
                for bound, count in zip([*map(str, _BUCKETS), "+Inf"], buckets):
                    lines.append(f"hrms_http_request_seconds_bucket{labels(method=method, route=route, tenant=tenant, le=bound)} {count}")
                lines.append(f"hrms_http_request_seconds_sum{labels(method=method, route=route, tenant=tenant)} {self.latency_sum[(method, route, tenant)]:.6f}")
                lines.append(f"hrms_http_request_seconds_count{labels(method=method, route=route, tenant=tenant)} {buckets[-1]}")
        return "\n".join(lines) + "\n"


METRICS = _Metrics()


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Request id (honours an inbound X-Request-ID), timing, metrics. Uses the matched
    route TEMPLATE ("/api/v1/tickets/{ticket_id}"), never the raw path, as the label."""

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(rid)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            route = request.scope.get("route")
            template = getattr(route, "path", None) or "unmatched"
            tenant = get_current_tenant()
            METRICS.observe(request.method, template, status, METRICS.tenant_label(tenant.slug if tenant else None), time.perf_counter() - start)
            request_id_var.reset(token)


def init_optional_integrations(app) -> list[str]:
    enabled = []
    if settings.SENTRY_DSN:
        try:
            import sentry_sdk

            sentry_sdk.init(dsn=settings.SENTRY_DSN, traces_sample_rate=0.05, send_default_pii=False)
            enabled.append("sentry")
        except ImportError:
            logging.getLogger(__name__).warning("SENTRY_DSN set but sentry_sdk is not installed")
    if settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(app)
            enabled.append("opentelemetry")
        except ImportError:
            logging.getLogger(__name__).warning("OTEL endpoint set but opentelemetry-instrumentation-fastapi is not installed")
    return enabled
