"""Versioned client semantics, raw provenance and payment classification.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "companies",
        sa.Column("data_semantics_version", sa.String(64), nullable=False, server_default="legacy-company-1"),
    )
    op.add_column(
        "companies", sa.Column("identity_quality", sa.String(16), nullable=False, server_default="legacy")
    )
    op.add_column("companies", sa.Column("client_type", sa.String(32), nullable=True))
    op.create_index("ix_companies_client_type", "companies", ["client_type"])
    op.add_column("person_links", sa.Column("provenance", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("payments", sa.Column("raw", sa.JSON(), nullable=False, server_default="{}"))
    # Old payments remain explicitly unclassified until a source-preserving reimport.
    op.add_column(
        "payments", sa.Column("classification", sa.String(16), nullable=False, server_default="legacy")
    )
    op.create_index("ix_payments_classification", "payments", ["classification"])
    op.create_table(
        "client_raw_rows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.String(64), sa.ForeignKey("import_batches.id"), nullable=False),
        sa.Column("file", sa.String(64), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("entity_id", sa.String(100), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(100), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=False),
        sa.UniqueConstraint("batch_id", "file", "row_number"),
    )
    op.create_index("ix_client_raw_rows_batch_id", "client_raw_rows", ["batch_id"])
    op.create_index("ix_client_raw_rows_entity_id", "client_raw_rows", ["entity_id"])


def downgrade():
    op.drop_table("client_raw_rows")
    op.drop_index("ix_payments_classification", "payments")
    op.drop_column("payments", "classification")
    op.drop_column("payments", "raw")
    op.drop_column("person_links", "provenance")
    op.drop_index("ix_companies_client_type", "companies")
    for name in ["client_type", "identity_quality", "data_semantics_version"]:
        op.drop_column("companies", name)
