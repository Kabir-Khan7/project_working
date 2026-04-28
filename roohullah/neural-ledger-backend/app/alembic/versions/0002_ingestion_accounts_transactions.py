"""Ingestion: accounts, transactions, ingestion_jobs

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── accounts ──────────────────────────────────────────────────────────────
    op.create_table(
        "accounts",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "org_id",
            UUID(as_uuid=False),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("parent_code", sa.String(20), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("org_id", "code", name="uq_account_org_code"),
    )
    op.create_index("ix_accounts_id", "accounts", ["id"])
    op.create_index("ix_accounts_org_id", "accounts", ["org_id"])

    # ── ingestion_jobs ────────────────────────────────────────────────────────
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "org_id",
            UUID(as_uuid=False),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "uploaded_by",
            UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("rows_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("org_id", "file_sha256", name="uq_ingestion_org_hash"),
    )
    op.create_index("ix_ingestion_jobs_id", "ingestion_jobs", ["id"])
    op.create_index("ix_ingestion_jobs_org_id", "ingestion_jobs", ["org_id"])
    op.create_index("ix_ingestion_jobs_file_sha256", "ingestion_jobs", ["file_sha256"])

    # ── transactions ──────────────────────────────────────────────────────────
    op.create_table(
        "transactions",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "org_id",
            UUID(as_uuid=False),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ingestion_job_id",
            UUID(as_uuid=False),
            sa.ForeignKey("ingestion_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_row_hash", sa.String(64), nullable=False),
        sa.Column("txn_date", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("party_name", sa.String(255), nullable=True),
        sa.Column("reference", sa.String(100), nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False, server_default="PKR"),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column(
            "account_id",
            UUID(as_uuid=False),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("category_hint", sa.String(100), nullable=True),
        sa.Column("category_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_transactions_id", "transactions", ["id"])
    op.create_index("ix_transactions_org_id", "transactions", ["org_id"])
    op.create_index("ix_transactions_source_row_hash", "transactions", ["source_row_hash"])
    op.create_index("ix_transactions_account_id", "transactions", ["account_id"])
    op.create_index("ix_transactions_ingestion_job_id", "transactions", ["ingestion_job_id"])
    op.create_index("ix_tx_org_date", "transactions", ["org_id", "txn_date"])
    op.create_index("ix_tx_org_account", "transactions", ["org_id", "account_id"])


def downgrade() -> None:
    op.drop_table("transactions")
    op.drop_table("ingestion_jobs")
    op.drop_table("accounts")
