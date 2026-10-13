"""Bookkeeping for SQLite -> PostGIS syncs (app/db/postgis_sync.py).

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table if not exists env_sync_run (
          run_id      text primary key,
          started_at  timestamptz not null,
          finished_at timestamptz,
          status      text not null check (status in ('running','ok','failed')),
          mode        text,
          stations    integer,
          rows_read   bigint,
          rows_total  bigint,
          note        text
        )
        """
    )


def downgrade() -> None:
    op.execute("drop table if exists env_sync_run")
