from sqlalchemy import Column, DateTime, Integer, Numeric, text

from app.core.database import Base


class ScreeningSettings(Base):
    """Singleton row (always id=1) holding admin-configurable screening thresholds.

    dashboard_min_score/dashboard_max_score control Part D's Candidates Dashboard
    auto-advance-to-'screened' threshold (see app/screening/service.py run_screening).
    A second, independent min/max pair for the Screening module's own
    auto-advance-to-interview-ready threshold (Part F) is added by a later migration --
    deliberately not both added up front, since they're two distinct settings owned by
    two distinct parts of this feature, not one shared control.
    """

    __tablename__ = "screening_settings"

    id = Column(Integer, primary_key=True)
    dashboard_min_score = Column(Numeric, nullable=False, server_default=text("60"))
    dashboard_max_score = Column(Numeric, nullable=False, server_default=text("100"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))
