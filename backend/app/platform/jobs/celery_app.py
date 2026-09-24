"""The Celery app (docs/HRMS_COMPLETE_SPEC.txt Part 2 section E: "jobs/ # celery app,
tenant-aware task base"). No broker is provisioned yet in this installation (Part 13 adds
Redis) -- task_always_eager runs every task body synchronously, in-process, the moment
.delay()/.apply_async() is called, so TenantTask's context-setting behavior (tenant_task.py)
is exercised for real today, without needing a live worker process. Switching this off (and
pointing broker_url at a real Redis) is a Part 13 deployment change, not a code change.
"""

from celery import Celery

celery_app = Celery("hr_automation")
celery_app.conf.task_always_eager = True
celery_app.conf.task_eager_propagates = True
