"""add_query_result_chart_config_to_messages

Revision ID: 8b924be81e2e
Revises: 6d25b48904ed
Create Date: 2026-05-30 13:31:55.512070

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b924be81e2e'
down_revision: Union[str, Sequence[str], None] = '6d25b48904ed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('query_result', sa.Text(), nullable=True))
    op.add_column('messages', sa.Column('chart_config', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'chart_config')
    op.drop_column('messages', 'query_result')
