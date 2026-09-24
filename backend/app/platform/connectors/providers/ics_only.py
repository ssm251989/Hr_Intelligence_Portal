"""ics_only provider (docs/HRMS_COMPLETE_SPEC.txt Part 3 section 2) -- no external
account, generates a .ics attachment only. Thin wrapper around
app/integrations/ics.py's build_interview_ics (this app's current, already-tested
behavior) -- not reimplemented here."""

from app.integrations.ics import build_interview_ics
from app.platform.connectors.capabilities import ProviderResult

PROVIDER_CODE = "ics_only"
CAPABILITIES = ("IcsOnlyCalendar",)
CONFIG_SCHEMA = {"type": "object", "properties": {}}
SECRET_FIELDS = ()


class IcsOnlyAdapter:
    def __init__(self, config: dict, secrets: dict):
        self.config = config

    def build_ics(self, **kwargs) -> bytes:
        return build_interview_ics(**kwargs)

    def test_connection(self) -> ProviderResult:
        return ProviderResult(success=True)  # no external account -- nothing to test

    def health_check(self) -> ProviderResult:
        return ProviderResult(success=True)
