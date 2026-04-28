"""Initial: users, organisations, org_members tables

Revision ID: 0001
Revises:
Create Date: 2026-04-27
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── users ─────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ── organisations ─────────────────────────────────────────────────────────
    op.create_table(
        "organisations",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("industry", sa.String(100), nullable=True),
        sa.Column("country", sa.String(10), nullable=False, server_default="PK"),
        sa.Column("currency", sa.String(10), nullable=False, server_default="PKR"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("plan", sa.String(50), nullable=False, server_default="free"),
        sa.Column("plan_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_organisations_id", "organisations", ["id"])
    op.create_index("ix_organisations_slug", "organisations", ["slug"], unique=True)

    # ── org_members ───────────────────────────────────────────────────────────
    op.create_table(
        "org_members",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "org_id",
            UUID(as_uuid=False),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(50), nullable=False, server_default="member"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("org_id", "user_id", name="uq_org_user"),
    )
    op.create_index("ix_org_members_id", "org_members", ["id"])
    op.create_index("ix_org_members_org_id", "org_members", ["org_id"])
    op.create_index("ix_org_members_user_id", "org_members", ["user_id"])


def downgrade() -> None:
    op.drop_table("org_members")
    op.drop_table("organisations")
    op.drop_table("users")
