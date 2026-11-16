"""Which back-office agents are there to answer a live escalation.

An agent is "available" while their back office keeps asking for the inbox: each poll of it records
a sighting, and one not seen for `AVAILABLE_FOR` stops counting. No separate "I'm online" button to
forget to switch off, and a closed tab leaves by itself.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import AgentPresence

# The inbox polls every few seconds (see the back office's EscalationsPage), so this tolerates a
# few missed polls and a brief network gap without calling the agent gone.
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
