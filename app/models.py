from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utcnow

MODE_BLOCKING = "blocking"
MODE_BACKGROUND = "background"
WORK_MODES = (MODE_BLOCKING, MODE_BACKGROUND)

SESSION_ACTIVE = "active"
SESSION_COMPLETED = "completed"
SESSION_CANCELLED = "cancelled"

MANUAL_READY = "ready"
MANUAL_BREAK = "break"
MANUAL_OFFLINE = "offline"
MANUAL_STATES = (MANUAL_READY, MANUAL_BREAK, MANUAL_OFFLINE)

STATE_READY = "ready"
STATE_BUSY_TASK = "busy_task"
STATE_BREAK = "break"
STATE_OFFLINE = "offline"
STATE_WRAP_UP = "wrap_up"

SYNC_OK = "ok"
SYNC_PENDING = "pending"
SYNC_ERROR = "error"


class AgentMapping(Base):
    __tablename__ = "agent_mapping"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zammad_user_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    asterisk_interface: Mapped[str] = mapped_column(String(128), nullable=False)
    extension: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    queues: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class WorkSession(Base):
    __tablename__ = "work_session"
    __table_args__ = (Index("ix_work_session_agent_state", "agent_id", "state"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agent_mapping.id"), nullable=False, index=True)
    work_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default=SESSION_ACTIVE)
    result_status: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AgentState(Base):
    __tablename__ = "agent_state"

    agent_id: Mapped[int] = mapped_column(ForeignKey("agent_mapping.id"), primary_key=True)
    manual_state: Mapped[str] = mapped_column(String(16), nullable=False, default=MANUAL_READY)
    computed_state: Mapped[str] = mapped_column(String(16), nullable=False, default=STATE_READY)
    computed_reason: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    wrap_up_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_asterisk_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sync_status: Mapped[str] = mapped_column(String(16), nullable=False, default=SYNC_OK)
    sync_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class IntegrationEvent(Base):
    __tablename__ = "integration_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    external_event_id: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="new")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    subject_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
