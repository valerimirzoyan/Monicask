# Monicask — Zammad + FreePBX/Asterisk

Reference implementation of the **Task & Agent State Service** and operator API described in
`TZ_Zammad_FreePBX_Agent_Workplace_RU.docx`. This is the **Stage 1 prototype**: it runs end-to-end
without any live Zammad/Asterisk instance because both integrations ship with mock drivers.

## What is implemented (Stage 1)

| TZ item | Where |
|---|---|
| §4.3 operator states + priority (`offline/break > blocking > ready`, wrap-up) | `app/state.py` |
| §4.2 blocking / background work modes | `app/models.py`, `app/services/tasks.py` |
| §5 FR-01..FR-14 core flows | `app/api/*`, `app/services/tasks.py` |
| §6 scenarios A–D (multiple tasks, manual break, reconcile) | tested in `tests/test_api_flow.py` |
| §7.2 AMI pause/unpause + confirmation + retry | `app/ami/*` |
| §7.1 Zammad REST client + webhook ingestion + dedup | `app/zammad/client.py`, `app/api/routes_webhook.py` |
| §8 data model (`agent_mapping`, `work_session`, `agent_state`, `integration_event` + `audit_log`) | `app/models.py`, `alembic/versions/` |
| §9 service API | `app/api/` (OpenAPI at `/docs`) |
| §10 non-functional (open-source stack, env secrets, UTC, audit) | `README`, `.env.example` |
| §11 acceptance tests | `tests/` |
| FR-09 operator panel + Stage 4 UI | `app/web/` (`/`) |

## Operator UI

A dependency-free single-page UI is served at <http://localhost:8000/> (Stage 4). It polls the API and
covers the operator panel from FR-09:

- phone/availability status pill (`ready / busy_task / break / offline / wrap_up`) + AMI confirmation
- action buttons: **Готов / Перерыв / Отключиться** and per-task **Завершить / Приступить / В фон**
- my blocking and background tasks, the Zammad ticket queue, recent calls, and an audit/event feed
- caller card: enter or simulate a number → contact lookup (FR-01) → create a ticket (FR-02)
- a sync-error banner (§FR-14) when the Asterisk state cannot be confirmed

Pick the acting agent in the top bar (`X-Agent-Id`). In dev, `POST /api/dev/simulate-call` pushes a
fake inbound call so the caller-card flow can be demonstrated without telephony.


## Quick start (no external systems)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# SQLite + mock AMI + mock Zammad
export DATABASE_URL=sqlite:///./monicask.db
export ENVIRONMENT=dev
alembic upgrade head
python -m scripts.seed_demo

uvicorn app.main:app --reload
```

Interactive docs: <http://localhost:8000/docs> · Health: <http://localhost:8000/health>

### Docker Compose (PostgreSQL)

```bash
cp .env.example .env
docker compose up --build
```

### Try the flow

```bash
H='X-Agent-Id: 1'
# Start a blocking task -> agent becomes busy_task and is paused in queues
curl -s -XPOST localhost:8000/api/tickets/42/start -H "$H" -H 'Content-Type: application/json' \
     -d '{"work_mode":"blocking"}'

# Current computed state
curl -s localhost:8000/api/agents/me/state -H "$H"

# Background task -> agent stays ready
curl -s -XPOST localhost:8000/api/tickets/43/start -H "$H" -H 'Content-Type: application/json' \
     -d '{"work_mode":"background"}'

# Finish and return to queues
curl -s -XPOST localhost:8000/api/tickets/42/complete -H "$H" -H 'Content-Type: application/json' -d '{}'

# Admin overview / reconcile
curl -s localhost:8000/api/admin/agents -H 'X-Role: admin'
curl -s -XPOST localhost:8000/api/admin/agents/1/reconcile -H 'X-Role: admin'
```

## Architecture

```
operator UI (Stage 4) ──HTTPS/API──► app/main.py (FastAPI)
                                          │
                    ┌─────────────────────┼───────────────────────┐
                    ▼                     ▼                        ▼
             services/tasks.py      ami/manager.py          zammad/client.py
             (state machine,        (pause/unpause,         (REST + webhook,
              idempotency, audit)    retry, reconcile)       dedup)
                    │                     │                        │
               SQLAlchemy            AMI (AMS/ARI)              Zammad REST
                    ▼                     ▼
              PostgreSQL            FreePBX/Asterisk
```

**Availability is computed server-side** and never derived from Zammad statuses.
`asterisk_confirmed` in the state response is `true` only when the AMI command was acknowledged
(§11 / §FR-14: a `ready` state is never reported as confirmed while the queue state is unknown).

## Integration modes

Both integrations switch on configuration; empty endpoints select the mock:

- `AMI_HOST` empty → `MockAMI` (in-process, records pause state, supports forced failures for tests)
- `ZAMMAD_BASE_URL` empty → `MockZammad`
- `RealAMI` speaks the AMI text protocol (Login, `PauseQueueMember` with `QueuePause` fallback,
  `QueueStatus` snapshot) over a reader thread — validated against a fake AMI server in tests.

## Stage 0 items to verify against the real installation (per TZ §7, §13, §15)

1. Zammad / FreePBX / Asterisk versions and installation method.
2. Exact AMI action accepted for queue pause in the target Asterisk (`PauseQueueMember` vs `QueuePause`).
3. Zammad webhook payload shape and reliable event id (default dedup currently hashes the payload).
4. Zammad ticket field mapping (`owner_id`, `status` vs `state_id`) and required custom fields.
5. Which queues are managed, plus interface naming (`PJSIP/1001` vs `Local/1001@from-internal`).
6. WhatsApp/Telegram channel availability on the installed Zammad.
7. Whether the operator UI is separate (current plan) or embedded into Zammad.

## Authentication

Stage 1 uses development headers: `X-Agent-Id` for operator endpoints, `X-Role: admin` for admin
endpoints, and optional `X-Webhook-Token` for the Zammad webhook. Replace with Zammad OAuth/JWT and a
role model (§10) before production.

## Scope not in Stage 1

- Production-grade front-end framework/build pipeline (the current UI is vanilla JS, no build step).
- Background retry worker for `integration_event.status=retry` (events are queued and visible; the
  worker and scheduling are Stage 2/3).
- Webhook-driven auto launch of the client card (FR-01) — AMI call events are consumed in Stage 3;
  the UI currently uses manual entry / the dev simulate endpoint.
- CRM funnel/companies/deals.

## Development

```bash
ruff check app tests      # lint
mypy app                  # type check
pytest -q                 # tests
alembic revision --autogenerate -m "change"   # new migration
```

## Components & licenses

Runtime stack is fully open-source: FastAPI, SQLAlchemy, Alembic, Pydantic (MIT/BSD/Apache-2.0),
PostgreSQL (PostgreSQL License). Asterisk (GPLv2) and Zammad (AGPLv3) are consumed as external
services, not linked. The final component/license list required by §10 is produced from
`requirements.txt` and the base image at delivery time.
