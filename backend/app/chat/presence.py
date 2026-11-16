import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import AgentPresence

AVAILABLE_FOR = timedelta(seconds=45)


def touch(db: Session, *, tenant_id: uuid.UUID, agent_name: str, now: datetime) -> None:
    statement = insert(AgentPresence).values(tenant_id=tenant_id, agent_name=agent_name, last_seen_at=now)
    db.execute(
        statement.on_conflict_do_update(
            index_elements=["tenant_id", "agent_name"], set_={"last_seen_at": statement.excluded.last_seen_at}
        )
    )
    db.commit()


def count_available(db: Session, *, tenant_id: uuid.UUID, now: datetime) -> int:
    return db.scalar(
        select(func.count())
        .select_from(AgentPresence)
        .where(AgentPresence.tenant_id == tenant_id, AgentPresence.last_seen_at >= now - AVAILABLE_FOR)
    ) or 0
