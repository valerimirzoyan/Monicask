from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.api.deps import get_current_agent, get_service
from app.models import AgentMapping
from app.schemas import (
    ActionResultResponse,
    CompleteRequest,
    ContactLookupRequest,
    CreateTicketRequest,
    SimulateCallRequest,
    StartRequest,
)
from app.services.tasks import TaskService

router = APIRouter(tags=["tickets"])


@router.post("/api/tickets/{ticket_id}/start", response_model=ActionResultResponse)
def start_ticket(
    ticket_id: str,
    payload: StartRequest,
    agent: AgentMapping = Depends(get_current_agent),
    service: TaskService = Depends(get_service),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict:
    result = service.start(agent, ticket_id, payload.work_mode, actor=f"agent:{agent.id}", idem_key=idempotency_key)
    return {
        "session_id": result.session.id,
        "ticket_id": result.session.ticket_id,
        "work_mode": result.session.work_mode,
        "replayed": result.replayed,
        "state": result.state,
    }


@router.post("/api/tickets/{ticket_id}/complete", response_model=ActionResultResponse)
def complete_ticket(
    ticket_id: str,
    payload: CompleteRequest | None = None,
    agent: AgentMapping = Depends(get_current_agent),
    service: TaskService = Depends(get_service),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict:
    result = service.complete(agent, ticket_id, actor=f"agent:{agent.id}", idem_key=idempotency_key)
    return {
        "session_id": result.session.id,
        "ticket_id": result.session.ticket_id,
        "work_mode": result.session.work_mode,
        "replayed": result.replayed,
        "state": result.state,
    }


@router.post("/api/tickets")
def create_ticket(
    payload: CreateTicketRequest,
    agent: AgentMapping = Depends(get_current_agent),
    service: TaskService = Depends(get_service),
) -> dict:
    return service.create_ticket(
        subject=payload.subject,
        body=payload.description,
        customer=payload.customer,
        priority=payload.priority,
        actor=f"agent:{agent.id}",
    )


@router.post("/api/contacts/lookup")
def lookup_contact(
    payload: ContactLookupRequest,
    agent: AgentMapping = Depends(get_current_agent),
    service: TaskService = Depends(get_service),
) -> dict:
    return service.lookup_contact(payload.number)


@router.post("/api/dev/simulate-call")
def simulate_call(
    request: Request,
    payload: SimulateCallRequest,
    agent: AgentMapping = Depends(get_current_agent),
) -> dict:
    if request.app.state.settings.environment not in ("dev", "test"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not available")
    call = request.app.state.call_store.push(payload.number, payload.extension or agent.extension)
    return {"id": call.id, "number": call.number, "extension": call.extension}
