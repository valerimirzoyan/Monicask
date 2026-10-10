from __future__ import annotations

from datetime import timedelta

from app.db import utcnow
from app.models import (
    MANUAL_BREAK,
    MANUAL_OFFLINE,
    MANUAL_READY,
    MODE_BACKGROUND,
    MODE_BLOCKING,
    STATE_BREAK,
    STATE_BUSY_TASK,
    STATE_OFFLINE,
    STATE_READY,
    STATE_WRAP_UP,
    WorkSession,
)
from app.state import compute_state


def session(mode: str, sid: int) -> WorkSession:
    return WorkSession(id=sid, agent_id=1, ticket_id=str(sid), work_mode=mode)


def test_ready_with_no_sessions():
    now = utcnow()
    result = compute_state(MANUAL_READY, [], None, now)
    assert result.state == STATE_READY
    assert result.desired_paused is False


def test_background_does_not_block():
    now = utcnow()
    result = compute_state(MANUAL_READY, [session(MODE_BACKGROUND, 1), session(MODE_BACKGROUND, 2)], None, now)
    assert result.state == STATE_READY
    assert result.desired_paused is False


def test_blocking_task_makes_busy():
    now = utcnow()
    result = compute_state(MANUAL_READY, [session(MODE_BLOCKING, 7)], None, now)
    assert result.state == STATE_BUSY_TASK
    assert result.blocking_session_ids == (7,)
    assert result.desired_paused is True


def test_break_has_priority_over_blocking():
    now = utcnow()
    result = compute_state(MANUAL_BREAK, [session(MODE_BLOCKING, 1)], None, now)
    assert result.state == STATE_BREAK


def test_offline_has_priority_over_break():
    now = utcnow()
    result = compute_state(MANUAL_OFFLINE, [session(MODE_BLOCKING, 1)], None, now)
    assert result.state == STATE_OFFLINE


def test_wrap_up_when_no_blocking():
    now = utcnow()
    result = compute_state(MANUAL_READY, [], now + timedelta(seconds=10), now)
    assert result.state == STATE_WRAP_UP
    assert result.desired_paused is True


def test_wrap_up_expired_is_ready():
    now = utcnow()
    result = compute_state(MANUAL_READY, [], now - timedelta(seconds=1), now)
    assert result.state == STATE_READY


def test_blocking_beats_wrap_up():
    now = utcnow()
    result = compute_state(MANUAL_READY, [session(MODE_BLOCKING, 3)], now + timedelta(seconds=10), now)
    assert result.state == STATE_BUSY_TASK
