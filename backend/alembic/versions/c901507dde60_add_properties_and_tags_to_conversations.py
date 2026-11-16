from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c901507dde60'
down_revision: Union[str, Sequence[str], None] = '7dee0b60164c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('properties', sa.JSON(), server_default='{}', nullable=False))
    op.add_column('conversations', sa.Column('tags', sa.JSON(), server_default='[]', nullable=False))


def downgrade() -> None:
    op.drop_column('conversations', 'tags')
    op.drop_column('conversations', 'properties')
