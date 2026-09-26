"""Registers every provider adapter in the catalog (platform/connectors/registry.py).
Call register_all() once at app startup (idempotent)."""

from app.platform.connectors.registry import ProviderSpec, register_provider

_registered = False


def register_all() -> None:
    global _registered
    if _registered:
        return

    from app.platform.connectors.providers import anthropic_provider, excel_file, generic_webhook, ics_only, imap, local_disk, nominatim, smtp, stubs
    from app.platform.connectors.providers.anthropic_provider import AnthropicAdapter
    from app.platform.connectors.providers.excel_file import ExcelFileAdapter
    from app.platform.connectors.providers.generic_webhook import GenericWebhookAdapter
    from app.platform.connectors.providers.ics_only import IcsOnlyAdapter
    from app.platform.connectors.providers.imap import ImapAdapter
    from app.platform.connectors.providers.local_disk import LocalDiskAdapter
    from app.platform.connectors.providers.nominatim import NominatimAdapter
    from app.platform.connectors.providers.smtp import SmtpAdapter

    for module, adapter_cls in (
        (smtp, SmtpAdapter), (imap, ImapAdapter), (ics_only, IcsOnlyAdapter),
        (anthropic_provider, AnthropicAdapter), (excel_file, ExcelFileAdapter),
        (local_disk, LocalDiskAdapter), (generic_webhook, GenericWebhookAdapter),
        (nominatim, NominatimAdapter),
    ):
        register_provider(
            ProviderSpec(
                code=module.PROVIDER_CODE, capabilities=module.CAPABILITIES,
                config_schema=module.CONFIG_SCHEMA, secret_fields=module.SECRET_FIELDS,
                adapter_cls=adapter_cls,
            ),
            replace=True,
        )
    stubs.register_all()
    _registered = True
