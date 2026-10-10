from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import IntegrationEvent


def payload_fingerprint(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def store_event(
    db: Session,
    source: str,
    payload: dict,
    external_event_id: str | None,
    status: str = "processed",
    result: dict | None = None,
) -> tuple[IntegrationEvent, bool]:
    event = IntegrationEvent(
        source=source,
        external_event_id=external_event_id,
        payload=payload,
        result=result,
        status=status,
    )
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(IntegrationEvent).where(IntegrationEvent.external_event_id == external_event_id)
        )
        if existing is None:
            raise
        return existing, False
    db.refresh(event)
    return event, True


def find_event(db: Session, external_event_id: str) -> IntegrationEvent | None:
    return db.scalar(select(IntegrationEvent).where(IntegrationEvent.external_event_id == external_event_id))
