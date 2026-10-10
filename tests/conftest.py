from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.ami.mock import MockAMI
from app.config import Settings
from app.db import Base, build_engine, build_session_factory
from app.main import create_app
from app.models import AgentMapping
from app.zammad.client import MockZammad


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        ami_host="",
        managed_queues=["sales", "support"],
        ami_retry_backoff=0.0,
        wrap_up_enabled=False,
    )


@pytest.fixture
def engine(settings):
    engine = build_engine(settings.database_url)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session_factory(engine):
    return build_session_factory(engine)


@pytest.fixture
def agents(session_factory):
    with session_factory() as db:
        alice = AgentMapping(
            name="Alice",
            extension="1001",
            asterisk_interface="PJSIP/1001",
            zammad_user_id=101,
            queues=["sales", "support"],
        )
        bob = AgentMapping(
            name="Bob",
            extension="1002",
            asterisk_interface="PJSIP/1002",
            zammad_user_id=102,
            queues=["sales"],
        )
        db.add_all([alice, bob])
        db.commit()
        db.refresh(alice)
        db.refresh(bob)
        return {"alice": alice.id, "bob": bob.id}


@pytest.fixture
def app(settings, engine):
    application = create_app(settings)
    application.state.engine = engine
    application.state.session_factory = build_session_factory(engine)
    return application


@pytest.fixture
def client(app) -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def ami(app) -> MockAMI:
    return app.state.ami


@pytest.fixture
def zammad(app) -> MockZammad:
    return app.state.zammad


def agent_headers(agent_id: int) -> dict[str, str]:
    return {"X-Agent-Id": str(agent_id)}


def admin_headers() -> dict[str, str]:
    return {"X-Role": "admin"}
