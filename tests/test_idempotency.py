from __future__ import annotations

from tests.conftest import agent_headers


def test_start_with_same_idempotency_key_creates_one_session(client, agents):
    alice = agents["alice"]
    headers = {**agent_headers(alice), "Idempotency-Key": "abc-123"}
    first = client.post("/api/tickets/100/start", json={"work_mode": "blocking"}, headers=headers)
    second = client.post("/api/tickets/100/start", json={"work_mode": "blocking"}, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["session_id"] == second.json()["session_id"]
    assert second.json()["replayed"] is True

    tasks = client.get("/api/agents/me/tasks", headers=agent_headers(alice)).json()
    assert len(tasks["active"]) == 1


def test_start_twice_without_key_is_idempotent_by_active_session(client, agents):
    alice = agents["alice"]
    first = client.post("/api/tickets/101/start", json={"work_mode": "blocking"}, headers=agent_headers(alice))
    second = client.post("/api/tickets/101/start", json={"work_mode": "blocking"}, headers=agent_headers(alice))
    assert first.json()["session_id"] == second.json()["session_id"]

    tasks = client.get("/api/agents/me/tasks", headers=agent_headers(alice)).json()
    assert len(tasks["active"]) == 1


def test_complete_is_idempotent(client, agents):
    alice = agents["alice"]
    client.post("/api/tickets/102/start", json={"work_mode": "blocking"}, headers=agent_headers(alice))
    first = client.post("/api/tickets/102/complete", json={}, headers=agent_headers(alice))
    second = client.post("/api/tickets/102/complete", json={}, headers=agent_headers(alice))
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["session_id"] == second.json()["session_id"]


def test_duplicate_webhook_is_deduplicated(client):
    payload = {"event": "ticket.create", "ticket": {"id": 5, "title": "help"}}
    first = client.post("/api/integrations/zammad/webhook", json=payload)
    second = client.post("/api/integrations/zammad/webhook", json=payload)
    assert first.status_code == 200
    assert first.json()["deduplicated"] is False
    assert second.json()["deduplicated"] is True
    assert first.json()["event_id"] == second.json()["event_id"]


def test_webhook_token_is_enforced(client, app):
    app.state.settings.webhook_secret = "topsecret"
    payload = {"event": "ticket.update"}
    denied = client.post("/api/integrations/zammad/webhook", json=payload)
    assert denied.status_code == 401
    allowed = client.post(
        "/api/integrations/zammad/webhook",
        json=payload,
        headers={"X-Webhook-Token": "topsecret"},
    )
    assert allowed.status_code == 200
