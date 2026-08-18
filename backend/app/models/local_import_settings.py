from sqlalchemy import Column, DateTime, Integer, Text, text

from app.core.database import Base


class LocalImportSettings(Base):
    """Singleton row (always id=1) holding Part G's configurable ready-to-upload/already-
    uploaded root paths -- absolute paths on the server machine, set once via the "Import
    from Source" wizard's Local Import configure step (see app/local_import/router.py).
    Both start null (unconfigured) until a recruiter sets them; the scheduled scan
    (app/local_import/service.py) no-ops with nothing to do until they're set.

    Deliberately its own table, not folded into screening_settings -- that table is scoped
    to screening score thresholds, a completely unrelated concern from where local-import's
    folders live on disk.
    """

    __tablename__ = "local_import_settings"

    id = Column(Integer, primary_key=True)
    ready_to_upload_root = Column(Text, nullable=True)
    already_uploaded_root = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))
