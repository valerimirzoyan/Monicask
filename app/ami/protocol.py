from __future__ import annotations

import itertools
import threading

_action_counter = itertools.count(1)
_counter_lock = threading.Lock()


def next_action_id(prefix: str = "aw") -> str:
    with _counter_lock:
        return f"{prefix}-{next(_action_counter)}"


def encode_action(action: str, params: dict[str, str], action_id: str) -> bytes:
    lines = [f"Action: {action}"]
    for key, value in params.items():
        lines.append(f"{key}: {value}")
    lines.append(f"ActionID: {action_id}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")


def parse_message(chunk: bytes) -> dict[str, str]:
    message: dict[str, str] = {}
    for raw_line in chunk.split(b"\r\n"):
        if not raw_line:
            continue
        line = raw_line.decode("utf-8", errors="replace")
        if ": " not in line:
            continue
        key, value = line.split(": ", 1)
        if key in message:
            message[key] = f"{message[key]}\n{value}"
        else:
            message[key] = value
    return message


class MessageBuffer:
    def __init__(self) -> None:
        self._buffer = b""

    def feed(self, data: bytes) -> list[dict[str, str]]:
        self._buffer += data
        messages: list[dict[str, str]] = []
        while True:
            index = self._buffer.find(b"\r\n\r\n")
            if index < 0:
                break
            chunk = self._buffer[:index]
            self._buffer = self._buffer[index + 4 :]
            if chunk.strip():
                messages.append(parse_message(chunk))
        return messages
