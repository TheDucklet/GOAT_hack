"""Demo actions and bounded product telemetry, independent of global visibility."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "demo_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("company_id", sa.String(100), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("insight_id", sa.String(36), sa.ForeignKey("insights.id")),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "company_id", "idempotency_key"),
    )
    op.create_table(
        "product_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("company_id", sa.String(100), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("insight_id", sa.String(36), sa.ForeignKey("insights.id")),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("session_hash", sa.String(64), nullable=False),
        sa.Column("version", sa.String(100), nullable=False),
        sa.Column("versions", sa.JSON(), nullable=False),
        sa.Column("dedup_key", sa.String(64), nullable=False, unique=True),
        sa.Column("excluded_reason", sa.String(16)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_product_events_created_at", "product_events", ["created_at"])


def downgrade():
    op.drop_table("product_events")
    op.drop_table("demo_actions")
