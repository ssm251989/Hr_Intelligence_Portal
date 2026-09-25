"""Configuration health (docs/HRMS_COMPLETE_SPEC.txt Part 14 section 2; L-A3 "setup health
checklist on admin home"). Each issue says what is wrong in plain language, why it matters,
and links to the exact settings page that fixes it."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.comms import MessageTemplate, NotificationRule
from app.models.connection import Connection, ConnectionOAuthToken, ConnectionRoute
from app.models.user import User
from app.models.workflow import WorkflowDefinition
from app.platform.tenancy.context import TenantContext

# Purposes that features built in this platform actually send/receive through. A purpose
# counts as "needed" when the module that uses it is enabled.
_NEEDED_PURPOSES = {
    "email.outbound.default": None, "email.outbound.system": None,
    "email.inbound.negotiation_replies": "recruitment", "email.outbound.recruitment": "recruitment",
    "email.outbound.onboarding": "onboarding", "email.inbound.helpdesk": "helpdesk",
    "llm.resume_extraction": "recruitment", "llm.judgment": "performance", "llm.copilot": "copilot",
    "esign.offer_letters": "recruitment",
}


def _issue(severity: str, code: str, message: str, fix: str, fix_path: str, **extra) -> dict:
    return {"severity": severity, "code": code, "message": message, "fix": fix, "fix_path": fix_path, **extra}


def check(db: Session, tenant: TenantContext) -> dict:
    from app.platform.ai.governance import feature_enabled
    from app.platform.connectors.purposes import fallback_for
    from app.platform.modules import enabled_modules
    from app.platform.settings.resolver import SettingContext, SettingsService

    issues: list[dict] = []
    modules = enabled_modules(db, tenant)
    routed = {r.purpose for r in db.query(ConnectionRoute).filter(ConnectionRoute.tenant_id == tenant.tenant_id, ConnectionRoute.enabled.is_(True)).all()}

    def _is_routed(purpose: str) -> bool:
        seen = set()
        while purpose and purpose not in seen:
            if purpose in routed:
                return True
            seen.add(purpose)
            purpose = fallback_for(purpose)
        return False

    for purpose, module in _NEEDED_PURPOSES.items():
        if module and module not in modules:
            continue
        if purpose.startswith("llm.") and not SettingsService(db).get("ai.enabled", SettingContext(tenant=tenant)):
            continue
        if not _is_routed(purpose):
            issues.append(_issue("error" if purpose.startswith("email.outbound") else "warning", "UNROUTED_PURPOSE",
                                 f"Nothing is connected for '{purpose}'.", "Connect an account and route this purpose to it.", "/settings#connections", purpose=purpose))

    published = {(t.key, t.channel) for t in db.query(MessageTemplate).filter(MessageTemplate.tenant_id == tenant.tenant_id, MessageTemplate.status == "published").all()}
    published_keys = {k for k, _ in published}
    for rule in db.query(NotificationRule).filter(NotificationRule.tenant_id == tenant.tenant_id, NotificationRule.enabled.is_(True)).all():
        if rule.template_key not in published_keys:
            issues.append(_issue("error", "UNPUBLISHED_TEMPLATE", f"Notification rule '{rule.name}' uses template '{rule.template_key}', which isn't published.",
                                 "Publish the template or turn the rule off.", "/settings#communications", rule_id=str(rule.id)))

    for definition in db.query(WorkflowDefinition).filter(WorkflowDefinition.tenant_id == tenant.tenant_id, WorkflowDefinition.status == "published").all():
        nodes = (definition.graph_json or {}).get("nodes", {})
        for node_id, node in nodes.items():
            if node.get("type") == "approval" and not node.get("approvers"):
                issues.append(_issue("error", "WORKFLOW_NO_APPROVERS", f"Workflow '{definition.name}' has an approval step ('{node_id}') with no approvers.",
                                     "Add an approver rule to that step and republish.", "/settings#workflows", workflow_key=definition.key))

    mfa_required = SettingsService(db).get("iam.auth.mfa_required", SettingContext(tenant=tenant))
    no_mfa = [u for u in db.query(User).filter(User.tenant_id == tenant.tenant_id).all() if not u.mfa_totp_enrolled_at and not u.mfa_email_otp_enabled]
    admins_no_mfa = [u for u in no_mfa if u.role == "admin"]
    if admins_no_mfa:
        issues.append(_issue("error", "ADMIN_WITHOUT_2FA", f"{len(admins_no_mfa)} admin(s) haven't set up 2-step verification.",
                             "Ask them to enrol, then turn on 'Require 2-step verification'.", "/settings#security", count=len(admins_no_mfa)))
    if no_mfa and not mfa_required:
        issues.append(_issue("warning", "USERS_WITHOUT_2FA", f"{len(no_mfa)} user(s) sign in without 2-step verification, and it isn't required.",
                             "Turn on 'Require 2-step verification' once users have enrolled (decision C2).", "/settings#security", count=len(no_mfa)))

    soon = datetime.now(timezone.utc) + timedelta(days=7)
    for token_row in db.query(ConnectionOAuthToken).filter(ConnectionOAuthToken.tenant_id == tenant.tenant_id, ConnectionOAuthToken.expires_at.isnot(None),
                                                           ConnectionOAuthToken.expires_at < soon).all():
        connection = db.get(Connection, token_row.connection_id)
        if connection is not None and not token_row.refresh_secret_ref:
            issues.append(_issue("warning", "OAUTH_EXPIRING", f"The sign-in for '{connection.name}' expires {token_row.expires_at:%d %b %Y} and can't refresh itself.",
                                 "Reconnect the account.", "/settings#connections", connection_id=str(connection.id)))

    for connection in db.query(Connection).filter(Connection.tenant_id == tenant.tenant_id, Connection.status == "active").all():
        result = connection.last_test_result or {}
        if connection.last_tested_at is not None and result.get("success") is False:
            issues.append(_issue("warning", "CONNECTION_FAILING", f"'{connection.name}' failed its last test.", "Open the connection and re-test it.",
                                 "/settings#connections", connection_id=str(connection.id)))

    if "copilot" in modules and feature_enabled(db, tenant, "copilot.chat"):
        from app.models.intelligence import KnowledgeDocument

        if db.query(KnowledgeDocument).filter(KnowledgeDocument.tenant_id == tenant.tenant_id, KnowledgeDocument.status == "active").count() == 0:
            issues.append(_issue("info", "COPILOT_NO_KNOWLEDGE", "HR Copilot has no policy documents yet, so it will hand every policy question to the helpdesk.",
                                 "Upload your handbook and policies.", "/settings#copilot"))

    order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: order[i["severity"]])
    return {"healthy": not any(i["severity"] == "error" for i in issues), "issues": issues,
            "counts": {s: sum(1 for i in issues if i["severity"] == s) for s in order}}
