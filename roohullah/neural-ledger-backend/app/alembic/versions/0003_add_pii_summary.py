"""Add pii_summary column to ingestion_jobs (M13 Privacy Firewall)

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-28

Why:
  M13 — Privacy Firewall scans every uploaded file for PII (CNIC, phone,
  email, IBAN, addresses). The aggregate *summary* of what was detected
  is stored here. Raw PII values are NEVER stored — only metadata like
  "3 rows had phone numbers in the description column".
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # JSONB is PostgreSQL's binary JSON type — faster to query than plain JSON.
    # nullable=True so existing rows aren't broken.
    op.add_column(
        "ingestion_jobs",
        sa.Column("pii_summary", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ingestion_jobs", "pii_summary")
