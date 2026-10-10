from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import get_current_agent, get_service
from app.models import MANUAL_BREAK, MANUAL_OFFLINE, MANUAL_READY, AgentMapping
from app.schemas import (
    ManualStateRequest,
    StateResponse,
    TasksResponse,
)
from app.services.tasks import TaskService

router = APIRouter(prefix="/api/agents/me", tags=["agent"])


@router.get("/state", response_model=StateResponse)
def get_state(
    agent: AgentMapping = Depends(get_current_agent),
    service: TaskService = Depends(get_service),
) -> dict:
    service.refresh(agent)
    return service.state_payload(agent)


@router.get("/tasks", response_model=TasksResponse)
def get_tasks(
    agent: AgentMapping = Depends(get_current_agent),
    service: TaskService = Depends(get_service),
) -> dict:
    return service.tasks_payload(agent)


@router.get("/tickets")
def get_tickets(
    agent: AgentMapping = Depends(get_current_agent),
    service: TaskService = Depends(get_service),
) -> dict:
    return service.tickets_with_sessions(agent)


@router.get("/audit")
def get_audit(
    agent: AgentMapping = Depends(get_current_agent),
    service: TaskService = Depends(get_service),
) -> dict:
    return {"events": service.recent_audit(agent)}


@router.get("/calls")
def get_calls(
    request: Request,
    agent: AgentMapping = Depends(get_current_agent),
) -> dict:
    calls = request.app.state.call_store.recent(extension=agent.extension)
    return {
        "calls": [
            {
                "id": c.id,
                "number": c.number,
                "extension": c.extension,
                "direction": c.direction,
                "state": c.state,
                "started_at": c.started_at,
            }
            for c in calls
        ]
    }


@router.post("/break", response_model=StateResponse)
def set_break(
    payload: ManualStateRequest,
    agent: AgentMapping = Depends(get_current_agent),
    service: TaskService = Depends(get_service),
) -> dict:
    return service.set_manual_state(agent, MANUAL_BREAK, actor=f"agent:{agent.id}", reason=payload.reason)


@router.post("/ready", response_model=StateResponse)
def set_ready(
    payload: ManualStateRequest,
    agent: AgentMapping = Depends(get_current_agent),
    service: TaskService = Depends(get_service),
) -> dict:
    return service.set_manual_state(agent, MANUAL_READY, actor=f"agent:{agent.id}", reason=payload.reason)


@router.post("/offline", response_model=StateResponse, status_code=status.HTTP_200_OK)
def set_offline(
    payload: ManualStateRequest,
    agent: AgentMapping = Depends(get_current_agent),
    service: TaskService = Depends(get_service),
) -> dict:
    return service.set_manual_state(agent, MANUAL_OFFLINE, actor=f"agent:{agent.id}", reason=payload.reason)
