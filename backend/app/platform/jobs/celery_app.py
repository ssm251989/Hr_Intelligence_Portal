"""The Celery app (docs/HRMS_COMPLETE_SPEC.txt Part 2 section E: "jobs/ # celery app,
tenant-aware task base"). No broker is provisioned yet in this installation (Part 13 adds
Redis) -- task_always_eager runs every task body synchronously, in-process, the moment
.delay()/.apply_async() is called, so TenantTask's context-setting behavior (tenant_task.py)
is exercised for real today, without needing a live worker process. Switching this off (and
pointing broker_url at a real Redis) is a Part 13 deployment change, not a code change.
"""

from celery import Celery
from kombu import Queue

from app.core.config import settings

celery_app = Celery("hr_automation")
# Part 13: a real Redis broker when REDIS_URL is set (docker-compose / Helm / ECS);
# eager in-process execution otherwise (local dev + tests), exactly as before.
celery_app.conf.task_always_eager = settings.CELERY_ALWAYS_EAGER or not settings.REDIS_URL
celery_app.conf.task_eager_propagates = True
if settings.REDIS_URL:
    celery_app.conf.broker_url = settings.REDIS_URL
    celery_app.conf.result_backend = settings.REDIS_URL
# Job queues per priority (section C). Workers are started per queue with their own
# concurrency (see docker-compose.yml / charts/hrms), so a flood of low-priority report
# jobs can't starve OTP/notification sends.
celery_app.conf.task_queues = (Queue("high"), Queue("default"), Queue("low"))
celery_app.conf.task_default_queue = "default"
celery_app.conf.worker_prefetch_multiplier = 1  # fair dispatch across tenants
celery_app.conf.task_acks_late = True
