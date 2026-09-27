"""The dispatch pipeline (docs/HRMS_COMPLETE_SPEC.txt Part 4 section 3):
DomainEvent -> NotificationRuleMatcher -> RecipientResolver -> PreferenceFilter/
Suppression -> Renderer -> ConnectorRouter -> send -> outbound_messages status updates.

No live Celery worker is provisioned in this installation (same as Part 2's own
TenantTask -- task_always_eager runs it synchronously in-process) and no real
transactional outbox table exists yet (platform/events/ is a Part-2-section-E package
this build hasn't reached) -- dispatch_event() below calls the pipeline synchronously,
inline, rather than through a separate outbox-drain worker. Every send still goes through
the same outbound_messages log regardless (section 3's own "Direct sends ... still go
through the same log" requirement), which is the part that actually matters for audit/
resend/suppression -- the async delivery mechanism is the part deferred.
"""

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.comms import MessageTemplate, OutboundMessage
from app.platform.comms.quiet_hours import should_hold_for_digest
from app.platform.comms.recipients import RecipientResolver
from app.platform.comms.renderer import TemplateRenderError, VariablesValidationError, render_template
from app.platform.comms.rules import NotificationRuleMatcher
from app.platform.comms.suppression import filter_suppressed_and_opted_out
from app.platform.comms.templates import TemplateNotFoundError, get_published_template
from app.platform.connectors.registry import NotYetImplementedProviderError, get_provider
from app.platform.connectors.router import ConnectorRouter, NoConnectionForPurposeError
from app.platform.tenancy.context import TenantContext


def _get_adapter_and_secrets(db: Session, tenant: TenantContext, connection):
    spec = get_provider(connection.provider_code)
    if spec.adapter_cls is None:
        raise NotYetImplementedProviderError(f"{connection.provider_code} has no adapter implementation yet")
    secrets: dict = {}
    if connection.secret_ref:
        import json

        from app.models.secret import Secret, SecretScope
        from app.platform.secrets.store import get_secret_store

        store = get_secret_store(db, Secret, SecretScope, str(tenant.tenant_id))
        secrets = json.loads(store.get(connection.secret_ref))
    return spec.adapter_cls(connection.config_json or {}, secrets)


def send(
    db: Session, tenant: TenantContext, *, template_key: str, to: list[str], ctx: dict, purpose: str,
    cc: Optional[list[str]] = None, bcc: Optional[list[str]] = None, channel: str = "email", locale: str = "en",
    related_entity_type: Optional[str] = None, related_entity_id: Optional[UUID] = None,
    attachments: Optional[list[dict]] = None, rule_id: Optional[UUID] = None,
) -> OutboundMessage:
    """The direct-send entry point (section 3: `comms.send(template_key, to, ctx,
    purpose)`) -- OTP, password reset, or any call site that isn't itself an event a rule
    should match. Always logs to outbound_messages, whether the render/route/send below
    succeeds or fails, so the log reflects a real attempt either way."""
    to = filter_suppressed_and_opted_out(db, tenant, to, channel=channel, event_group=template_key)

    outbound = OutboundMessage(
        tenant_id=tenant.tenant_id, rule_id=rule_id, channel=channel, purpose=purpose,
        to_addresses=to, cc_addresses=cc or [], bcc_addresses=bcc or [], status="queued",
        related_entity_type=related_entity_type, related_entity_id=related_entity_id,
    )
    db.add(outbound)
    db.commit()
    db.refresh(outbound)

    if not to:
        outbound.status = "suppressed"
        outbound.error = "Every recipient is suppressed or opted out"
        db.commit()
        return outbound

    try:
        template = get_published_template(db, tenant.tenant_id, template_key, channel=channel, locale=locale)
        outbound.template_id = template.id
        outbound.template_version = template.version

        rendered = render_template(
            subject_tpl=template.subject_tpl, html_tpl=template.html_tpl, text_tpl=template.text_tpl,
            variables_schema=template.variables_schema_json, context=ctx,
        )
        if channel == "email" and rendered["html"]:
            from app.platform.comms.theme import wrap_email_html

            rendered["html"] = wrap_email_html(db, tenant, rendered["html"])  # Part 17.11: logo / name header
        outbound.subject = rendered["subject"]
        outbound.body_ref = rendered["html"] or rendered["text"]

        resolved = ConnectorRouter(db).resolve(purpose, ctx)
        outbound.connection_id = resolved.connection.id
        adapter = _get_adapter_and_secrets(db, tenant, resolved.connection)

        from app.platform.connectors.capabilities import OutboundEmail

        result = adapter.send(OutboundEmail(
            to=to, cc=cc, bcc=bcc, subject=rendered["subject"], body_text=rendered["text"],
            body_html=rendered["html"], attachments=attachments,
        ))
        outbound.attempts += 1
        if result.success:
            outbound.status = "sent"
            outbound.provider_message_id = result.provider_message_id
            outbound.sent_at = datetime.now(timezone.utc)
        else:
            outbound.status = "failed"
            outbound.error = result.error
    except (TemplateNotFoundError, VariablesValidationError, TemplateRenderError, NoConnectionForPurposeError, NotYetImplementedProviderError) as exc:
        outbound.status = "failed"
        outbound.error = str(exc)

    db.commit()
    db.refresh(outbound)
    return outbound


def dispatch_event(db: Session, tenant: TenantContext, event_type: str, event_ctx: dict) -> list[OutboundMessage]:
    """The rule-driven half of the pipeline -- every enabled, condition-passing
    notification_rules row for this event_type fires its own send()."""
    matcher = NotificationRuleMatcher(db)
    rules = matcher.match(tenant, event_type, event_ctx)
    resolver = RecipientResolver(db, tenant)

    results: list[OutboundMessage] = []
    for rule in rules:
        recipients = resolver.resolve(rule.recipients_json, event_ctx)
        if not recipients:
            continue
        for channel in rule.channels or ["email"]:
            if should_hold_for_digest(rule.digest_mode):
                # Held for the (not-yet-built) digest-compilation job -- see
                # quiet_hours.py's own module docstring for why this only queues rather
                # than actually sending, same as a real "batch these, don't send
                # one-by-one" digest would need to.
                held = OutboundMessage(
                    tenant_id=tenant.tenant_id, rule_id=rule.id, channel=channel,
                    purpose=event_ctx.get("purpose", f"email.outbound.{event_type}"),
                    to_addresses=recipients, status="queued",
                )
                db.add(held)
                db.commit()
                db.refresh(held)
                results.append(held)
                continue
            results.append(send(
                db, tenant, template_key=rule.template_key, to=recipients, ctx=event_ctx,
                purpose=event_ctx.get("purpose", f"email.outbound.{event_type}"), channel=channel,
                rule_id=rule.id,
            ))
    return results
