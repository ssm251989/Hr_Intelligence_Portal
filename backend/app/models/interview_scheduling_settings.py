from sqlalchemy import Column, DateTime, Integer, Text, text

from app.core.database import Base
from app.platform.tenancy.mixins import TenantOwned


class InterviewSchedulingSettings(Base, TenantOwned):
    """Singleton row (always id=1) holding the Interview Scheduling automation's
    configurable Excel tracker path -- an absolute path on the server machine to a
    workbook with an "Interviewer Pool" sheet and an "Interview Log" sheet (see
    app/interview_scheduling/tracker.py), set once via the Settings page. Null until a
    recruiter sets it; app/interview_scheduling/service.py has nothing to do until then.

    Same singleton-row pattern as LocalImportSettings/ScreeningSettings -- one small,
    rarely-changed config row, not worth its own multi-row table.
    """

    __tablename__ = "interview_scheduling_settings"

    id = Column(Integer, primary_key=True)
    tracker_path = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))
