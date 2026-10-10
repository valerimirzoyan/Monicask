from __future__ import annotations

from tests.conftest import agent_headers


def test_ui_index_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Рабочее место оператора" in response.text


def test_tickets_endpoint_lists_mock_tickets(client, agents):
    response = client.get("/api/agents/me/tickets", headers=agent_headers(agents["alice"]))
    assert response.status_code == 200
    tickets = response.json()["tickets"]
    assert len(tickets) >= 3
    assert all(t["work_mode"] is None for t in tickets)


def test_tickets_endpoint_marks_active_session(client, agents):
    alice = agents["alice"]
    first = client.get("/api/agents/me/tickets", headers=agent_headers(alice)).json()["tickets"][0]
    client.post(f"/api/tickets/{first['id']}/start", json={"work_mode": "background"}, headers=agent_headers(alice))
    tickets = client.get("/api/agents/me/tickets", headers=agent_headers(alice)).json()["tickets"]
    mine = next(t for t in tickets if t["id"] == first["id"])
    assert mine["mine"] is True
    assert mine["work_mode"] == "background"


def test_contact_lookup_found_and_not_found(client, agents):
    headers = agent_headers(agents["alice"])
    found = client.post("/api/contacts/lookup", json={"number": "+37360123456"}, headers=headers)
    assert found.status_code == 200
    assert found.json()["found"] is True
    assert found.json()["contact"]["name"] == "ИП Ромашка"

    missing = client.post("/api/contacts/lookup", json={"number": "+10000000000"}, headers=headers)
    assert missing.json()["found"] is False


def test_create_ticket_appears_in_queue(client, agents):
    headers = agent_headers(agents["alice"])
    created = client.post(
        "/api/tickets",
        json={"subject": "Тестовое обращение", "description": "текст"},
        headers=headers,
    )
    assert created.status_code == 200
    ticket_id = created.json()["id"]
    tickets = client.get("/api/agents/me/tickets", headers=headers).json()["tickets"]
    assert any(t["id"] == ticket_id and t["title"] == "Тестовое обращение" for t in tickets)


def test_audit_feed_records_actions(client, agents):
    alice = agents["alice"]
    client.post("/api/tickets/55/start", json={"work_mode": "blocking"}, headers=agent_headers(alice))
    events = client.get("/api/agents/me/audit", headers=agent_headers(alice)).json()["events"]
    assert any(e["action"] == "task.start" for e in events)


def test_simulate_call_and_recent_calls(client, agents):
    alice = agents["alice"]
    headers = agent_headers(alice)
    simulated = client.post("/api/dev/simulate-call", json={"number": "+37360123456"}, headers=headers)
    assert simulated.status_code == 200
    calls = client.get("/api/agents/me/calls", headers=headers).json()["calls"]
    assert len(calls) == 1
    assert calls[0]["number"] == "+37360123456"


def test_simulate_call_disabled_outside_dev(client, agents, app):
    app.state.settings.environment = "prod"
    response = client.post("/api/dev/simulate-call", json={"number": "+37360000000"}, headers=agent_headers(agents["alice"]))
    assert response.status_code == 404
