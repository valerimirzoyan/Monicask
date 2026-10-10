from __future__ import annotations

from typing import Any

import httpx

from app.db import utcnow
from app.phone import match as phone_match
from app.phone import normalize


class ZammadError(Exception):
    pass


class ZammadClient:
    mode = "base"

    def assign_ticket(self, ticket_id: str, zammad_user_id: int) -> None:  # pragma: no cover
        raise NotImplementedError

    def set_status(self, ticket_id: str, status: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def list_tickets(self, limit: int = 25) -> list[dict]:  # pragma: no cover
        raise NotImplementedError

    def get_ticket(self, ticket_id: str) -> dict | None:  # pragma: no cover
        raise NotImplementedError

    def search_contact(self, number: str) -> dict | None:  # pragma: no cover
        raise NotImplementedError

    def create_ticket(self, subject: str, body: str, customer: str = "", priority: str = "2 normal") -> dict:  # pragma: no cover
        raise NotImplementedError


class MockZammad(ZammadClient):
    mode = "mock"

    def __init__(self) -> None:
        self.tickets: dict[str, dict[str, Any]] = {}
        self.contacts: dict[int, dict[str, Any]] = {}
        self.calls: list[tuple[str, str, Any]] = []
        self.fail_next: int = 0
        self._ticket_seq = 0
        self._contact_seq = 0
        self._seed()

    def _seed(self) -> None:
        for name, number, email in (
            ("ИП Ромашка", "+37360123456", "romashka@example.com"),
            ("ООО Вектор", "+37369234567", "vector@example.com"),
        ):
            self._contact_seq += 1
            self.contacts[self._contact_seq] = {
                "id": self._contact_seq,
                "name": name,
                "phone": number,
                "email": email,
                "number_normalized": normalize(number),
            }
        for title, state, priority in (
            ("Интернет не работает", "open", "2 normal"),
            ("Не приходит счёт на почту", "open", "1 low"),
            ("Настроить переадресацию", "open", "3 high"),
        ):
            self.create_ticket(subject=title, body="", customer="", priority=priority, state=state)

    def _guard(self, action: str) -> None:
        if self.fail_next > 0:
            self.fail_next -= 1
            raise ZammadError(f"mock Zammad rejected {action}")

    def get_ticket(self, ticket_id: str) -> dict | None:
        return self.tickets.get(str(ticket_id))

    def list_tickets(self, limit: int = 25) -> list[dict]:
        open_tickets = [t for t in self.tickets.values() if t["state"] in ("new", "open")]
        open_tickets.sort(key=lambda t: t["created_at"], reverse=True)
        return open_tickets[:limit]

    def search_contact(self, number: str) -> dict | None:
        normalized = normalize(number)
        if not normalized:
            return None
        for contact in self.contacts.values():
            if phone_match(contact.get("phone"), number) or phone_match(contact.get("number_normalized"), normalized):
                return contact
        return None

    def create_ticket(
        self,
        subject: str,
        body: str,
        customer: str = "",
        priority: str = "2 normal",
        state: str = "new",
    ) -> dict:
        self._guard("create_ticket")
        self._ticket_seq += 1
        ticket_id = str(self._ticket_seq)
        ticket = {
            "id": ticket_id,
            "number": f"20{self._ticket_seq:06d}",
            "title": subject or "(без темы)",
            "body": body,
            "customer": customer,
            "priority": priority,
            "state": state,
            "owner_id": None,
            "created_at": utcnow().isoformat(),
        }
        self.tickets[ticket_id] = ticket
        self.calls.append(("create_ticket", ticket_id, subject))
        return ticket

    def assign_ticket(self, ticket_id: str, zammad_user_id: int) -> None:
        self._guard("assign")
        ticket = self.tickets.setdefault(
            str(ticket_id),
            {"id": str(ticket_id), "title": "", "state": "open", "owner_id": None, "created_at": utcnow().isoformat()},
        )
        ticket["owner_id"] = zammad_user_id
        self.calls.append(("assign", str(ticket_id), zammad_user_id))

    def set_status(self, ticket_id: str, status: str) -> None:
        self._guard("set_status")
        ticket = self.tickets.setdefault(
            str(ticket_id),
            {"id": str(ticket_id), "title": "", "state": "open", "owner_id": None, "created_at": utcnow().isoformat()},
        )
        ticket["state"] = status
        self.calls.append(("set_status", str(ticket_id), status))


class RestZammad(ZammadClient):
    mode = "real"

    def __init__(self, base_url: str, token: str, timeout: float = 5.0) -> None:
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Token token={token}"},
            timeout=timeout,
        )

    def assign_ticket(self, ticket_id: str, zammad_user_id: int) -> None:
        self._update(ticket_id, {"owner_id": zammad_user_id})

    def set_status(self, ticket_id: str, status: str) -> None:
        self._update(ticket_id, {"status": status})

    def get_ticket(self, ticket_id: str) -> dict | None:
        try:
            response = self.client.get(f"/api/v1/tickets/{ticket_id}")
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise ZammadError(f"Zammad request failed: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ZammadError(f"Zammad request failed: {exc}") from exc
        return self._to_ticket(response.json())

    def list_tickets(self, limit: int = 25) -> list[dict]:
        # Stage 0: confirm the search endpoint/fields on the installed Zammad version.
        try:
            response = self.client.get("/api/v1/tickets/search", params={"query": "state:new OR state:open", "limit": limit})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ZammadError(f"Zammad request failed: {exc}") from exc
        payload = response.json()
        return [self._to_ticket(item) for item in payload.get("tickets", payload if isinstance(payload, list) else [])]

    def search_contact(self, number: str) -> dict | None:
        try:
            response = self.client.get("/api/v1/users/search", params={"query": number, "limit": 10})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ZammadError(f"Zammad request failed: {exc}") from exc
        for user in response.json():
            if phone_match(user.get("phone"), number):
                return user
        return None

    def create_ticket(self, subject: str, body: str, customer: str = "", priority: str = "2 normal") -> dict:
        payload = {
            "title": subject,
            "group": "Users",
            "priority": priority,
            "state": "new",
            "customer_id": customer or "guess:auto",
            "article": {"subject": subject, "body": body, "type": "note", "internal": False},
        }
        try:
            response = self.client.post("/api/v1/tickets", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ZammadError(f"Zammad request failed: {exc}") from exc
        return self._to_ticket(response.json())

    def _update(self, ticket_id: str, attributes: dict[str, Any]) -> None:
        try:
            response = self.client.put(f"/api/v1/tickets/{ticket_id}", json={"ticket": attributes})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ZammadError(f"Zammad request failed: {exc}") from exc

    @staticmethod
    def _to_ticket(raw: dict) -> dict:
        return {
            "id": str(raw.get("id")),
            "number": str(raw.get("number", raw.get("id", ""))),
            "title": raw.get("title", ""),
            "state": raw.get("state", raw.get("state_id", "")),
            "priority": raw.get("priority", raw.get("priority_id", "")),
            "owner_id": raw.get("owner_id"),
            "customer": raw.get("customer", raw.get("customer_id", "")),
            "created_at": raw.get("created_at", ""),
        }


def build_zammad(settings) -> ZammadClient:
    if settings.zammad_base_url:
        return RestZammad(settings.zammad_base_url, settings.zammad_token, settings.zammad_timeout)
    return MockZammad()
