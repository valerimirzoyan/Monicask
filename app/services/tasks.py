from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ami.manager import AMIManager, SyncResult
from app.config import Settings
from app.db import utcnow
from app.models import (
    MANUAL_STATES,
    MODE_BLOCKING,
    SESSION_ACTIVE,
    SESSION_COMPLETED,
    SYNC_ERROR,
    SYNC_OK,
    WORK_MODES,
    AgentMapping,
    AgentState,
    AuditLog,
    IntegrationEvent,
    WorkSession,
)
from app.phone import normalize
from app.services import audit
from app.services.events import find_event, store_event
from app.state import ComputedState, compute_state
from app.zammad.client import ZammadClient, ZammadError


class ValidationError(Exception):
    pass


class NotFoundError(Exception):
    pass


@dataclass
class ActionResult:
    session: WorkSession
    replayed: bool
    state: dict


class TaskService:
    def __init__(
        self,
        db: Session,
        settings: Settings,
        ami: AMIManager,
        zammad: ZammadClient,
    ) -> None:
        self.db = db
        self.settings = settings
        self.ami = ami
        self.zammad = zammad

    def get_agent(self, agent_id: int) -> AgentMapping:
        agent = self.db.get(AgentMapping, agent_id)
        if agent is None:
            raise NotFoundError(f"agent {agent_id} not found")
        return agent

    def state_row(self, agent_id: int) -> AgentState:
        row = self.db.get(AgentState, agent_id)
        if row is None:
            row = AgentState(agent_id=agent_id)
            self.db.add(row)
            self.db.flush()
        return row

    def active_sessions(self, agent_id: int) -> list[WorkSession]:
        return list(
            self.db.scalars(
                select(WorkSession)
                .where(WorkSession.agent_id == agent_id, WorkSession.state == SESSION_ACTIVE)
                .order_by(WorkSession.started_at)
            )
        )

    def refresh(self, agent: AgentMapping) -> tuple[AgentState, ComputedState, SyncResult]:
        row = self.state_row(agent.id)
        now = utcnow()
        if row.wrap_up_until is not None and row.wrap_up_until <= now:
            row.wrap_up_until = None
        sessions = self.active_sessions(agent.id)
        computed = compute_state(row.manual_state, sessions, row.wrap_up_until, now)
        row.computed_state = computed.state
        row.computed_reason = computed.reason

        result = self.ami.sync(agent, computed.desired_paused, computed.reason)
        row.last_asterisk_sync_at = utcnow()
        if result.ok:
            row.sync_status = SYNC_OK
            row.sync_error = None
        else:
            row.sync_status = SYNC_ERROR
            row.sync_error = result.error
        self.db.commit()
        return row, computed, result

    def state_payload(self, agent: AgentMapping) -> dict:
        row = self.state_row(agent.id)
        sessions = self.active_sessions(agent.id)
        blocking = [s for s in sessions if s.work_mode == MODE_BLOCKING]
        background = [s for s in sessions if s.work_mode != MODE_BLOCKING]
        return {
            "agent_id": agent.id,
            "name": agent.name,
            "extension": agent.extension,
            "manual_state": row.manual_state,
            "computed_state": row.computed_state,
            "reason": row.computed_reason,
            "sync_status": row.sync_status,
            "sync_error": row.sync_error,
            "asterisk_confirmed": row.sync_status == SYNC_OK,
            "wrap_up_until": row.wrap_up_until,
            "last_asterisk_sync_at": row.last_asterisk_sync_at,
            "blocking_session_ids": [s.id for s in blocking],
            "active_tasks": len(sessions),
            "background_tasks": len(background),
        }

    def tasks_payload(self, agent: AgentMapping) -> dict:
        sessions = self.active_sessions(agent.id)
        return {
            "active": [self._session_payload(s) for s in sessions],
            "blocking": [self._session_payload(s) for s in sessions if s.work_mode == MODE_BLOCKING],
            "background": [self._session_payload(s) for s in sessions if s.work_mode != MODE_BLOCKING],
        }

    @staticmethod
    def _session_payload(session: WorkSession) -> dict:
        return {
            "id": session.id,
            "ticket_id": session.ticket_id,
            "agent_id": session.agent_id,
            "work_mode": session.work_mode,
            "state": session.state,
            "started_at": session.started_at,
            "ended_at": session.ended_at,
        }

    def start(self, agent: AgentMapping, ticket_id: str, work_mode: str, actor: str, idem_key: str | None) -> ActionResult:
        if work_mode not in WORK_MODES:
            raise ValidationError(f"work_mode must be one of {WORK_MODES}")
        if not ticket_id:
            raise ValidationError("ticket_id is required")

        idem_id = self._idem_id(agent, "start", idem_key)
        if idem_id:
            replayed = find_event(self.db, idem_id)
            if replayed is not None and replayed.result:
                session = self.db.get(WorkSession, replayed.result["session_id"])
                if session is None:
                    raise NotFoundError("idempotent session is missing")
                return ActionResult(session=session, replayed=True, state=self.state_payload(agent))

        existing = self.db.scalar(
            select(WorkSession).where(
                WorkSession.agent_id == agent.id,
                WorkSession.ticket_id == ticket_id,
                WorkSession.state == SESSION_ACTIVE,
            )
        )
        if existing is not None:
            return ActionResult(session=existing, replayed=True, state=self.state_payload(agent))

        session = WorkSession(
            ticket_id=ticket_id,
            agent_id=agent.id,
            work_mode=work_mode,
            started_at=utcnow(),
            state=SESSION_ACTIVE,
        )
        self.db.add(session)
        self.db.flush()

        self._assign_ticket(agent, ticket_id)
        _row, computed, sync = self.refresh(agent)

        audit.record(
            self.db,
            actor=actor,
            action="task.start",
            subject_type="ticket",
            subject_id=ticket_id,
            detail={
                "agent_id": agent.id,
                "work_mode": work_mode,
                "session_id": session.id,
                "computed_state": computed.state,
                "asterisk": sync.as_dict(),
            },
        )
        self.db.commit()

        result = {"session_id": session.id, "work_mode": work_mode}
        if idem_id:
            store_event(self.db, "api", {"ticket_id": ticket_id, "work_mode": work_mode}, idem_id, result=result)
        return ActionResult(session=session, replayed=False, state=self.state_payload(agent))

    def complete(self, agent: AgentMapping, ticket_id: str, actor: str, idem_key: str | None) -> ActionResult:
        idem_id = self._idem_id(agent, "complete", idem_key)
        if idem_id:
            replayed = find_event(self.db, idem_id)
            if replayed is not None and replayed.result:
                session = self.db.get(WorkSession, replayed.result["session_id"])
                if session is None:
                    raise NotFoundError("idempotent session is missing")
                return ActionResult(session=session, replayed=True, state=self.state_payload(agent))

        session = self.db.scalar(
            select(WorkSession).where(
                WorkSession.agent_id == agent.id,
                WorkSession.ticket_id == ticket_id,
                WorkSession.state == SESSION_ACTIVE,
            )
        )
        if session is None:
            last = self.db.scalar(
                select(WorkSession)
                .where(
                    WorkSession.agent_id == agent.id,
                    WorkSession.ticket_id == ticket_id,
                    WorkSession.state == SESSION_COMPLETED,
                )
                .order_by(WorkSession.ended_at.desc())
            )
            if last is None:
                raise NotFoundError(f"no session for ticket {ticket_id} and agent {agent.id}")
            return ActionResult(session=last, replayed=True, state=self.state_payload(agent))

        session.state = SESSION_COMPLETED
        session.ended_at = utcnow()
        session.result_status = self.settings.final_ticket_status
        self.db.flush()

        remaining_blocking = [s for s in self.active_sessions(agent.id) if s.work_mode == MODE_BLOCKING]
        row = self.state_row(agent.id)
        if self.settings.wrap_up_enabled and session.work_mode == MODE_BLOCKING and not remaining_blocking:
            row.wrap_up_until = utcnow() + timedelta(seconds=self.settings.wrap_up_seconds)

        self._close_ticket(ticket_id)
        row, computed, sync = self.refresh(agent)

        audit.record(
            self.db,
            actor=actor,
            action="task.complete",
            subject_type="ticket",
            subject_id=ticket_id,
            detail={
                "agent_id": agent.id,
                "session_id": session.id,
                "computed_state": computed.state,
                "asterisk": sync.as_dict(),
            },
        )
        self.db.commit()

        result = {"session_id": session.id}
        if idem_id:
            store_event(self.db, "api", {"ticket_id": ticket_id}, idem_id, result=result)
        return ActionResult(session=session, replayed=False, state=self.state_payload(agent))

    def set_manual_state(
        self,
        agent: AgentMapping,
        manual_state: str,
        actor: str,
        reason: str = "",
        override: bool = False,
    ) -> dict:
        if manual_state not in MANUAL_STATES:
            raise ValidationError(f"manual_state must be one of {MANUAL_STATES}")
        row = self.state_row(agent.id)
        previous = row.manual_state
        row.manual_state = manual_state
        self.db.flush()
        row, computed, sync = self.refresh(agent)

        audit.record(
            self.db,
            actor=actor,
            action="agent.override" if override else "agent.manual_state",
            subject_type="agent",
            subject_id=str(agent.id),
            detail={
                "from": previous,
                "to": manual_state,
                "reason": reason,
                "override": override,
                "computed_state": computed.state,
                "blocked_by_tasks": bool(computed.blocking_session_ids),
                "asterisk": sync.as_dict(),
            },
        )
        self.db.commit()
        return self.state_payload(agent)

    def reconcile(self, agent: AgentMapping, actor: str) -> dict:
        row = self.state_row(agent.id)
        now = utcnow()
        if row.wrap_up_until is not None and row.wrap_up_until <= now:
            row.wrap_up_until = None
        sessions = self.active_sessions(agent.id)
        computed = compute_state(row.manual_state, sessions, row.wrap_up_until, now)
        report = self.ami.reconcile(agent, computed.desired_paused, computed.reason)

        row.computed_state = computed.state
        row.computed_reason = computed.reason
        row.last_asterisk_sync_at = utcnow()
        if report.get("error") or report.get("failed"):
            row.sync_status = SYNC_ERROR
            row.sync_error = report.get("error") or f"failed queues: {report.get('failed')}"
        else:
            row.sync_status = SYNC_OK
            row.sync_error = None
        self.db.commit()

        audit.record(
            self.db,
            actor=actor,
            action="agent.reconcile",
            subject_type="agent",
            subject_id=str(agent.id),
            detail={"computed_state": computed.state, "report": report},
        )
        self.db.commit()
        return {"agent_id": agent.id, "computed_state": computed.state, "report": report}

    def list_agents(self) -> list[dict]:
        agents = list(self.db.scalars(select(AgentMapping).order_by(AgentMapping.id)))
        return [
            {
                "id": agent.id,
                "name": agent.name,
                "extension": agent.extension,
                "asterisk_interface": agent.asterisk_interface,
                "queues": self.ami.queues_for(agent),
                "enabled": agent.enabled,
                **self.state_payload(agent),
            }
            for agent in agents
        ]

    def tickets_with_sessions(self, agent: AgentMapping, limit: int = 25) -> dict:
        try:
            tickets = self.zammad.list_tickets(limit=limit)
            error = None
        except ZammadError as exc:
            return {"tickets": [], "error": str(exc)}

        sessions = {
            s.ticket_id: s
            for s in self.db.scalars(
                select(WorkSession).where(WorkSession.agent_id == agent.id, WorkSession.state == SESSION_ACTIVE)
            )
        }
        result = []
        for ticket in tickets:
            session = sessions.get(str(ticket["id"]))
            item = dict(ticket)
            item["work_mode"] = session.work_mode if session else None
            item["session_id"] = session.id if session else None
            item["mine"] = session is not None
            result.append(item)
        return {"tickets": result, "error": error}

    def lookup_contact(self, number: str) -> dict:
        normalized = normalize(number)
        if not normalized:
            raise ValidationError("number is required")
        try:
            contact = self.zammad.search_contact(number)
        except ZammadError as exc:
            raise ValidationError(f"contact lookup failed: {exc}") from exc
        return {"number_normalized": normalized, "found": contact is not None, "contact": contact}

    def create_ticket(
        self,
        subject: str,
        body: str = "",
        customer: str = "",
        priority: str = "2 normal",
        actor: str = "agent",
    ) -> dict:
        if not subject:
            raise ValidationError("subject is required")
        try:
            ticket = self.zammad.create_ticket(subject, body, customer, priority)
        except ZammadError as exc:
            raise ValidationError(f"ticket creation failed: {exc}") from exc
        audit.record(
            self.db,
            actor=actor,
            action="ticket.create",
            subject_type="ticket",
            subject_id=str(ticket["id"]),
            detail={"subject": subject, "customer": customer},
        )
        self.db.commit()
        return ticket

    def recent_audit(self, agent: AgentMapping, limit: int = 20) -> list[dict]:
        entries = self.db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))
        return [
            {
                "id": e.id,
                "at": e.at,
                "actor": e.actor,
                "action": e.action,
                "subject_type": e.subject_type,
                "subject_id": e.subject_id,
                "detail": e.detail,
            }
            for e in entries
        ]

    def _assign_ticket(self, agent: AgentMapping, ticket_id: str) -> None:
        if not agent.zammad_user_id:
            return
        try:
            self.zammad.assign_ticket(ticket_id, agent.zammad_user_id)
        except ZammadError as exc:
            self._queue_zammad_retry("assign", ticket_id, exc)

    def _close_ticket(self, ticket_id: str) -> None:
        try:
            self.zammad.set_status(ticket_id, self.settings.final_ticket_status)
        except ZammadError as exc:
            self._queue_zammad_retry("set_status", ticket_id, exc)

    def _queue_zammad_retry(self, action: str, ticket_id: str, exc: Exception) -> None:
        self.db.add(
            IntegrationEvent(
                source="zammad",
                external_event_id=None,
                payload={"action": action, "ticket_id": ticket_id, "status": self.settings.final_ticket_status},
                status="retry",
                attempts=0,
                last_error=str(exc),
            )
        )
        audit.record(
            self.db,
            actor="system",
            action="zammad.retry_queued",
            subject_type="ticket",
            subject_id=ticket_id,
            detail={"action": action, "error": str(exc)},
        )

    def _idem_id(self, agent: AgentMapping, scope: str, key: str | None) -> str | None:
        if not key:
            return None
        return f"api:{scope}:{agent.id}:{key}"
