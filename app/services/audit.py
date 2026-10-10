from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AuditLog


def record(
    db: Session,
    actor: str,
    action: str,
    subject_type: str = "",
    subject_id: str = "",
    detail: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor=actor,
        action=action,
        subject_type=subject_type,
        subject_id=str(subject_id),
        detail=detail or {},
    )
    db.add(entry)
    return entry
