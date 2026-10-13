-- One-time local setup: app role + database + PostGIS. Idempotent.
-- Run as the postgres superuser, passing the NEW app password on the command line (never stored in this file):
--
--   psql -h localhost -U postgres -d postgres -v app_pw=YOUR_CHOSEN_PASSWORD -f scripts/setup_local_postgres.sql
--
-- Then set in api/.env:
--   DATABASE_URL=postgresql+psycopg://aerocast:YOUR_CHOSEN_PASSWORD@localhost:5432/aerocast

SELECT format('CREATE ROLE aerocast LOGIN PASSWORD %L', :'app_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aerocast') \gexec

SELECT format('ALTER ROLE aerocast PASSWORD %L', :'app_pw') \gexec

SELECT 'CREATE DATABASE aerocast OWNER aerocast'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'aerocast') \gexec

\connect aerocast
-- PostGIS is not a "trusted" extension, so a superuser must create it (Alembic 0001 is then a no-op).
CREATE EXTENSION IF NOT EXISTS postgis;
SELECT postgis_full_version();
