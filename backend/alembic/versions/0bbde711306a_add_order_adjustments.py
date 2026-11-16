from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0bbde711306a'
down_revision: Union[str, Sequence[str], None] = 'bc075df9dded'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('order_adjustments',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('order_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('refund_cents', sa.Integer(), nullable=True),
    sa.Column('credit_points', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('order_id')
    )


def downgrade() -> None:
    op.drop_table('order_adjustments')
