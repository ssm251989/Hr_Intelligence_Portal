from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.bgv_document import BgvDocument
from app.models.candidate import Candidate
from app.models.comms import (
    BrandTheme,
    InboundMessage,
    MessageLayout,
    MessageTemplate,
    NotificationPreference,
    NotificationRule,
    OutboundMessage,
    SuppressionListEntry,
)
from app.models.connection import Connection, ConnectionAttempt, ConnectionOAuthToken, ConnectionRoute
from app.models.core_hr import (
    BusinessUnit,
    CostCenter,
    Department,
    Employee,
    EmployeeDocument,
    EmploymentRecord,
    ImportBatch,
    ImportRow,
    LegalEntity,
    LetterRecord,
    LetterTemplate,
    Location,
    Position,
)
from app.models.onboarding import (
    AssignmentRule,
    BgvCase,
    OnboardingPlan,
    OnboardingPlanTemplate,
    OnboardingTask,
    PreboardingCase,
    PreboardingDocument,
)
from app.models.performance import (
    CalibrationAudit,
    CalibrationEntry,
    CalibrationSession,
    CompensationBudget,
    CompensationCycle,
    CompensationProposal,
    CompensationRecord,
    Feedback,
    Goal,
    GoalCheckin,
    GoalLibraryItem,
    InternalApplication,
    InternalOpportunity,
    MeritMatrix,
    OneOnOne,
    RatingScale,
    Review,
    ReviewCycle,
    ReviewNomination,
    SalaryBand,
    SuccessionCandidate,
    SuccessionSlate,
    TalentProfile,
)
from app.models.service_desk import (
    Asset,
    AssetAllocation,
    AssetMaintenance,
    AssetRequest,
    BusinessCalendar,
    ClearanceItem,
    KbArticle,
    Separation,
    SlaPolicy,
    Ticket,
    TicketAssignmentRule,
    TicketComment,
    TicketQueue,
)
from app.models.hiring_team import JobHiringTeamMember
from app.models.hr_inbound_email import HrInboundEmail
from app.models.hr_integration import HrIntegration
from app.models.iam import (
    ActionToken,
    FieldSecurity,
    MagicLink,
    MfaChallenge,
    MfaRecoveryCode,
    PasswordHistory,
    RefreshToken,
    Role,
    RoleAssignment,
    UserDelegation,
    UserDevice,
)
from app.models.interview import Interview
from app.models.interview_confirmation_token import InterviewConfirmationToken
from app.models.interview_scheduling_settings import InterviewSchedulingSettings
from app.models.interviewer_availability import InterviewerAvailability
from app.models.job_role import JobRole
from app.models.local_import_settings import LocalImportSettings
from app.models.metadata import CustomFieldDef, FormLayout, FxRate, I18nOverride, MasterType, MasterValue, MetaForm, Sequence
from app.models.negotiation_token import NegotiationToken
from app.models.offer import Offer
from app.models.offer_component import OfferComponent
from app.models.pipeline import PipelineStage, PipelineTemplate
from app.models.prompt import PromptTemplate
from app.models.requisition import JobRequisition
from app.models.secret import Secret, SecretScope
from app.models.setting_value import SettingValue, SettingValueHistory
from app.models.user import User
from app.models.user_integration import UserIntegration
from app.models.workflow import WorkflowDefinition, WorkflowInstance, WorkflowStep, WorkflowTimer

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
    "BrandTheme",
    "Candidate",
    "InboundMessage",
    "MessageLayout",
    "MessageTemplate",
    "NotificationPreference",
    "NotificationRule",
    "OutboundMessage",
    "SuppressionListEntry",
    "Connection",
    "ConnectionAttempt",
    "ConnectionOAuthToken",
    "ConnectionRoute",
    "BusinessUnit",
    "CostCenter",
    "Department",
    "Employee",
    "EmployeeDocument",
    "EmploymentRecord",
    "ImportBatch",
    "ImportRow",
    "LegalEntity",
    "LetterRecord",
    "LetterTemplate",
    "Location",
    "Position",
    "ActionToken",
    "FieldSecurity",
    "MagicLink",
    "MfaChallenge",
    "MfaRecoveryCode",
    "PasswordHistory",
    "RefreshToken",
    "Role",
    "RoleAssignment",
    "UserDelegation",
    "UserDevice",
    "JobHiringTeamMember",
    "HrInboundEmail",
    "HrIntegration",
    "Interview",
    "InterviewConfirmationToken",
    "InterviewSchedulingSettings",
    "InterviewerAvailability",
    "JobRole",
    "LocalImportSettings",
    "CustomFieldDef",
    "FormLayout",
    "FxRate",
    "I18nOverride",
    "MasterType",
    "MasterValue",
    "MetaForm",
    "Sequence",
    "NegotiationToken",
    "Asset",
    "AssetAllocation",
    "AssetMaintenance",
    "AssetRequest",
    "BusinessCalendar",
    "ClearanceItem",
    "KbArticle",
    "Separation",
    "SlaPolicy",
    "Ticket",
    "TicketAssignmentRule",
    "TicketComment",
    "TicketQueue",
    "CalibrationAudit",
    "CalibrationEntry",
    "CalibrationSession",
    "CompensationBudget",
    "CompensationCycle",
    "CompensationProposal",
    "CompensationRecord",
    "Feedback",
    "Goal",
    "GoalCheckin",
    "GoalLibraryItem",
    "InternalApplication",
    "InternalOpportunity",
    "MeritMatrix",
    "OneOnOne",
    "RatingScale",
    "Review",
    "ReviewCycle",
    "ReviewNomination",
    "SalaryBand",
    "SuccessionCandidate",
    "SuccessionSlate",
    "TalentProfile",
    "AssignmentRule",
    "BgvCase",
    "OnboardingPlan",
    "OnboardingPlanTemplate",
    "OnboardingTask",
    "PreboardingCase",
    "PreboardingDocument",
    "Offer",
    "OfferComponent",
    "PipelineStage",
    "PipelineTemplate",
    "PromptTemplate",
    "JobRequisition",
    "Secret",
    "SecretScope",
    "SettingValue",
    "SettingValueHistory",
    "User",
    "UserIntegration",
    "WorkflowDefinition",
    "WorkflowInstance",
    "WorkflowStep",
    "WorkflowTimer",
]
