from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from app.db import utcnow


@dataclass
class CallEvent:
    id: int
    number: str
    extension: str
    direction: str = "inbound"
    state: str = "ringing"
    started_at: datetime = field(default_factory=utcnow)
    answered_at: datetime | None = None
    ended_at: datetime | None = None


class CallStore:
    def __init__(self, maxlen: int = 100) -> None:
        self._calls: deque[CallEvent] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._seq = 0

    def push(self, number: str, extension: str, direction: str = "inbound") -> CallEvent:
        with self._lock:
            self._seq += 1
            event = CallEvent(id=self._seq, number=number, extension=extension, direction=direction)
            self._calls.appendleft(event)
            return event

    def recent(self, limit: int = 20, extension: str | None = None) -> list[CallEvent]:
        with self._lock:
            calls = list(self._calls)
        if extension:
            calls = [c for c in calls if c.extension == extension]
        return calls[:limit]

    def latest_incoming(self, extension: str) -> CallEvent | None:
        for call in self.recent(limit=50, extension=extension):
            if call.direction == "inbound" and call.state == "ringing":
                return call
        return None
