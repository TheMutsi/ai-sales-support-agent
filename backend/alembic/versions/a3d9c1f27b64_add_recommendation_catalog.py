from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = 'a3d9c1f27b64'
down_revision: Union[str, Sequence[str], None] = '5b1e7a9c3d42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'recommendation_types',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('card_template', sa.String(), nullable=False),
        sa.Column('field_schema', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'key'),
        sa.UniqueConstraint('id', 'tenant_id', name='uq_recommendation_types_id_tenant'),
        sa.CheckConstraint("card_template IN ('product_card')", name='ck_recommendation_types_card_template'),
    )
    op.create_index(op.f('ix_recommendation_types_tenant_id'), 'recommendation_types', ['tenant_id'], unique=False)

    op.create_table(
        'recommendation_items',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('type_id', sa.UUID(), nullable=False),
        sa.Column('external_id', sa.String(), nullable=False),
        sa.Column('product_id', sa.String(), nullable=True),
        sa.Column('pack_size', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('short_desc', sa.Text(), server_default='', nullable=False),
        sa.Column('long_desc', sa.Text(), server_default='', nullable=False),
        sa.Column('price_cents', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(length=3), server_default='usd', nullable=False),
        sa.Column('rating', sa.Float(), nullable=True),
        sa.Column('image_url', sa.String(), nullable=True),
        sa.Column('url', sa.String(), nullable=True),
        sa.Column('extra', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('status', sa.String(), server_default='draft', nullable=False),
        sa.Column('enrichment_status', sa.String(), server_default='pending', nullable=False),
        sa.Column('embedding', Vector(768), nullable=True),
        sa.Column(
            'search_tsv', postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', title || ' ' || short_desc || ' ' || long_desc)", persisted=True),
            nullable=True,
        ),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status IN ('draft', 'active', 'archived')", name='ck_recommendation_items_status'),
        sa.CheckConstraint(
            "enrichment_status IN ('pending', 'ready', 'failed')", name='ck_recommendation_items_enrichment_status'
        ),
        sa.CheckConstraint('price_cents >= 0', name='ck_recommendation_items_price'),
        sa.CheckConstraint('rating IS NULL OR rating BETWEEN 0 AND 5', name='ck_recommendation_items_rating'),
        sa.CheckConstraint("image_url IS NULL OR image_url ~* '^https://'", name='ck_recommendation_items_image_https'),
        sa.CheckConstraint("url IS NULL OR url ~* '^https?://'", name='ck_recommendation_items_url_http'),
        sa.CheckConstraint('pack_size > 0', name='ck_recommendation_items_pack_size'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(
            ['type_id', 'tenant_id'], ['recommendation_types.id', 'recommendation_types.tenant_id'],
            name='fk_recommendation_items_type_tenant',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'external_id'),
        sa.UniqueConstraint('id', 'tenant_id', name='uq_recommendation_items_id_tenant'),
    )
    op.create_index(op.f('ix_recommendation_items_tenant_id'), 'recommendation_items', ['tenant_id'], unique=False)
    op.create_index(
        'ix_recommendation_items_tenant_product', 'recommendation_items', ['tenant_id', 'product_id'], unique=False
    )
    op.create_index(
        'ix_recommendation_items_search_tsv', 'recommendation_items', ['search_tsv'], unique=False,
        postgresql_using='gin',
    )

    op.create_table(
        'item_offers',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('item_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('label', sa.String(), nullable=False),
        sa.Column('quantity', sa.Integer(), server_default='1', nullable=False),
        sa.Column('price_cents', sa.Integer(), nullable=False),
        sa.Column('compare_at_cents', sa.Integer(), nullable=True),
        sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
        sa.CheckConstraint("kind IN ('pack', 'discount', 'bundle')", name='ck_item_offers_kind'),
        sa.CheckConstraint('price_cents >= 0', name='ck_item_offers_price'),
        sa.CheckConstraint('compare_at_cents >= 0', name='ck_item_offers_compare_at'),
        sa.CheckConstraint('quantity > 0', name='ck_item_offers_quantity'),
        sa.CheckConstraint(
            'compare_at_cents IS NULL OR compare_at_cents > price_cents', name='ck_item_offers_compare_at_above_price'
        ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(
            ['item_id', 'tenant_id'], ['recommendation_items.id', 'recommendation_items.tenant_id'],
            name='fk_item_offers_item_tenant', ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_item_offers_item_id', 'item_offers', ['item_id'], unique=False)

    op.create_table(
        'recommendation_tags',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('slug', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), server_default='', nullable=False),
        sa.Column('embedding', Vector(768), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'slug'),
        sa.UniqueConstraint('id', 'tenant_id', name='uq_recommendation_tags_id_tenant'),
    )
    op.create_index(op.f('ix_recommendation_tags_tenant_id'), 'recommendation_tags', ['tenant_id'], unique=False)

    op.create_table(
        'item_tags',
        sa.Column('item_id', sa.UUID(), nullable=False),
        sa.Column('tag_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('weight', sa.Float(), nullable=False),
        sa.Column('why', sa.Text(), server_default='', nullable=False),
        sa.Column('pinned', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('is_complement', sa.Boolean(), server_default='false', nullable=False),
        sa.CheckConstraint('weight >= 0 AND weight <= 1', name='ck_item_tags_weight'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(
            ['item_id', 'tenant_id'], ['recommendation_items.id', 'recommendation_items.tenant_id'],
            name='fk_item_tags_item_tenant', ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['tag_id', 'tenant_id'], ['recommendation_tags.id', 'recommendation_tags.tenant_id'],
            name='fk_item_tags_tag_tenant', ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('item_id', 'tag_id'),
    )
    op.create_index('ix_item_tags_tag_id', 'item_tags', ['tag_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_item_tags_tag_id', table_name='item_tags')
    op.drop_table('item_tags')
    op.drop_index(op.f('ix_recommendation_tags_tenant_id'), table_name='recommendation_tags')
    op.drop_table('recommendation_tags')
    op.drop_index('ix_item_offers_item_id', table_name='item_offers')
    op.drop_table('item_offers')
    op.drop_index('ix_recommendation_items_tenant_product', table_name='recommendation_items')
    op.drop_index('ix_recommendation_items_search_tsv', table_name='recommendation_items', postgresql_using='gin')
    op.drop_index(op.f('ix_recommendation_items_tenant_id'), table_name='recommendation_items')
    op.drop_table('recommendation_items')
    op.drop_index(op.f('ix_recommendation_types_tenant_id'), table_name='recommendation_types')
    op.drop_table('recommendation_types')
