from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'bc075df9dded'
down_revision: Union[str, Sequence[str], None] = 'cf84eaca06e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('tenant_smtp',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('host', sa.String(), nullable=False),
    sa.Column('port', sa.Integer(), nullable=False),
    sa.Column('security', sa.String(), nullable=False),
    sa.Column('username', sa.String(), nullable=True),
    sa.Column('password_encrypted', sa.String(), nullable=True),
    sa.Column('from_address', sa.String(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.CheckConstraint("security in ('starttls', 'ssl', 'none')", name='ck_tenant_smtp_security'),
    sa.PrimaryKeyConstraint('tenant_id')
    )


def downgrade() -> None:
    op.drop_table('tenant_smtp')
