"""add folders table and folder_id to conversations

Revision ID: 24d8ce000324
Revises: 8b924be81e2e
Create Date: 2026-05-30 14:14:07.212108

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '24d8ce000324'
down_revision: Union[str, Sequence[str], None] = '8b924be81e2e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    # folders table may already exist (created by Base.metadata.create_all on startup)
    if "folders" not in tables:
        op.create_table(
            "folders",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    if "folder_id" not in [c["name"] for c in inspector.get_columns("conversations")]:
        with op.batch_alter_table("conversations") as batch_op:
            batch_op.add_column(sa.Column("folder_id", sa.String(length=36), nullable=True))
            batch_op.create_foreign_key(
                None, "folders", ["folder_id"], ["id"], ondelete="SET NULL"
            )


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    if "folder_id" in [c["name"] for c in inspector.get_columns("conversations")]:
        with op.batch_alter_table("conversations") as batch_op:
            batch_op.drop_constraint(None, type_="foreignkey")
            batch_op.drop_column("folder_id")

    if "folders" in tables:
        op.drop_table("folders")
