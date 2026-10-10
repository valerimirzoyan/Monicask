from __future__ import annotations

from tests.conftest import admin_headers, agent_headers


def test_start_blocking_pauses_queue(client, agents, ami):
    alice = agents["alice"]
    response = client.post(
        "/api/tickets/42/start",
        json={"work_mode": "blocking"},
        headers=agent_headers(alice),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state"]["computed_state"] == "busy_task"
    assert body["state"]["asterisk_confirmed"] is True

    paused = {(q, m): p for (q, m), p in ami.paused.items()}
    assert paused == {("sales", "PJSIP/1001"): True, ("support", "PJSIP/1001"): True}


def test_background_keeps_agent_ready(client, agents, ami):
    alice = agents["alice"]
    response = client.post(
        "/api/tickets/7/start",
        json={"work_mode": "background"},
        headers=agent_headers(alice),
    )
    assert response.status_code == 200
    assert response.json()["state"]["computed_state"] == "ready"
    assert not any(ami.paused.values())


def test_two_blocking_tasks_one_completion_still_busy(client, agents):
    alice = agents["alice"]
    client.post("/api/tickets/1/start", json={"work_mode": "blocking"}, headers=agent_headers(alice))
    client.post("/api/tickets/2/start", json={"work_mode": "blocking"}, headers=agent_headers(alice))

    completed = client.post("/api/tickets/1/complete", json={}, headers=agent_headers(alice))
    assert completed.status_code == 200
    assert completed.json()["state"]["computed_state"] == "busy_task"

    final = client.post("/api/tickets/2/complete", json={}, headers=agent_headers(alice))
    assert final.json()["state"]["computed_state"] == "ready"


def test_completing_blocking_returns_to_queue(client, agents, ami):
    alice = agents["alice"]
    client.post("/api/tickets/9/start", json={"work_mode": "blocking"}, headers=agent_headers(alice))
    assert ami.paused[("sales", "PJSIP/1001")] is True

    client.post("/api/tickets/9/complete", json={}, headers=agent_headers(alice))
    assert ami.paused[("sales", "PJSIP/1001")] is False
    assert ami.paused[("support", "PJSIP/1001")] is False


def test_manual_ready_cannot_bypass_blocking(client, agents):
    alice = agents["alice"]
    client.post("/api/tickets/5/start", json={"work_mode": "blocking"}, headers=agent_headers(alice))
    response = client.post("/api/agents/me/ready", json={}, headers=agent_headers(alice))
    assert response.status_code == 200
    body = response.json()
    assert body["computed_state"] == "busy_task"
    assert body["blocking_session_ids"]


def test_break_persists_after_ticket_closed(client, agents):
    alice = agents["alice"]
    client.post("/api/agents/me/break", json={"reason": "lunch"}, headers=agent_headers(alice))
    started = client.post("/api/tickets/11/start", json={"work_mode": "blocking"}, headers=agent_headers(alice))
    assert started.json()["state"]["computed_state"] == "break"

    completed = client.post("/api/tickets/11/complete", json={}, headers=agent_headers(alice))
    assert completed.json()["state"]["computed_state"] == "break"


def test_only_background_and_no_break_is_available(client, agents):
    alice = agents["alice"]
    client.post("/api/tickets/20/start", json={"work_mode": "background"}, headers=agent_headers(alice))
    client.post("/api/tickets/21/start", json={"work_mode": "background"}, headers=agent_headers(alice))
    response = client.get("/api/agents/me/state", headers=agent_headers(alice))
    assert response.json()["computed_state"] == "ready"


def test_ami_failure_marks_sync_error_and_not_confirmed(client, agents, ami):
    alice = agents["alice"]
    ami.offline = True
    response = client.post(
        "/api/tickets/30/start",
        json={"work_mode": "blocking"},
        headers=agent_headers(alice),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state"]["computed_state"] == "busy_task"
    assert body["state"]["sync_status"] == "error"
    assert body["state"]["asterisk_confirmed"] is False


def test_reconcile_fixes_drift(client, agents, ami):
    alice = agents["alice"]
    ami.drift("sales", "PJSIP/1001", True)
    response = client.post(
        f"/api/admin/agents/{alice}/reconcile",
        headers=admin_headers(),
    )
    assert response.status_code == 200
    report = response.json()
    assert report["computed_state"] == "ready"
    assert report["report"]["mismatched_queues"] == ["sales"]
    assert ami.paused[("sales", "PJSIP/1001")] is False


def test_admin_lists_agents(client, agents):
    response = client.get("/api/admin/agents", headers=admin_headers())
    assert response.status_code == 200
    names = {a["name"] for a in response.json()["agents"]}
    assert {"Alice", "Bob"} <= names


def test_admin_requires_role(client, agents):
    response = client.get("/api/admin/agents")
    assert response.status_code == 403
