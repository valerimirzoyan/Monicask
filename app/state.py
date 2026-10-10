from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.models import (
    MANUAL_BREAK,
    MANUAL_OFFLINE,
    MANUAL_READY,
    MODE_BLOCKING,
    STATE_BREAK,
    STATE_BUSY_TASK,
    STATE_OFFLINE,
    STATE_READY,
    STATE_WRAP_UP,
)


class SessionLike(Protocol):
    id: int
    work_mode: str


@dataclass(frozen=True)
class ComputedState:
    state: str
    reason: str
    blocking_session_ids: tuple[int, ...]

    @property
    def desired_paused(self) -> bool:
        return self.state != STATE_READY


def compute_state(
    manual_state: str,
    active_sessions: Sequence[SessionLike],
    wrap_up_until: datetime | None,
    now: datetime,
) -> ComputedState:
    blocking = tuple(s.id for s in active_sessions if s.work_mode == MODE_BLOCKING)

    if manual_state == MANUAL_OFFLINE:
        return ComputedState(STATE_OFFLINE, "operator is offline", ())
    if manual_state == MANUAL_BREAK:
        return ComputedState(STATE_BREAK, "manual break", blocking)
    if blocking:
        return ComputedState(
            STATE_BUSY_TASK,
            f"{len(blocking)} blocking task(s): {', '.join(str(i) for i in blocking)}",
            blocking,
        )
    if wrap_up_until is not None and now < wrap_up_until:
        return ComputedState(STATE_WRAP_UP, "post-call wrap-up", ())
    return ComputedState(STATE_READY, "no blockers", ())


def manual_allows_calls(manual_state: str) -> bool:
    return manual_state in (MANUAL_READY, MANUAL_BREAK, MANUAL_OFFLINE)
