from sqlalchemy import Column, DateTime, Integer, Numeric, text

from app.core.database import Base


class ScreeningSettings(Base):
    """Singleton row (always id=1) holding admin-configurable screening thresholds.

    Two independent min/max pairs, each owned by a distinct part of this feature -- never
    one shared control, and always editable independently of each other (see
    app/screening/router.py update_settings' partial-update semantics):

    - dashboard_min_score/dashboard_max_score: Part D's Candidates Dashboard
      auto-advance-to-'screened' threshold (see app/screening/service.py run_screening).
    - interview_min_score/interview_max_score: Part F's Screening Dashboard threshold for
      whether a screened application is flagged "Interview ready" in the Screening List's
      Remarks column (see app/screening/service.py describe_interview_readiness). This is
      purely a computed indicator, never a status change -- advancing to interview_scheduled
      stays a fully human-driven decision (shortlisting + scheduling), same as every other
      pipeline transition past 'screened'.
    """

    __tablename__ = "screening_settings"

    id = Column(Integer, primary_key=True)
    dashboard_min_score = Column(Numeric, nullable=False, server_default=text("60"))
    dashboard_max_score = Column(Numeric, nullable=False, server_default=text("100"))
    interview_min_score = Column(Numeric, nullable=False, server_default=text("75"))
    interview_max_score = Column(Numeric, nullable=False, server_default=text("100"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))
