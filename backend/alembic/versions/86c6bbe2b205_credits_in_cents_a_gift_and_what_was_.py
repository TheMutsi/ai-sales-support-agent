from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '86c6bbe2b205'
down_revision: Union[str, Sequence[str], None] = 'd60c2d01fc3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('order_adjustments', 'credit_points', new_column_name='credit_cents')
    op.add_column('order_adjustments', sa.Column('gift', sa.String(), nullable=True))
    op.add_column('orders', sa.Column('item_name', sa.String(), nullable=True))
    op.add_column('orders', sa.Column('item_images', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'item_images')
    op.drop_column('orders', 'item_name')
    op.alter_column('order_adjustments', 'credit_cents', new_column_name='credit_points')
    op.drop_column('order_adjustments', 'gift')
