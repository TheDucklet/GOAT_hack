"""Persist receipt time separately from queue and execution time."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("received_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE jobs SET received_at = created_at")
    constraints = [sa.CheckConstraint("status IN ('queued','running','done','failed')")]
    with op.batch_alter_table("jobs", table_args=constraints) as batch:
        batch.alter_column("received_at", existing_type=sa.DateTime(timezone=True), nullable=False)


def downgrade():
    constraints = [sa.CheckConstraint("status IN ('queued','running','done','failed')")]
    with op.batch_alter_table("jobs", table_args=constraints) as batch:
        batch.drop_column("received_at")
