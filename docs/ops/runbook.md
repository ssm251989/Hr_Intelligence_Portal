# HRMS operations runbook (Part 13)

One installation per client (MODE 1, `TENANCY_MODE=single`). MODE 2 (`multi`) is supported by the
same image and chart but is not deployed at launch.

## 1. Stand up a client installation (AWS, ap-south-1)

1. `cd infra/terraform/aws && terraform init && terraform apply -var-file=clients/<slug>/<env>.tfvars`
   (VPC, ECS Fargate api/worker/beat, RDS Postgres 16 with PITR, ElastiCache Redis, S3, CloudFront,
   ACM, Route53, Secrets Manager, CloudWatch alarms, KMS). DR: `dr_enabled = true` replicates RDS
   backups to ap-south-2. Regions outside India are rejected by the module.
2. Put the installation's `MASTER_KEY` into the `…/app` secret **out of band** (never in tfvars/state):
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
3. Run the `migrate` task definition once (`hrctl installation init` + `hrctl migrate --all-tenants
   --control-plane`). It is idempotent and also runs before every deploy.
4. Create the tenant: `python -m hrctl.tenant create --slug <slug> --name "<Legal name>" --isolation
   dedicated_db --region ap-south-1 --admin-email <first admin> --domain <host> [--config-pack pack.json]`.
   Always run with `--dry-run` first. The first admin receives a one-time set-password link (or it is
   printed if the tenant has no mailbox yet).
5. The admin finishes in the Setup Wizard (Part 14).

## 2. Promote configuration dev → uat → prod

`python -m hrctl.config_pack export --slug <slug> --out pack.json` on the source environment, review
the diff, then `python -m hrctl.config_pack import --slug <slug> --file pack.json --dry-run` and
without `--dry-run` on the target. Packs never contain secrets or connection credentials — those are
entered per environment.

## 3. Tenant lifecycle

| Action | Command | Notes |
|---|---|---|
| Suspend | `hrctl.tenant suspend --slug s --reason "..."` | API returns 423 with the reason |
| Resume | `hrctl.tenant resume --slug s` | |
| Archive | `hrctl.tenant archive --slug s` | API returns 410; data kept |
| Delete | `hrctl.tenant delete --slug s` → report; `--confirm s` to mark deleted; `--drop-database` additionally drops a dedicated DB | tenant #1 cannot be deleted |
| Move installation | `hrctl.tenant export --slug s --out s.zip` then on the target `hrctl.tenant import --file s.zip` | schema revisions must match; secrets travel encrypted under the source MASTER_KEY — re-enter connection credentials on the target; copy object-storage prefix `tenants/<id>/` separately |

## 4. Migrations (zero downtime)

Expand/contract: a release's migration only **adds** (columns nullable or defaulted, new tables);
code stops using the old shape; the **removal** ships one release later. The Helm pre-upgrade hook /
ECS migrate task runs control plane first, then every tenant DB (`--parallel N`). Feature flags
(control-plane `feature_flags`) gate risky rollouts per tenant.

## 5. Backups & restore drill

* Primary: RDS automated backups + PITR (`backup_retention_days`), optional cross-region replication.
* Portable layer: `python -m scripts.backup_tenants --out /backups --retention-days 30` (one dump per
  distinct tenant DB + control plane).
* Monthly drill: `python -m scripts.restore_drill --dump <file>` restores into a throwaway database,
  checks schema revision + row counts, drops only that throwaway DB, prints a report. File the report.

## 6. Observability

* Logs: JSON (`LOG_FORMAT=json`) with `tenant_id`, `tenant_slug`, `request_id`; shipped to CloudWatch.
* Metrics: `GET /metrics` (Prometheus text; set `METRICS_TOKEN`), tenant label bounded to 50.
* Traces/errors: set `OTEL_EXPORTER_OTLP_ENDPOINT` / `SENTRY_DSN` (packages optional in the image).
* Health: `/healthz` (liveness), `/readyz` (DB, control plane, Redis) — used by ALB/k8s probes.
* Per-tenant connection health: Super-Admin console `GET /api/v1/superadmin/tenants/<slug>/health`.

## 7. Noisy-tenant protection

Rate limits per tenant / user / anonymous IP (`RATE_LIMIT_*`), Celery queues `high|default|low` on
separate worker pools, and `TENANT_MAX_CONCURRENT_JOBS` per tenant (excess jobs are re-queued).

## 8. Super-Admin console

`echo '<password>' | python -m hrctl.superadmin create --email <you>` — TOTP enrolment is mandatory;
scan the printed `otpauth://` URI. Every console action is in `superadmin_audit`; impersonation is
time-boxed (`IMPERSONATION_MAX_MINUTES`), needs a reason, is written to the tenant's own audit log,
and is revoked immediately by `POST /impersonations/<id>/end`.

## 9. Key rotation

* `SECRET_KEY` (JWT): rotate in Secrets Manager and redeploy — all sessions end.
* `MASTER_KEY`: envelope key over per-tenant DEKs; rotation = re-wrap DEKs (SecretStore rotate path)
  during a maintenance window; never delete the old key until every DEK is re-wrapped.
* DB/Redis passwords: rotate in Secrets Manager, redeploy tasks.
