from __future__ import annotations

from sqlalchemy import select

from app.config import get_settings
from app.db import build_engine, build_session_factory
from app.models import AgentMapping

DEMO_AGENTS = [
    {"name": "Alice", "extension": "1001", "asterisk_interface": "PJSIP/1001", "zammad_user_id": 101},
    {"name": "Bob", "extension": "1002", "asterisk_interface": "PJSIP/1002", "zammad_user_id": 102},
]


def main() -> None:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    with session_factory() as db:
        for spec in DEMO_AGENTS:
            existing = db.scalar(select(AgentMapping).where(AgentMapping.extension == spec["extension"]))
            if existing is not None:
                continue
            db.add(AgentMapping(queues=settings.managed_queues, **spec))
        db.commit()
    print(f"seeded demo agents into {settings.database_url}")


if __name__ == "__main__":
    main()
