# HRMS backend image (docs/HRMS_COMPLETE_SPEC.txt Part 13 section A). ONE image, three
# process roles selected by build target (or by overriding the command):
#   api    -> uvicorn
#   worker -> celery worker (queue(s) from CELERY_QUEUES)
#   beat   -> celery beat (exactly one replica per installation)
# No tenant or client value is baked in: everything arrives as env/secrets at runtime.

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 postgresql-client curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 hrms
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt redis
COPY --chown=hrms:hrms . .
RUN mkdir -p /app/uploads && chown hrms:hrms /app/uploads
USER hrms
ENV LOG_FORMAT=json

FROM base AS api
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -fsS http://localhost:8000/healthz || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]

FROM base AS worker
ENV CELERY_QUEUES=high,default,low \
    CELERY_CONCURRENCY=4
CMD ["sh", "-c", "celery -A app.platform.jobs.scheduled:celery_app worker --loglevel=INFO -Q ${CELERY_QUEUES} --concurrency ${CELERY_CONCURRENCY}"]

FROM base AS beat
CMD ["celery", "-A", "app.platform.jobs.scheduled:celery_app", "beat", "--loglevel=INFO", "--schedule", "/tmp/celerybeat-schedule"]
