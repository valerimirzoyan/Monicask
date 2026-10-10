from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services import audit
from app.services.events import payload_fingerprint, store_event

router = APIRouter(prefix="/api/integrations/zammad", tags=["integrations"])


@router.post("/webhook")
async def zammad_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_webhook_token: str | None = Header(None, alias="X-Webhook-Token"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict:
    raw = await request.body()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty body")

    expected = request.app.state.settings.webhook_secret
    if expected and x_webhook_token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid webhook token")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid JSON") from exc
    if not isinstance(payload, dict):
        payload = {"data": payload}

    external_event_id = f"zammad:{idempotency_key or payload_fingerprint(payload)}"
    event, created = store_event(db, source="zammad", payload=payload, external_event_id=external_event_id)

    if created:
        audit.record(
            db,
            actor="zammad",
            action="webhook.received",
            subject_type="integration_event",
            subject_id=str(event.id),
            detail={"event": payload.get("event") or payload.get("type")},
        )
        db.commit()

    return {"deduplicated": not created, "event_id": event.id, "external_event_id": external_event_id}
