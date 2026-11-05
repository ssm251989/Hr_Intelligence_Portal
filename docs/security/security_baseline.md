# Security baseline (Part 13 section D) — OWASP ASVS L2 mapping, pen-test checklist, compliance path

## ASVS L2 — where each control lives

| ASVS area | Control in this codebase |
|---|---|
| V1 Architecture | Tenant isolation: DB-per-tenant or RLS (`FORCE ROW LEVEL SECURITY` on every tenant table); app runs as a non-superuser role (`hrctl installation init` refuses otherwise) |
| V2 Authentication | bcrypt; lockout (`iam.auth.lockout_*`); TOTP/email OTP MFA, tenant-enforceable; console MFA mandatory; one-time set-password links (action tokens, single use, expiring) |
| V3 Session | Short-lived JWT + rotating refresh tokens bound to devices; tenant id claim checked per request; impersonation tokens revocable server-side |
| V4 Access control | `authz.require()` permission per endpoint; org-hierarchy data scopes (`org_scope.py`); field security (hidden/masked) enforced in APIs and the report builder |
| V5 Validation | Pydantic models on every endpoint; JSONLogic validated at write time; Jinja sandbox for templates; CSS sanitizer |
| V6 Cryptography | Envelope encryption (MASTER_KEY → per-tenant DEK) for secrets and PII columns; TLS everywhere (RDS `force_ssl`, Redis TLS, CloudFront TLS1.2+); KMS at rest |
| V7 Errors/logging | JSON logs with request/tenant ids; no PII in logs; audit log + CSV audit export (`/api/v1/privacy/audit-export`) |
| V8 Data protection | DPDP module: consent ledger, notices, DSR workflow, retention with 2-person approval, breach register; AI PII redaction |
| V9 Communications | HSTS (`HSTS_ENABLED`), CSP (API lock-down / HTML self-only / SPA policy in nginx) |
| V10 Malicious code | Dependency scans (pip-audit, npm audit), SAST (bandit, semgrep), image scan (trivy), secret scan (gitleaks) in CI |
| V12 Files | AV scan hook (ClamAV INSTREAM, fail-closed with `AV_SCAN_REQUIRED`), size limits, type allow-lists |
| V13 API | Rate limiting per tenant/user/IP; consistent 401/403/404 (no existence leaks for confidential tickets, portal tokens) |
| V14 Config | No client values in code (hardcode guard test); secrets only via SecretStore/Secrets Manager; non-root containers |

## Pen-test checklist (run before each client go-live)

- [ ] Cross-tenant: token from tenant A against tenant B host → 403; raw SQL with unset `app.tenant_id` returns 0 rows
- [ ] Horizontal privilege: employee reads another employee's `/me/...`, ticket, asset, review → denied
- [ ] Manager scope: dataset/report returns only reportees; hidden fields cannot be grouped/filtered
- [ ] Confidential tickets invisible (404) without `helpdesk.ticket.view_sensitive`
- [ ] Portal/BGV/action tokens: brute force rate-limited; expired/used tokens rejected uniformly
- [ ] Upload: EICAR test file rejected when ClamAV configured; oversized file → 413
- [ ] Stored XSS via templates, KB articles, copilot answers; CSP headers present
- [ ] SSRF via connection configs (webhook/SMTP hosts) — outbound allow-list reviewed
- [ ] AI: prompt injection in uploaded policy cannot trigger actions (copilot actions are drafts only)
- [ ] Impersonation leaves an entry in the tenant's audit log; ended session token rejected
- [ ] Headers: HSTS, CSP, X-Frame-Options, nosniff on API, HTML pages and SPA

## Path to ISO 27001 / SOC 2

Evidence already produced by the system: access reviews (`/api/v1/iam/access-review`), audit export,
change management (CI + protected branches), backup + restore-drill reports, vulnerability scan
results, incident register (`breach_incidents`), encryption configuration (Terraform). Organisational
controls (policies, risk register, vendor reviews, HR security) are outside the codebase.
