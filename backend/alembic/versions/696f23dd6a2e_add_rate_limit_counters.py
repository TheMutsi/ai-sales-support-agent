from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '696f23dd6a2e'
down_revision: Union[str, Sequence[str], None] = 'e906874f1c6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('rate_limit_counters',
    sa.Column('key', sa.String(), nullable=False),
    sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('key', 'window_start')
    )
    op.create_index('ix_rate_limit_counters_window_start', 'rate_limit_counters', ['window_start'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_rate_limit_counters_window_start', table_name='rate_limit_counters')
    op.drop_table('rate_limit_counters')
