"""add unique constraint on documents.source and cascade delete for document_chunks

Revision ID: 7c42b6d5b88a
Revises: fc9820fe4edd
Create Date: 2026-09-29 22:38:24.769738

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c42b6d5b88a'
down_revision: Union[str, Sequence[str], None] = 'fc9820fe4edd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(op.f('document_chunks_document_id_fkey'), 'document_chunks', type_='foreignkey')
    op.create_foreign_key(
        'document_chunks_document_id_fkey', 'document_chunks', 'documents', ['document_id'], ['id'], ondelete='CASCADE'
    )
    op.create_unique_constraint('uq_documents_source', 'documents', ['source'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_documents_source', 'documents', type_='unique')
    op.drop_constraint('document_chunks_document_id_fkey', 'document_chunks', type_='foreignkey')
    op.create_foreign_key(
        op.f('document_chunks_document_id_fkey'), 'document_chunks', 'documents', ['document_id'], ['id']
    )
