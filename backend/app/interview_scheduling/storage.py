from sqlalchemy.orm import Session

from app.models.interview_scheduling_settings import InterviewSchedulingSettings


def get_interview_scheduling_settings(db: Session) -> InterviewSchedulingSettings:
    """The singleton settings row (id=1), seeded by migration e2f5b8c1a9d3. Defensively
    creates it if somehow missing (e.g. a test DB that ran migrations before this table
    existed) rather than crashing outright."""
    settings_row = db.get(InterviewSchedulingSettings, 1)
    if settings_row is None:
        settings_row = InterviewSchedulingSettings(id=1)
        db.add(settings_row)
        db.commit()
        db.refresh(settings_row)
    return settings_row
