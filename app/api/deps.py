from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.models import AgentMapping
from app.services.tasks import TaskService


def get_db(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_service(request: Request, db: Session = Depends(get_db)) -> TaskService:
    return TaskService(
        db=db,
        settings=request.app.state.settings,
        ami=request.app.state.ami_manager,
        zammad=request.app.state.zammad,
    )


def get_current_agent(
    request: Request,
    db: Session = Depends(get_db),
    x_agent_id: int = Header(..., alias="X-Agent-Id"),
) -> AgentMapping:
    agent = db.get(AgentMapping, x_agent_id)
    if agent is None or not agent.enabled:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown or disabled agent")
    return agent


def require_admin(x_role: str = Header("", alias="X-Role")) -> None:
    if x_role.lower() != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin role required")


AdminDep = Depends(require_admin)
