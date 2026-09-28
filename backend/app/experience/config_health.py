"""Configuration health (docs/HRMS_COMPLETE_SPEC.txt Part 14 section 2; L-A3 "setup health
checklist on admin home"). Each issue says what is wrong in plain language, why it matters,
and links to the exact settings page that fixes it."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.comms import MessageTemplate, NotificationRule
from app.models.connection import Connection, ConnectionOAuthToken
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


def _issue(severity: str, code: str, message: str, fix: str, fix_path: str, action_label: str = "Fix it", **extra) -> dict:
    # Part 16.2: `message` is plain words (what + why), `action_label` is the one-click fix button.
    return {"severity": severity, "code": code, "message": message, "fix": fix, "fix_path": fix_path, "action_label": action_label, **extra}


def check(db: Session, tenant: TenantContext) -> dict:
    from app.platform.ai.governance import feature_enabled
    from app.platform.comms.catalog import describe_template, purpose_health
    from app.platform.modules import enabled_modules
    from app.platform.settings.resolver import SettingContext, SettingsService

    issues: list[dict] = []
    modules = enabled_modules(db, tenant)

    from app.platform.connectors.router import ConnectorRouter

    resolver = ConnectorRouter(db)

    def _is_routed(purpose: str) -> bool:
        # Part 18.2/18.3: ask the router itself (fallback chain + the one company mailbox)
        if resolver.try_resolve(purpose) is not None:
            return True
        if purpose.startswith("esign."):
            return esign_connected(db, tenant)
        return False

    for purpose, module in _NEEDED_PURPOSES.items():
        if module and module not in modules:
            continue
        if purpose.startswith("llm.") and not SettingsService(db).get("ai.enabled", SettingContext(tenant=tenant)):
            continue
        if not _is_routed(purpose):
            message, label, path = purpose_health(purpose)
            issues.append(_issue("error" if purpose.startswith("email.outbound") else "warning", "UNROUTED_PURPOSE",
                                 message, "Connect the account once; everything that needs it starts working.", path, label, purpose=purpose))

    published = {(t.key, t.channel) for t in db.query(MessageTemplate).filter(MessageTemplate.tenant_id == tenant.tenant_id, MessageTemplate.status == "published").all()}
    published_keys = {k for k, _ in published}
    for rule in db.query(NotificationRule).filter(NotificationRule.tenant_id == tenant.tenant_id, NotificationRule.enabled.is_(True)).all():
        if rule.template_key not in published_keys:
            name = describe_template(rule.template_key)["name"]
            issues.append(_issue("error", "UNPUBLISHED_TEMPLATE", f"The \"{name}\" email isn't ready yet, so \"{rule.name}\" can't send it.",
                                 "Open the email, check the wording and publish it - or switch that notification off.",
                                 "/settings/communication/templates", "Open the email", rule_id=str(rule.id)))

    for definition in db.query(WorkflowDefinition).filter(WorkflowDefinition.tenant_id == tenant.tenant_id, WorkflowDefinition.status == "published").all():
        nodes = (definition.graph_json or {}).get("nodes", {})
        for node_id, node in nodes.items():
            if node.get("type") == "approval" and not node.get("approvers"):
                issues.append(_issue("error", "WORKFLOW_NO_APPROVERS", f"\"{definition.name}\" has an approval step with nobody to approve it.",
                                     "Choose who approves that step, then save.", "/settings/automation/approvals", "Choose approvers", workflow_key=definition.key))

    from app.platform.iam.mfa import is_available as two_step_available

    mfa_required = SettingsService(db).get("iam.auth.mfa_required", SettingContext(tenant=tenant))
    no_mfa = [] if not two_step_available(db, tenant) else [  # Part 18.1: no 2-step warnings while it is off
        u for u in db.query(User).filter(User.tenant_id == tenant.tenant_id).all() if not u.mfa_totp_enrolled_at and not u.mfa_email_otp_enabled]
    admins_no_mfa = [u for u in no_mfa if u.role == "admin"]
    if admins_no_mfa:
        n = len(admins_no_mfa)
        issues.append(_issue("error", "ADMIN_WITHOUT_2FA", f"{n} admin{'s' if n != 1 else ''} sign in without 2-step verification.",
                             "Admins can change everything, so their accounts need the extra code.", "/settings/people/two-step",
                             "Invite them to set it up", count=n))
    if no_mfa and not mfa_required:
        n = len(no_mfa)
        issues.append(_issue("warning", "USERS_WITHOUT_2FA", f"{n} {'people sign' if n != 1 else 'person signs'} in without 2-step verification.",
                             "Invite them to set it up; once they have, switch on \"Require 2-step verification\".", "/settings/people/two-step",
                             "Invite them to set it up", count=n))

    soon = datetime.now(timezone.utc) + timedelta(days=7)
    for token_row in db.query(ConnectionOAuthToken).filter(ConnectionOAuthToken.tenant_id == tenant.tenant_id, ConnectionOAuthToken.expires_at.isnot(None),
                                                           ConnectionOAuthToken.expires_at < soon).all():
        connection = db.get(Connection, token_row.connection_id)
        if connection is not None and not token_row.refresh_secret_ref:
            issues.append(_issue("warning", "OAUTH_EXPIRING", f"The connection to {connection.name} stops working on {token_row.expires_at:%d %b %Y}.",
                                 "Reconnect it before then so emails and calendars keep working.", "/settings/integrations", "Reconnect",
                                 connection_id=str(connection.id)))

    for connection in db.query(Connection).filter(Connection.tenant_id == tenant.tenant_id, Connection.status.in_(("active", "error"))).all():
        result = connection.last_test_result or {}
        if connection.status == "error" or (connection.last_tested_at is not None and result.get("success") is False):
            issues.append(_issue("warning", "CONNECTION_FAILING", f"{connection.name} isn't working - its last check failed.",
                                 f"{result.get('error') or 'Open it, check the details and test again.'}", "/settings/integrations/connections",
                                 "Check connection", connection_id=str(connection.id)))
        elif connection.last_tested_at is None:  # Part 18.3: "connected" means connected AND tested
            issues.append(_issue("info", "CONNECTION_NOT_TESTED", f"{connection.name} hasn't been tested yet.",
                                 "Press \"Re-check now\" (or Test on the connection) to make sure it works.", "/settings/integrations/connections",
                                 "Test it", connection_id=str(connection.id)))

    if "copilot" in modules and feature_enabled(db, tenant, "copilot.chat"):
        from app.models.intelligence import KnowledgeDocument

        if db.query(KnowledgeDocument).filter(KnowledgeDocument.tenant_id == tenant.tenant_id, KnowledgeDocument.status == "active").count() == 0:
            issues.append(_issue("info", "COPILOT_NO_KNOWLEDGE", "The HR assistant has no policy documents yet, so it sends every policy question to the helpdesk.",
                                 "Upload your handbook and policies so it can answer.", "/settings/integrations/ai", "Upload policies"))

    order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: order[i["severity"]])
    return {"healthy": not any(i["severity"] == "error" for i in issues), "issues": issues,
            "counts": {s: sum(1 for i in issues if i["severity"] == s) for s in order}}


def esign_connected(db: Session, tenant: TenantContext) -> bool:
    """Part 18.3: e-sign is connected when a company e-sign connection is routed, OR the app has
    DocuSign keys and at least one person in this company has signed in to DocuSign (offers are
    sent through that person's DocuSign account -- app/integrations/docusign.py)."""
    from app.core.config import settings as app_settings
    from app.models.user_integration import UserIntegration

    if not getattr(app_settings, "DOCUSIGN_INTEGRATION_KEY", None):
        return False
    return db.query(UserIntegration.id).filter(UserIntegration.tenant_id == tenant.tenant_id, UserIntegration.provider == "docusign").first() is not None


def recheck(db: Session, tenant: TenantContext) -> dict:
    """Part 18.3 "Re-check now": really test every company connection (records the result and
    time; a failed test does not switch the connection off), then return the fresh check."""
    from datetime import datetime as _dt, timezone as _tz

    from app.platform.connectors.api_router import _build_adapter

    tested = []
    for connection in db.query(Connection).filter(Connection.tenant_id == tenant.tenant_id, Connection.status.in_(("active", "error"))).all():
        try:
            result = _build_adapter(connection, db).test_connection()
            ok, error = bool(result.success), result.error
        except Exception as exc:  # noqa: BLE001 -- a provider that can't be tested is reported, not fatal
            ok, error = False, str(exc)[:300]
        connection.last_tested_at = _dt.now(_tz.utc)
        connection.last_test_result = {"success": ok, "error": error}
        if ok and connection.status == "error":
            connection.status = "active"
        tested.append({"connection": connection.name, "provider": connection.provider_code, "ok": ok, "error": error})
    db.commit()
    return {**check(db, tenant), "tested": tested, "checked_at": _dt.now(_tz.utc).isoformat()}
