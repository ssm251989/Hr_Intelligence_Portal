from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.bgv_document import BgvDocument
from app.models.candidate import Candidate
from app.models.hr_inbound_email import HrInboundEmail
from app.models.hr_integration import HrIntegration
from app.models.interview import Interview
from app.models.interview_confirmation_token import InterviewConfirmationToken
from app.models.interview_scheduling_settings import InterviewSchedulingSettings
from app.models.job_role import JobRole
from app.models.local_import_settings import LocalImportSettings
from app.models.negotiation_token import NegotiationToken
from app.models.offer import Offer
from app.models.screening_settings import ScreeningSettings
from app.models.secret import Secret, SecretScope
from app.models.setting_value import SettingValue, SettingValueHistory
from app.models.user import User
from app.models.user_integration import UserIntegration

# Every model class must be imported here, even one no code elsewhere in this module ever
# references by name -- Part 2's own tenant migration (30cb603c4306) found the hard way that
# `alembic/env.py`'s `from app.models import *` is autogenerate's ONLY view of the schema;
# a model missing from __all__ reads to it as a table that no longer exists, generating a
# silent DROP TABLE the next time anyone runs --autogenerate. Previously true for
# InterviewConfirmationToken/InterviewSchedulingSettings/LocalImportSettings below (real,
# populated tables that happened to only ever be imported directly by their own
# routers/services, never through this file) until this fix.
__all__ = [
    "Application",
    "AuditLog",
    "BgvDocument",
    "Candidate",
    "HrInboundEmail",
    "HrIntegration",
    "Interview",
    "InterviewConfirmationToken",
    "InterviewSchedulingSettings",
    "JobRole",
    "LocalImportSettings",
    "NegotiationToken",
    "Offer",
    "ScreeningSettings",
    "Secret",
    "SecretScope",
    "SettingValue",
    "SettingValueHistory",
    "User",
    "UserIntegration",
]
