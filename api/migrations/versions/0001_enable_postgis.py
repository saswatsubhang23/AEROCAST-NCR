"""Enable the PostGIS extension.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Requires a role allowed to create extensions (or the extension pre-installed by an administrator).
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")


def downgrade() -> None:
    # Intentionally left in place: other databases objects may depend on it.
    pass
