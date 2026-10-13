"""Normalised environmental data schema (sources, stations, cells, typed records, exposure layers).

Revision ID: 0002
Revises: 0001

Requires PostGIS (0001). The DDL lives in app/envdata/ddl.py so the migration, the docs and the tests share one definition.
"""

from alembic import op

from app.envdata.ddl import POSTGIS_DDL, SOURCES_SEED

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGIS_DDL)
    op.execute(SOURCES_SEED)


def downgrade() -> None:
    for t in ("sensitive_site", "exposure_cell", "env_record", "env_cell", "env_station", "env_source"):
        op.execute(f"drop table if exists {t} cascade")
