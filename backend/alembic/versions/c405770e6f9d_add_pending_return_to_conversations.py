from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c405770e6f9d'
down_revision: Union[str, Sequence[str], None] = '0bbde711306a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('pending_return_order_id', sa.String(), nullable=True))
    op.add_column('conversations', sa.Column('pending_return_stage', sa.String(), nullable=True))
    op.add_column('conversations', sa.Column('pending_return_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('conversations', 'pending_return_at')
    op.drop_column('conversations', 'pending_return_stage')
    op.drop_column('conversations', 'pending_return_order_id')
