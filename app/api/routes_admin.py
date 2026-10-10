from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_service, require_admin
from app.models import SYNC_ERROR, AgentMapping
from app.schemas import AdminStateRequest, AgentCreateRequest
from app.services.tasks import TaskService

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/agents")
def list_agents(service: TaskService = Depends(get_service)) -> dict:
    return {"agents": service.list_agents()}


@router.post("/agents", status_code=status.HTTP_201_CREATED)
def create_agent(payload: AgentCreateRequest, db: Session = Depends(get_db)) -> dict:
    agent = AgentMapping(
        name=payload.name,
        extension=payload.extension,
        asterisk_interface=payload.asterisk_interface,
        zammad_user_id=payload.zammad_user_id,
        queues=payload.queues,
        enabled=payload.enabled,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return {"id": agent.id}


@router.post("/agents/{agent_id}/reconcile")
def reconcile_agent(
    agent_id: int,
    service: TaskService = Depends(get_service),
) -> dict:
    agent = service.get_agent(agent_id)
    return service.reconcile(agent, actor="admin")


@router.post("/agents/{agent_id}/state")
def override_agent_state(
    agent_id: int,
    payload: AdminStateRequest,
    service: TaskService = Depends(get_service),
) -> dict:
    agent = service.get_agent(agent_id)
    return service.set_manual_state(
        agent,
        payload.manual_state,
        actor="admin",
        reason=payload.reason,
        override=payload.override,
    )


@router.get("/health")
def admin_health(service: TaskService = Depends(get_service)) -> dict:
    agents = service.list_agents()
    desynced = [a["id"] for a in agents if a["sync_status"] == SYNC_ERROR]
    return {"agents": len(agents), "desynced_agents": desynced}
