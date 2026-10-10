from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.ami.base import AMIClient, AMIConnectionError, AMIError
from app.models import AgentMapping


@dataclass
class SyncResult:
    ok: bool
    desired_paused: bool
    applied: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "desired_paused": self.desired_paused,
            "applied": self.applied,
            "failed": self.failed,
            "error": self.error,
        }


class AMIManager:
    def __init__(
        self,
        client: AMIClient,
        managed_queues: list[str],
        max_attempts: int = 3,
        retry_backoff: float = 0.25,
        timeout: float = 5.0,
    ) -> None:
        self.client = client
        self.managed_queues = list(managed_queues)
        self.max_attempts = max(1, max_attempts)
        self.retry_backoff = retry_backoff
        self.timeout = timeout

    def mode(self) -> str:
        return self.client.mode

    def queues_for(self, agent: AgentMapping) -> list[str]:
        configured = [q for q in (agent.queues or []) if q in self.managed_queues]
        return configured or list(self.managed_queues)

    def ensure_connected(self) -> None:
        if self.client.is_connected():
            return
        self.client.connect()

    def sync(self, agent: AgentMapping, desired_paused: bool, reason: str = "") -> SyncResult:
        result = SyncResult(ok=True, desired_paused=desired_paused)
        queues = self.queues_for(agent)
        if not queues:
            return result
        try:
            self.ensure_connected()
        except AMIError as exc:
            result.ok = False
            result.error = str(exc)
            result.failed = list(queues)
            return result

        for queue in queues:
            try:
                self._apply(queue, agent.asterisk_interface, desired_paused, reason)
                result.applied.append(queue)
            except AMIError as exc:
                result.ok = False
                result.failed.append(queue)
                result.error = str(exc)
        return result

    def snapshot(self, agent: AgentMapping) -> dict[str, bool]:
        queues = self.queues_for(agent)
        state = self.client.queue_paused_state()
        return {
            queue: state.get((queue, agent.asterisk_interface), False)
            for queue in queues
        }

    def _apply(self, queue: str, member: str, desired_paused: bool, reason: str) -> None:
        last_error: AMIError | None = None
        for attempt in range(self.max_attempts):
            try:
                if desired_paused:
                    self.client.pause(queue, member, reason)
                else:
                    self.client.unpause(queue, member, reason)
                return
            except AMIConnectionError as exc:
                last_error = exc
                time.sleep(self.retry_backoff * (attempt + 1))
                try:
                    self.client.connect()
                except AMIError as connect_error:
                    last_error = connect_error
            except AMIError as exc:
                last_error = exc
                break
        raise last_error or AMIError("AMI command failed")

    def reconcile(self, agent: AgentMapping, desired_paused: bool, reason: str = "") -> dict:
        report: dict = {
            "desired_paused": desired_paused,
            "actual": {},
            "mismatched_queues": [],
            "fixed": [],
            "failed": [],
            "connected": False,
            "error": None,
        }
        try:
            self.ensure_connected()
            report["connected"] = True
            actual = self.snapshot(agent)
        except AMIError as exc:
            report["error"] = str(exc)
            return report

        report["actual"] = actual
        for queue, paused in actual.items():
            if paused != desired_paused:
                report["mismatched_queues"].append(queue)

        if report["mismatched_queues"]:
            sync = self.sync(agent, desired_paused, reason)
            report["fixed"] = sync.applied
            report["failed"] = sync.failed
            report["error"] = sync.error
        return report
