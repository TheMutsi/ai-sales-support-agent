from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '20395d05e92c'
down_revision: Union[str, Sequence[str], None] = '696f23dd6a2e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('kind', sa.String(), server_default='text', nullable=False))


def downgrade() -> None:
    op.drop_column('messages', 'kind')
