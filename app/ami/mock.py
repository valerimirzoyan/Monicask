from __future__ import annotations

from app.ami.base import AMIClient, AMIConnectionError, AMIError


class MockAMI(AMIClient):
    mode = "mock"

    def __init__(self) -> None:
        self.paused: dict[tuple[str, str], bool] = {}
        self.commands: list[tuple[str, str, str, str]] = []
        self.fail_next: int = 0
        self.offline: bool = False
        self._connected = True
        self.last_error: str | None = None

    def connect(self) -> None:
        if self.offline:
            self.last_error = "mock AMI is offline"
            raise AMIConnectionError(self.last_error)
        self._connected = True

    def close(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected and not self.offline

    def _guard(self, action: str) -> None:
        if self.offline or not self._connected:
            self.last_error = "mock AMI is offline"
            raise AMIConnectionError(self.last_error)
        if self.fail_next > 0:
            self.fail_next -= 1
            raise AMIError(f"mock AMI rejected {action}")

    def pause(self, queue: str, member: str, reason: str = "") -> None:
        self._guard("pause")
        self.commands.append(("pause", queue, member, reason))
        self.paused[(queue, member)] = True

    def unpause(self, queue: str, member: str, reason: str = "") -> None:
        self._guard("unpause")
        self.commands.append(("unpause", queue, member, reason))
        self.paused[(queue, member)] = False

    def queue_paused_state(self) -> dict[tuple[str, str], bool]:
        self._guard("queue_status")
        return dict(self.paused)

    def drift(self, queue: str, member: str, paused: bool) -> None:
        self.paused[(queue, member)] = paused
