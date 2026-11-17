from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '5b1e7a9c3d42'
down_revision: Union[str, Sequence[str], None] = '2af2ea5efcfb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_DELETE_DOCUMENTS_WITHOUT_A_TENANT = "DELETE FROM documents WHERE tenant_id IS NULL"
_BACKFILL_ORIGIN = (
    "UPDATE documents SET origin = CASE WHEN source LIKE 'admin/%' THEN 'admin' ELSE 'seed' END"
)
_MORE_THAN_ONE_TENANT_HAS_DOCUMENTS = "SELECT count(DISTINCT tenant_id) FROM documents"
_DROP_CHUNKS_OF_VERSIONS_THAT_ARE_NOT_PUBLISHED = (
    "DELETE FROM document_chunks WHERE document_version_id NOT IN (SELECT published_version_id FROM documents "
    "WHERE published_version_id IS NOT NULL)"
)
_RESTORE_DOCUMENT_CONTENT_FROM_THE_PUBLISHED_VERSION = (
    "UPDATE documents d SET content = COALESCE("
    "(SELECT v.content FROM document_versions v WHERE v.id = d.published_version_id), "
    "(SELECT v.content FROM document_versions v WHERE v.document_id = d.id ORDER BY v.version DESC LIMIT 1), '')"
)
_POINT_CHUNKS_BACK_AT_THEIR_DOCUMENT = (
    "UPDATE document_chunks c SET document_id = v.document_id FROM document_versions v "
    "WHERE v.id = c.document_version_id"
)


def upgrade() -> None:
    op.create_table(
        'document_versions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('document_id', sa.UUID(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('published_by', sa.String(), nullable=True),
        sa.CheckConstraint("status IN ('draft', 'published', 'archived')", name='ck_document_versions_status'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('document_id', 'version'),
    )
    op.create_index(op.f('ix_document_versions_document_id'), 'document_versions', ['document_id'], unique=False)

    op.add_column('documents', sa.Column('tenant_id', sa.UUID(), nullable=True))
    op.add_column('documents', sa.Column('when_to_use', sa.Text(), server_default='', nullable=False))
    op.add_column('documents', sa.Column('published_version_id', sa.UUID(), nullable=True))
    op.add_column('documents', sa.Column('origin', sa.String(), server_default='admin', nullable=False))
    op.create_check_constraint('ck_documents_origin', 'documents', "origin IN ('seed', 'admin')")
    op.execute(_BACKFILL_ORIGIN)
    op.execute(_DELETE_DOCUMENTS_WITHOUT_A_TENANT)

    op.add_column('document_chunks', sa.Column('document_version_id', sa.UUID(), nullable=True))
    op.drop_constraint('document_chunks_document_id_chunk_index_key', 'document_chunks', type_='unique')
    op.drop_constraint('document_chunks_document_id_fkey', 'document_chunks', type_='foreignkey')
    op.drop_column('document_chunks', 'document_id')
    op.alter_column('document_chunks', 'document_version_id', nullable=False)
    op.create_foreign_key(
        'document_chunks_document_version_id_fkey',
        'document_chunks', 'document_versions', ['document_version_id'], ['id'], ondelete='CASCADE',
    )
    op.create_unique_constraint(
        'document_chunks_document_version_id_chunk_index_key', 'document_chunks', ['document_version_id', 'chunk_index']
    )
    op.add_column(
        'document_chunks',
        sa.Column(
            'content_tsv', postgresql.TSVECTOR(), sa.Computed("to_tsvector('simple', content)", persisted=True),
            nullable=True,
        ),
    )
    op.create_index(
        'ix_document_chunks_content_tsv', 'document_chunks', ['content_tsv'], unique=False, postgresql_using='gin'
    )

    op.drop_column('documents', 'content')
    op.drop_constraint('uq_documents_source', 'documents', type_='unique')
    op.alter_column('documents', 'tenant_id', nullable=False)
    op.create_foreign_key('documents_tenant_id_fkey', 'documents', 'tenants', ['tenant_id'], ['id'])
    op.create_index(op.f('ix_documents_tenant_id'), 'documents', ['tenant_id'], unique=False)
    op.create_unique_constraint('uq_documents_tenant_source', 'documents', ['tenant_id', 'source'])
    op.create_foreign_key(
        'fk_documents_published_version', 'documents', 'document_versions', ['published_version_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    tenants_with_documents = op.get_bind().execute(sa.text(_MORE_THAN_ONE_TENANT_HAS_DOCUMENTS)).scalar()
    if tenants_with_documents > 1:
        raise RuntimeError(
            'cannot downgrade: documents of more than one tenant exist and the older schema keeps one '
            'global document per source; delete the documents of all but one tenant first'
        )
    op.drop_constraint('fk_documents_published_version', 'documents', type_='foreignkey')
    op.add_column('documents', sa.Column('content', sa.Text(), server_default='', nullable=False))
    op.execute(_RESTORE_DOCUMENT_CONTENT_FROM_THE_PUBLISHED_VERSION)
    op.alter_column('documents', 'content', server_default=None)
    op.execute(_DROP_CHUNKS_OF_VERSIONS_THAT_ARE_NOT_PUBLISHED)

    op.drop_index('ix_document_chunks_content_tsv', table_name='document_chunks', postgresql_using='gin')
    op.drop_column('document_chunks', 'content_tsv')
    op.add_column('document_chunks', sa.Column('document_id', sa.UUID(), nullable=True))
    op.execute(_POINT_CHUNKS_BACK_AT_THEIR_DOCUMENT)
    op.drop_constraint('document_chunks_document_version_id_chunk_index_key', 'document_chunks', type_='unique')
    op.drop_constraint('document_chunks_document_version_id_fkey', 'document_chunks', type_='foreignkey')
    op.drop_column('document_chunks', 'document_version_id')
    op.alter_column('document_chunks', 'document_id', nullable=False)
    op.create_foreign_key(
        'document_chunks_document_id_fkey', 'document_chunks', 'documents', ['document_id'], ['id'],
        ondelete='CASCADE',
    )
    op.create_unique_constraint(
        'document_chunks_document_id_chunk_index_key', 'document_chunks', ['document_id', 'chunk_index']
    )

    op.drop_constraint('uq_documents_tenant_source', 'documents', type_='unique')
    op.drop_index(op.f('ix_documents_tenant_id'), table_name='documents')
    op.drop_constraint('documents_tenant_id_fkey', 'documents', type_='foreignkey')
    op.drop_constraint('ck_documents_origin', 'documents', type_='check')
    op.drop_column('documents', 'origin')
    op.drop_column('documents', 'published_version_id')
    op.drop_column('documents', 'when_to_use')
    op.drop_column('documents', 'tenant_id')
    op.create_unique_constraint('uq_documents_source', 'documents', ['source'])

    op.drop_index(op.f('ix_document_versions_document_id'), table_name='document_versions')
    op.drop_table('document_versions')
