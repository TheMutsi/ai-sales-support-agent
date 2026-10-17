"""add tenant allowed origins

Revision ID: 81ab48d7062b
Revises: 20395d05e92c
Create Date: 2026-10-17 13:43:13.395791

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '81ab48d7062b'
down_revision: Union[str, Sequence[str], None] = '20395d05e92c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('tenants', sa.Column('allowed_origins', sa.JSON(), server_default='[]', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('tenants', 'allowed_origins')
