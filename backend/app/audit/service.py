import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def log_action(
    db: Session,
    entity_type: str,
    entity_id: Optional[uuid.UUID],
    action: str,
    actor: str,
    details: Optional[dict] = None,
) -> None:
    db.add(
        AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor=actor,
            details=details,
        )
    )
    db.commit()
