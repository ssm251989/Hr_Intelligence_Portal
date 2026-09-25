import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Migration/admin DSN (a Postgres superuser locally) -- Alembic's own env.py files read
    # this one, since DDL (ALTER TABLE, CREATE POLICY, ...) needs rights beyond what the
    # runtime app role below has. Never used for ordinary request/query traffic.
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    # Part 2 (docs/HRMS_COMPLETE_SPEC.txt): the control plane's own database -- tenants,
    # plans, module enablement -- deliberately separate from DATABASE_URL (tenant #1's own
    # data) even under TENANCY_MODE=single, so control-plane and tenant migrations/backups
    # stay independent from day one rather than needing a later split. Also a migration/
    # admin DSN -- see APP_CONTROL_PLANE_DATABASE_URL for the runtime one.
    CONTROL_PLANE_DATABASE_URL: str = os.getenv("CONTROL_PLANE_DATABASE_URL", "")
    # Part 2's actual runtime connections -- a non-superuser role (RLS is unconditionally
    # bypassed for a Postgres superuser, FORCE ROW LEVEL SECURITY or not, so the app must
    # never query as one -- see app.platform.tenancy.rls's own comment). Falls back to the
    # admin DSNs above only so a fresh clone that hasn't set these up yet doesn't hard-crash
    # on import; every real environment (including this repo's own local dev, see .env)
    # sets both explicitly.
    APP_DATABASE_URL: str = os.getenv("APP_DATABASE_URL") or DATABASE_URL
    APP_CONTROL_PLANE_DATABASE_URL: str = os.getenv("APP_CONTROL_PLANE_DATABASE_URL") or CONTROL_PLANE_DATABASE_URL
    # single (the only mode deployed at launch, decision A1 -- one installation per client)
    # or multi (kept in the code, not deployed -- section B). A deployment-shape choice,
    # not tenant data, per section A's own carve-out.
    TENANCY_MODE: str = os.getenv("TENANCY_MODE", "single")
    # platform/secrets/store.py's backend selector; MASTER_KEY wraps DbEncryptedSecretStore's
    # per-tenant data-encryption key (envelope encryption), never used to encrypt secrets
    # directly. This pair is deployment/infra config (per-installation, MODE 1), not tenant
    # data -- allowed to live in env per section A's own carve-out.
    SECRET_BACKEND: str = os.getenv("SECRET_BACKEND", "db_encrypted")
    MASTER_KEY: str = os.getenv("MASTER_KEY", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
    DOCUSIGN_INTEGRATION_KEY: str = os.getenv("DOCUSIGN_INTEGRATION_KEY", "")
    DOCUSIGN_SECRET_KEY: str = os.getenv("DOCUSIGN_SECRET_KEY", "")
    DOCUSIGN_ACCOUNT_ID: str = os.getenv("DOCUSIGN_ACCOUNT_ID", "")
    DOCUSIGN_AUTH_BASE_URL: str = os.getenv("DOCUSIGN_AUTH_BASE_URL", "https://account-d.docusign.com")
    DOCUSIGN_API_BASE_URL: str = os.getenv("DOCUSIGN_API_BASE_URL", "https://demo.docusign.net")
    DOCUSIGN_REDIRECT_URI: str = os.getenv("DOCUSIGN_REDIRECT_URI", "http://localhost:8000/auth/docusign/callback")
    LINKEDIN_CLIENT_ID: str = os.getenv("LINKEDIN_CLIENT_ID", "")
    LINKEDIN_CLIENT_SECRET: str = os.getenv("LINKEDIN_CLIENT_SECRET", "")
    LINKEDIN_REDIRECT_URI: str = os.getenv("LINKEDIN_REDIRECT_URI", "http://localhost:8000/auth/linkedin/callback")
    # LinkedIn deprecates API versions on a rolling schedule (YYYYMM format) -- bump this
    # via env var if LinkedIn starts rejecting requests with an "unsupported version" error,
    # no code change needed.
    LINKEDIN_API_VERSION: str = os.getenv("LINKEDIN_API_VERSION", "202507")
    # Used to build the job link included in the LinkedIn hiring-announcement post
    # (backend has no other way to know the frontend's origin).
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:5173")
    # Used to build the interview confirmation link emailed to candidates (Part 3) -- that
    # link is served directly by this backend (GET /interview-confirm/{token}, a self-
    # contained HTML page), not by the frontend SPA, so it needs the backend's own origin
    # rather than FRONTEND_URL.
    APP_BASE_URL: str = os.getenv("APP_BASE_URL", "http://localhost:8000")

    # ---- Part 13: deployment / reliability / security (per-installation infra config,
    # never tenant data -- section A's carve-out) ----
    REDIS_URL: str = os.getenv("REDIS_URL", "")
    CELERY_ALWAYS_EAGER: bool = os.getenv("CELERY_ALWAYS_EAGER", "true").lower() == "true"
    RATE_LIMIT_ENABLED: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
    RATE_LIMIT_USER_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_USER_PER_MINUTE", "1200"))
    RATE_LIMIT_ANON_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_ANON_PER_MINUTE", "300"))
    RATE_LIMIT_TENANT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_TENANT_PER_MINUTE", "20000"))
    HSTS_ENABLED: bool = os.getenv("HSTS_ENABLED", "false").lower() == "true"
    CLAMAV_HOST: str = os.getenv("CLAMAV_HOST", "")
    CLAMAV_PORT: int = int(os.getenv("CLAMAV_PORT", "3310"))
    AV_SCAN_REQUIRED: bool = os.getenv("AV_SCAN_REQUIRED", "false").lower() == "true"  # fail closed if the scanner is unreachable
    LOG_FORMAT: str = os.getenv("LOG_FORMAT", "text")  # text | json
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    METRICS_TOKEN: str = os.getenv("METRICS_TOKEN", "")  # if set, /metrics requires "Authorization: Bearer <token>"
    SENTRY_DSN: str = os.getenv("SENTRY_DSN", "")
    OTEL_EXPORTER_OTLP_ENDPOINT: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    # Data residency (section E): regions a tenant may be pinned to. India-only by default.
    ALLOWED_REGIONS: tuple = tuple(r.strip() for r in os.getenv("ALLOWED_REGIONS", "ap-south-1,ap-south-2").split(",") if r.strip())
    SUPERADMIN_SESSION_MINUTES: int = int(os.getenv("SUPERADMIN_SESSION_MINUTES", "30"))
    IMPERSONATION_MAX_MINUTES: int = int(os.getenv("IMPERSONATION_MAX_MINUTES", "30"))


settings = Settings()
