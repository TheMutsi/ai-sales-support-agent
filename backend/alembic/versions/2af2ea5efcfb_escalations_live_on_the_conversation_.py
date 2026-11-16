"""escalations live on the conversation, drop tickets

Revision ID: 2af2ea5efcfb
Revises: c901507dde60
Create Date: 2026-11-03 16:11:39.960854

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2af2ea5efcfb'
down_revision: Union[str, Sequence[str], None] = 'c901507dde60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_presence",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_name", sa.String(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("tenant_id", "agent_name"),
    )
    op.add_column("tenants", sa.Column("support_hours", sa.JSON(), nullable=True))
    for name in ("escalation_reference", "escalation_route", "escalation_reason",
                 "escalation_category", "escalation_status", "escalation_resolved_by"):
        op.add_column("conversations", sa.Column(name, sa.String(), nullable=True))
    op.add_column("conversations", sa.Column("escalation_notes", sa.Text(), nullable=True))
    for name in ("escalated_at", "escalation_resolved_at"):
        op.add_column("conversations", sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    # Conversations that already had a ticket keep it: its id, as a follow-up number, and its state.
    op.execute(
        """
        UPDATE conversations c SET
            escalation_reference = 'MF-' || upper(substr(md5(t.id::text), 1, 8)),
            escalation_route = 'live',
            escalation_category = t.category,
            escalation_status = CASE WHEN t.status = 'resolved' THEN 'resolved' ELSE 'open' END,
            escalated_at = t.created_at AT TIME ZONE 'UTC',
            escalation_resolved_at = t.resolved_at AT TIME ZONE 'UTC',
            escalation_notes = t.resolution_notes
        FROM tickets t WHERE c.handoff_ticket_id = t.id
        """
    )
    op.create_unique_constraint(
        "uq_conversations_escalation_reference", "conversations", ["escalation_reference"]
    )
    op.drop_constraint(op.f("fk_conversations_handoff_ticket_id"), "conversations", type_="foreignkey")
    op.drop_column("conversations", "handoff_ticket_id")
    op.drop_table("tickets")


def downgrade() -> None:
    op.create_table(
        "tickets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("priority", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("conversations", sa.Column("handoff_ticket_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_conversations_handoff_ticket_id"), "conversations", "tickets",
        ["handoff_ticket_id"], ["id"], ondelete="SET NULL",
    )
    op.drop_constraint("uq_conversations_escalation_reference", "conversations", type_="unique")
    for name in ("escalation_reference", "escalation_route", "escalation_reason",
                 "escalation_category", "escalation_status", "escalation_resolved_by",
                 "escalation_notes", "escalated_at", "escalation_resolved_at"):
        op.drop_column("conversations", name)
    op.drop_column("tenants", "support_hours")
    op.drop_table("agent_presence")
