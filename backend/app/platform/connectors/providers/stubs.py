"""Providers registered in the catalog (real config schema + capabilities, so they show up
correctly in GET /api/v1/connectors/providers and a client can see what a connection would
need) but with no adapter_cls yet -- `ConnectorRouter`/the connections API raise
`NotYetImplementedProviderError` for any of these rather than crash. Two groups, per
docs/HRMS_COMPLETE_SPEC.txt Part 3 section 2:

"Build now" but deferred here (needs either a live external service this dev environment
has no credentials/instance for, or a per-user OAuth token flow more involved than the
single-secret_ref pattern platform/secrets already wires up -- see docs/build_log.md's own
Part 3 note): google_meet, teams_meeting, zoom, docusign, leegality, s3_compatible,
openai_compatible, csv_sftp, linkedin_jobs, naukri, indeed, bgv_generic_webhook.
docusign/linkedin_jobs already have real, working, per-user-OAuth integration code in this
app (app/integrations/docusign.py, linkedin.py) -- NOT migrated onto this framework yet;
their config schema below documents the exact real endpoints that existing code uses.

"Later": microsoft_graph_mail, gmail_api, amazon_ses, sendgrid, twilio_sms, msg91,
meta_whatsapp_cloud, slack, teams_chat, google_calendar, microsoft_calendar, digio,
authbridge, idfy, saml_generic, oidc_generic, okta, azure_ad,
google_workspace_directory -- interface + minimal config schema only, per spec.
"""

from app.platform.connectors.registry import ProviderSpec, register_provider

_EMPTY_SCHEMA = {"type": "object", "properties": {}}

_DEFERRED_BUILD_NOW = (
    ProviderSpec(code="google_meet", capabilities=("VideoMeeting", "CalendarProvider"), config_schema=_EMPTY_SCHEMA, oauth={"auth_url": "https://accounts.google.com/o/oauth2/v2/auth", "token_url": "https://oauth2.googleapis.com/token", "scopes": ["https://www.googleapis.com/auth/calendar.events"]}),
    ProviderSpec(code="teams_meeting", capabilities=("VideoMeeting",), config_schema=_EMPTY_SCHEMA, oauth={"auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize", "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token", "scopes": ["OnlineMeetings.ReadWrite"]}),
    ProviderSpec(code="zoom", capabilities=("VideoMeeting",), config_schema=_EMPTY_SCHEMA, oauth={"auth_url": "https://zoom.us/oauth/authorize", "token_url": "https://zoom.us/oauth/token", "scopes": ["meeting:write"]}),
    ProviderSpec(code="docusign", capabilities=("ESignProvider",), config_schema={"type": "object", "properties": {"account_id": {"type": "string"}, "auth_base_url": {"type": "string"}, "api_base_url": {"type": "string"}}}, secret_fields=("integration_key", "secret_key"), oauth={"auth_url": "https://account-d.docusign.com/oauth/auth", "token_url": "https://account-d.docusign.com/oauth/token", "scopes": ["signature"]}),
    ProviderSpec(code="leegality", capabilities=("ESignProvider",), config_schema=_EMPTY_SCHEMA, secret_fields=("api_key",)),
    ProviderSpec(code="s3_compatible", capabilities=("StorageProvider",), config_schema={"type": "object", "required": ["bucket", "endpoint_url", "region"], "properties": {"bucket": {"type": "string"}, "endpoint_url": {"type": "string"}, "region": {"type": "string"}}}, secret_fields=("access_key_id", "secret_access_key")),
    ProviderSpec(code="openai_compatible", capabilities=("LlmProvider",), config_schema={"type": "object", "required": ["base_url"], "properties": {"base_url": {"type": "string"}}}, secret_fields=("api_key",)),
    ProviderSpec(code="csv_sftp", capabilities=("HrisSync",), config_schema={"type": "object", "required": ["host", "port", "remote_path"], "properties": {"host": {"type": "string"}, "port": {"type": "integer", "default": 22}, "remote_path": {"type": "string"}}}, secret_fields=("username", "password_or_key")),
    ProviderSpec(code="linkedin_jobs", capabilities=("JobBoardPublisher",), config_schema=_EMPTY_SCHEMA, secret_fields=("client_id", "client_secret"), oauth={"auth_url": "https://www.linkedin.com/oauth/v2/authorization", "token_url": "https://www.linkedin.com/oauth/v2/accessToken", "scopes": ["w_member_social"]}),
    ProviderSpec(code="naukri", capabilities=("JobBoardPublisher",), config_schema=_EMPTY_SCHEMA, secret_fields=("api_key",)),
    ProviderSpec(code="indeed", capabilities=("JobBoardPublisher",), config_schema=_EMPTY_SCHEMA, secret_fields=("api_key",)),
    ProviderSpec(code="bgv_generic_webhook", capabilities=("BgvProvider", "WebhookTarget"), config_schema={"type": "object", "required": ["url"], "properties": {"url": {"type": "string", "format": "uri"}}}, secret_fields=("signing_secret",)),
)

_LATER = (
    ("microsoft_graph_mail", ("EmailSender", "EmailReceiver")),
    ("gmail_api", ("EmailSender", "EmailReceiver")),
    ("amazon_ses", ("EmailSender",)),
    ("sendgrid", ("EmailSender",)),
    ("twilio_sms", ("SmsSender",)),
    ("msg91", ("SmsSender",)),
    ("meta_whatsapp_cloud", ("WhatsAppSender",)),
    ("slack", ("ChatNotifier",)),
    ("teams_chat", ("ChatNotifier",)),
    ("google_calendar", ("CalendarProvider",)),
    ("microsoft_calendar", ("CalendarProvider",)),
    ("digio", ("BgvProvider",)),
    ("authbridge", ("BgvProvider",)),
    ("idfy", ("BgvProvider",)),
    ("saml_generic", ("IdentityProvider",)),
    ("oidc_generic", ("IdentityProvider",)),
    ("okta", ("IdentityProvider",)),
    ("azure_ad", ("IdentityProvider",)),
    ("google_workspace_directory", ("HrisSync",)),
)


def register_all() -> None:
    for spec in _DEFERRED_BUILD_NOW:
        register_provider(spec, replace=True)
    for code, capabilities in _LATER:
        register_provider(ProviderSpec(code=code, capabilities=capabilities, config_schema=_EMPTY_SCHEMA), replace=True)
