"""Store the per-series coverage summary on each sync run so status reads need not aggregate millions of rows.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table env_sync_run add column if not exists summary jsonb")


def downgrade() -> None:
    op.execute("alter table env_sync_run drop column if exists summary")
