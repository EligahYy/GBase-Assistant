"""add semantic models + nl2sql cases tables"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "00a19da4f2a5"
down_revision: str | Sequence[str] | None = "24d8ce000324"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Semantic models ──
    op.create_table(
        "semantic_models",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("db_connection_id", sa.String(64), nullable=False, index=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text, default=""),
        sa.Column("table_names", sa.JSON, default=list),
        sa.Column("primary_table", sa.String(64), nullable=True),
        sa.Column("enabled_for_nl2sql", sa.Boolean, default=True),
        sa.Column("schema_version", sa.String(32), default=""),
        sa.Column("prompt_hint", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime),
        sa.Column("updated_at", sa.DateTime),
    )
    op.create_table(
        "semantic_metrics",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("semantic_model_id", sa.String(32), sa.ForeignKey("semantic_models.id"), nullable=False, index=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("synonyms", sa.JSON, default=list),
        sa.Column("expression", sa.Text, nullable=False),
        sa.Column("source_tables", sa.JSON, default=list),
        sa.Column("default_filters", sa.JSON, default=list),
        sa.Column("allowed_dimensions", sa.JSON, default=list),
        sa.Column("description", sa.Text, default=""),
        sa.Column("status", sa.String(16), default="draft"),
    )
    op.create_table(
        "semantic_dimensions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("semantic_model_id", sa.String(32), sa.ForeignKey("semantic_models.id"), nullable=False, index=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("column_ref", sa.String(256), nullable=False),
        sa.Column("synonyms", sa.JSON, default=list),
        sa.Column("data_type", sa.String(32), default="string"),
        sa.Column("time_granularities", sa.JSON, nullable=True),
        sa.Column("hierarchy", sa.JSON, nullable=True),
        sa.Column("status", sa.String(16), default="draft"),
    )
    op.create_table(
        "semantic_members",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("dimension_id", sa.String(32), sa.ForeignKey("semantic_dimensions.id"), nullable=False, index=True),
        sa.Column("raw_value", sa.String(256), nullable=False),
        sa.Column("display_value", sa.String(256), nullable=False),
        sa.Column("aliases", sa.JSON, default=list),
        sa.Column("frequency", sa.Integer, nullable=True),
        sa.Column("status", sa.String(16), default="draft"),
    )
    op.create_table(
        "semantic_joins",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("semantic_model_id", sa.String(32), sa.ForeignKey("semantic_models.id"), nullable=False, index=True),
        sa.Column("left_table", sa.String(64), nullable=False),
        sa.Column("right_table", sa.String(64), nullable=False),
        sa.Column("condition", sa.Text, nullable=False),
        sa.Column("cardinality", sa.String(16), default="many_to_one"),
        sa.Column("source", sa.String(16), default="manual"),
        sa.Column("confidence", sa.Float, default=0.0),
        sa.Column("status", sa.String(16), default="candidate"),
    )
    # ── NL2SQL cases ──
    op.create_table(
        "nl2sql_cases",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("sql", sa.Text, nullable=False),
        sa.Column("semantic_model_id", sa.String(32), nullable=True, index=True),
        sa.Column("db_connection_id", sa.String(64), nullable=True),
        sa.Column("schema_version", sa.String(32), nullable=True),
        sa.Column("query_ir_json", sa.Text, nullable=True),
        sa.Column("status", sa.String(16), default="pending"),
        sa.Column("quality_score", sa.Float, default=0.0),
        sa.Column("usage_count", sa.Integer, default=0),
        sa.Column("acceptance_rate", sa.Float, default=0.0),
        sa.Column("source", sa.String(16), default="auto"),
        sa.Column("conversation_id", sa.String(64), nullable=True),
        sa.Column("error_category", sa.String(32), nullable=True),
        sa.Column("reviewed_by", sa.String(64), nullable=True),
        sa.Column("reviewed_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime),
    )
    op.create_table(
        "nl2sql_attempts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("conversation_id", sa.String(64), nullable=False, index=True),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("sql", sa.Text, nullable=True),
        sa.Column("status", sa.String(16), default="pending"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("error_category", sa.String(32), nullable=True),
        sa.Column("latency_ms", sa.Float, nullable=True),
        sa.Column("llm_calls", sa.Integer, default=0),
        sa.Column("query_ir_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime),
    )


def downgrade() -> None:
    op.drop_table("nl2sql_attempts")
    op.drop_table("nl2sql_cases")
    op.drop_table("semantic_joins")
    op.drop_table("semantic_members")
    op.drop_table("semantic_dimensions")
    op.drop_table("semantic_metrics")
    op.drop_table("semantic_models")
