from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'cf84eaca06e4'
down_revision: Union[str, Sequence[str], None] = '49e84aa3e4e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('handoff_status', sa.String(), server_default='none', nullable=False))
    op.add_column('conversations', sa.Column('handoff_agent_name', sa.String(), nullable=True))
    op.add_column('conversations', sa.Column('handoff_requested_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('conversations', sa.Column('handoff_ticket_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_conversations_handoff_ticket_id', 'conversations', 'tickets', ['handoff_ticket_id'], ['id'], ondelete='SET NULL')
    op.add_column('messages', sa.Column('author_name', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'author_name')
    op.drop_constraint('fk_conversations_handoff_ticket_id', 'conversations', type_='foreignkey')
    op.drop_column('conversations', 'handoff_ticket_id')
    op.drop_column('conversations', 'handoff_requested_at')
    op.drop_column('conversations', 'handoff_agent_name')
    op.drop_column('conversations', 'handoff_status')
