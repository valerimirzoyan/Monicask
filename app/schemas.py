from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class StartRequest(BaseModel):
    work_mode: Literal["blocking", "background"] = Field(
        description="blocking pauses the agent in managed queues, background keeps them available"
    )


class CompleteRequest(BaseModel):
    note: str | None = None


class ManualStateRequest(BaseModel):
    reason: str = ""


class AdminStateRequest(BaseModel):
    manual_state: Literal["ready", "break", "offline"]
    reason: str = ""
    override: bool = True


class AgentCreateRequest(BaseModel):
    name: str = ""
    extension: str
    asterisk_interface: str
    zammad_user_id: int | None = None
    queues: list[str] = Field(default_factory=list)
    enabled: bool = True


class ActionResultResponse(BaseModel):
    session_id: int
    ticket_id: str
    work_mode: str
    replayed: bool
    state: dict


class StateResponse(BaseModel):
    agent_id: int
    name: str
    extension: str
    manual_state: str
    computed_state: str
    reason: str
    sync_status: str
    sync_error: str | None = None
    asterisk_confirmed: bool
    wrap_up_until: datetime | None = None
    last_asterisk_sync_at: datetime | None = None
    blocking_session_ids: list[int]
    active_tasks: int
    background_tasks: int


class SessionOut(BaseModel):
    id: int
    ticket_id: str
    agent_id: int
    work_mode: str
    state: str
    started_at: datetime
    ended_at: datetime | None = None


class TasksResponse(BaseModel):
    active: list[SessionOut]
    blocking: list[SessionOut]
    background: list[SessionOut]


class ContactLookupRequest(BaseModel):
    number: str


class CreateTicketRequest(BaseModel):
    subject: str
    description: str = ""
    customer: str = ""
    priority: str = "2 normal"


class SimulateCallRequest(BaseModel):
    number: str
    extension: str | None = None
