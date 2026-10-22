"""Private versioned feed snapshots and version-scoped dismissals.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "feed_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("company_id", sa.String(100), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("input_key", sa.String(64), nullable=False, unique=True),
        sa.Column("versions", sa.JSON(), nullable=False),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id")),
        sa.Column("error", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ready_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('queued','running','ready','partial','failed','deferred','stale')"),
    )
    op.create_index("ix_feed_snapshots_owner", "feed_snapshots", ["user_id", "company_id", "created_at"])
    op.create_table(
        "feed_dismissals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("company_id", sa.String(100), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("version", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "company_id", "event_id", "version"),
    )


def downgrade():
    op.drop_table("feed_dismissals")
    op.drop_table("feed_snapshots")
