"""add message kind

Revision ID: 20395d05e92c
Revises: 696f23dd6a2e
Create Date: 2026-10-17 12:27:30.031164

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20395d05e92c'
down_revision: Union[str, Sequence[str], None] = '696f23dd6a2e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('messages', sa.Column('kind', sa.String(), server_default='text', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('messages', 'kind')
