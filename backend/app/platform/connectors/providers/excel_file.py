"""excel_file provider (docs/HRMS_COMPLETE_SPEC.txt Part 3 section 2) -- the Interview
Scheduling tracker's Excel workbook path, as a connection instead of a bare settings
field. test_connection() reuses app/interview_scheduling/tracker.py's own
ensure_tracker_file (creates it if missing, validates/patches an existing one -- never
overwrites data), same behavior already exercised by the Settings page today."""

from pathlib import Path

from app.interview_scheduling.tracker import ensure_tracker_file, TrackerFileLockedError
from app.platform.connectors.capabilities import ProviderResult

PROVIDER_CODE = "excel_file"
CAPABILITIES = ("HrisSync",)
CONFIG_SCHEMA = {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}}
SECRET_FIELDS = ()


class ExcelFileAdapter:
    def __init__(self, config: dict, secrets: dict):
        self.config = config

    def test_connection(self) -> ProviderResult:
        try:
            summary = ensure_tracker_file(Path(self.config["path"]))
            return ProviderResult(success=True, raw=summary)
        except TrackerFileLockedError as exc:
            return ProviderResult(success=False, error=str(exc))
        except OSError as exc:
            return ProviderResult(success=False, error=str(exc))

    def health_check(self) -> ProviderResult:
        return ProviderResult(success=Path(self.config.get("path", "")).exists())
