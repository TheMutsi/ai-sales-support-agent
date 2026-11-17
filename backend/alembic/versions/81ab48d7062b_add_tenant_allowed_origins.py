from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '81ab48d7062b'
down_revision: Union[str, Sequence[str], None] = '20395d05e92c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tenants', sa.Column('allowed_origins', sa.JSON(), server_default='[]', nullable=False))


def downgrade() -> None:
    op.drop_column('tenants', 'allowed_origins')
