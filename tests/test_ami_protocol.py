from __future__ import annotations

import socket
import threading

import pytest

from app.ami.base import AMIConnectionError, AMIError
from app.ami.client import RealAMI
from app.ami.protocol import MessageBuffer, encode_action, parse_message

CRLF = b"\r\n"


class FakeAMIServer:
    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.host, self.port = self.sock.getsockname()
        self.paused: dict[tuple[str, str], bool] = {}
        self.reject: set[str] = set()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self.sock.close()
        self._thread.join(timeout=2.0)

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        buffer = MessageBuffer()
        try:
            while not self._stop.is_set():
                data = conn.recv(4096)
                if not data:
                    return
                for message in buffer.feed(data):
                    self._dispatch(conn, message)
        finally:
            conn.close()

    def _dispatch(self, conn: socket.socket, message: dict[str, str]) -> None:
        action = message.get("Action", "")
        action_id = message.get("ActionID", "")
        if action == "Login":
            self._send(conn, {"Response": "Success", "Message": "Authentication accepted", "ActionID": action_id})
        elif action in self.reject:
            self._send(conn, {"Response": "Error", "Message": "Permission denied", "ActionID": action_id})
        elif action in ("PauseQueueMember", "QueuePause"):
            member = message.get("Member") or message.get("Interface", "")
            self.paused[(message.get("Queue", ""), member)] = message.get("Paused", "no").lower() in ("yes", "1", "true")
            self._send(conn, {"Response": "Success", "ActionID": action_id})
        elif action == "QueueStatus":
            self._send(conn, {"Response": "Success", "ActionID": action_id})
            for (queue, member), paused in self.paused.items():
                self._send(
                    conn,
                    {
                        "Event": "QueueMember",
                        "Queue": queue,
                        "Member": member,
                        "Paused": "1" if paused else "0",
                        "ActionID": action_id,
                    },
                )
            self._send(conn, {"Event": "QueueStatusComplete", "ActionID": action_id})

    @staticmethod
    def _send(conn: socket.socket, message: dict[str, str]) -> None:
        body = CRLF.join(f"{key}: {value}".encode() for key, value in message.items())
        conn.sendall(body + CRLF + CRLF)


@pytest.fixture
def fake_ami():
    server = FakeAMIServer()
    yield server
    server.close()


def test_encode_and_parse_roundtrip():
    encoded = encode_action("PauseQueueMember", {"Queue": "sales", "Member": "PJSIP/1001"}, "aw-1")
    assert b"Action: PauseQueueMember\r\n" in encoded
    assert encoded.endswith(b"\r\n\r\n")

    message = parse_message(b"Response: Success\r\nActionID: aw-1")
    assert message == {"Response": "Success", "ActionID": "aw-1"}


def test_message_buffer_splits_messages():
    buffer = MessageBuffer()
    messages = buffer.feed(b"Event: A\r\nX: 1\r\n\r\nEvent: B\r\nY: 2\r\n\r\n")
    assert [m["Event"] for m in messages] == ["A", "B"]


def test_real_ami_login_pause_status(fake_ami):
    client = RealAMI(fake_ami.host, fake_ami.port, "user", "secret", timeout=3.0)
    client.connect()
    assert client.is_connected()

    client.pause("sales", "PJSIP/1001", "busy")
    assert fake_ami.paused[("sales", "PJSIP/1001")] is True

    client.unpause("sales", "PJSIP/1001")
    assert fake_ami.paused[("sales", "PJSIP/1001")] is False

    client.pause("sales", "PJSIP/1001")
    state = client.queue_paused_state()
    assert state[("sales", "PJSIP/1001")] is True
    client.close()


def test_real_ami_rejected_action_raises(fake_ami):
    fake_ami.reject.add("PauseQueueMember")
    fake_ami.reject.add("QueuePause")
    client = RealAMI(fake_ami.host, fake_ami.port, "user", "secret", timeout=3.0)
    client.connect()
    with pytest.raises(AMIError):
        client.pause("sales", "PJSIP/1001")
    client.close()


def test_real_ami_connection_refused():
    client = RealAMI("127.0.0.1", 1, "user", "secret", timeout=1.0)
    with pytest.raises(AMIConnectionError):
        client.connect()
