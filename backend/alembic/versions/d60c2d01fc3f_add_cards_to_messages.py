from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd60c2d01fc3f'
down_revision: Union[str, Sequence[str], None] = 'c405770e6f9d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('cards', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'cards')
