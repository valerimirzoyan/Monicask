from __future__ import annotations

import logging
import socket
import threading
import time
from collections import deque
from collections.abc import Callable

from app.ami.base import AMIClient, AMIConnectionError, AMIError
from app.ami.protocol import MessageBuffer, encode_action, next_action_id

log = logging.getLogger(__name__)

Predicate = Callable[[dict[str, str]], bool]


class _Pending:
    def __init__(self) -> None:
        self.cond = threading.Condition()
        self.messages: list[dict[str, str]] = []
        self.closed = False

    def add(self, message: dict[str, str]) -> None:
        with self.cond:
            self.messages.append(message)
            self.cond.notify_all()

    def close(self) -> None:
        with self.cond:
            self.closed = True
            self.cond.notify_all()

    def wait(self, predicate: Predicate, timeout: float) -> dict[str, str] | None:
        deadline = time.monotonic() + timeout
        with self.cond:
            cursor = 0
            while True:
                while cursor < len(self.messages):
                    message = self.messages[cursor]
                    cursor += 1
                    if predicate(message):
                        return message
                if self.closed:
                    return None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self.cond.wait(timeout=min(remaining, 0.5))


class RealAMI(AMIClient):
    mode = "real"

    def __init__(
        self,
        host: str,
        port: int = 5038,
        username: str = "",
        secret: str = "",
        timeout: float = 5.0,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.secret = secret
        self.timeout = timeout
        self.recent_events: deque[dict[str, str]] = deque(maxlen=500)
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._pending: dict[str, _Pending] = {}
        self._lock = threading.Lock()
        self._connected = False
        self._stopping = False
        self.last_error: str | None = None

    def connect(self) -> None:
        if self._connected:
            return
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            self.last_error = f"AMI connect failed: {exc}"
            raise AMIConnectionError(self.last_error) from exc
        sock.settimeout(0.5)
        self._sock = sock
        self._stopping = False
        self._connected = True
        self._thread = threading.Thread(target=self._reader_loop, name="ami-reader", daemon=True)
        self._thread.start()
        try:
            self.send_action(
                "Login",
                {"Username": self.username, "Secret": self.secret},
                timeout=self.timeout,
            )
        except AMIError:
            self.close()
            raise

    def close(self) -> None:
        self._stopping = True
        self._connected = False
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        with self._lock:
            pendings = list(self._pending.values())
            self._pending.clear()
        for pending in pendings:
            pending.close()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None

    def is_connected(self) -> bool:
        return self._connected

    def send_action(
        self,
        action: str,
        params: dict[str, str],
        timeout: float | None = None,
    ) -> dict[str, str]:
        if not self._connected or self._sock is None:
            raise AMIConnectionError("AMI is not connected")
        action_id = next_action_id()
        pending = _Pending()
        with self._lock:
            self._pending[action_id] = pending
        payload = encode_action(action, params, action_id)
        try:
            self._sock.sendall(payload)
        except OSError as exc:
            self.last_error = f"AMI send failed: {exc}"
            self._drop_pending(action_id)
            self.close()
            raise AMIConnectionError(self.last_error) from exc

        response = pending.wait(lambda m: "Response" in m, timeout or self.timeout)
        self._drop_pending(action_id)
        if response is None:
            self.last_error = f"timeout waiting for response to {action}"
            raise AMIConnectionError(self.last_error)
        if response.get("Response") != "Success":
            raise AMIError(response.get("Message") or f"{action} rejected: {response.get('Response')}")
        return response

    def pause(self, queue: str, member: str, reason: str = "") -> None:
        params = {
            "Queue": queue,
            "Member": member,
            "Interface": member,
            "Paused": "yes",
            "Reason": reason or "monicask",
        }
        try:
            self.send_action("PauseQueueMember", params)
        except AMIConnectionError:
            raise
        except AMIError:
            fallback = {"Queue": queue, "Interface": member, "Paused": "yes", "Reason": reason or "monicask"}
            self.send_action("QueuePause", fallback)

    def unpause(self, queue: str, member: str, reason: str = "") -> None:
        params = {
            "Queue": queue,
            "Member": member,
            "Interface": member,
            "Paused": "no",
            "Reason": reason or "monicask",
        }
        try:
            self.send_action("PauseQueueMember", params)
        except AMIConnectionError:
            raise
        except AMIError:
            fallback = {"Queue": queue, "Interface": member, "Paused": "no", "Reason": reason or "monicask"}
            self.send_action("QueuePause", fallback)

    def queue_paused_state(self) -> dict[tuple[str, str], bool]:
        action_id = next_action_id()
        pending = _Pending()
        with self._lock:
            self._pending[action_id] = pending
        if not self._connected or self._sock is None:
            self._drop_pending(action_id)
            raise AMIConnectionError("AMI is not connected")
        try:
            self._sock.sendall(encode_action("QueueStatus", {}, action_id))
        except OSError as exc:
            self._drop_pending(action_id)
            self.close()
            raise AMIConnectionError(f"AMI send failed: {exc}") from exc

        response = pending.wait(lambda m: "Response" in m, self.timeout)
        if response is None or response.get("Response") != "Success":
            self._drop_pending(action_id)
            raise AMIError("QueueStatus rejected or timed out")
        pending.wait(lambda m: m.get("Event") in ("QueueStatusComplete", "AgentsComplete"), self.timeout)
        self._drop_pending(action_id)

        state: dict[tuple[str, str], bool] = {}
        for message in pending.messages:
            if message.get("Event") not in ("QueueMember", "Agent"):
                continue
            queue = message.get("Queue")
            member = message.get("Member") or message.get("Interface")
            paused = message.get("Paused")
            if queue and member and paused is not None:
                state[(queue, member)] = paused.lower() in ("1", "true", "yes")
        return state

    def _drop_pending(self, action_id: str) -> None:
        with self._lock:
            pending = self._pending.pop(action_id, None)
        if pending is not None:
            pending.close()

    def _reader_loop(self) -> None:
        buffer = MessageBuffer()
        while not self._stopping:
            sock = self._sock
            if sock is None:
                break
            try:
                data = sock.recv(8192)
            except TimeoutError:
                continue
            except OSError:
                break
            if not data:
                break
            for message in buffer.feed(data):
                action_id = message.get("ActionID")
                with self._lock:
                    pending = self._pending.get(action_id) if action_id else None
                if pending is not None:
                    pending.add(message)
                else:
                    self.recent_events.append(message)
        if not self._stopping:
            self.last_error = "AMI connection closed by peer"
            log.warning("AMI connection closed by peer")
            self._connected = False
            with self._lock:
                pendings = list(self._pending.values())
                self._pending.clear()
            for pending in pendings:
                pending.close()
