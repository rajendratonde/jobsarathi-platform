#!/bin/sh
# Local development only. Creates the eight service databases, each with
#   <svc>_migration_role  owns the database and its schema (runs Alembic)
#   <svc>_service_role    runtime role: CONNECT to its own database only, DML via grants
# PUBLIC loses CONNECT, so no role can open another service's database.
set -eu

: "${LOCAL_DB_PASSWORD:?LOCAL_DB_PASSWORD must be set (see .env.example)}"

for svc in identity candidate employer job application learning engagement reference; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE ${svc}_migration_role LOGIN PASSWORD '${LOCAL_DB_PASSWORD}';
CREATE ROLE ${svc}_service_role   LOGIN PASSWORD '${LOCAL_DB_PASSWORD}';
CREATE DATABASE ${svc}_db OWNER ${svc}_migration_role;
REVOKE ALL ON DATABASE ${svc}_db FROM PUBLIC;
GRANT CONNECT ON DATABASE ${svc}_db TO ${svc}_migration_role, ${svc}_service_role;
SQL
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "${svc}_db" <<SQL
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;
ALTER SCHEMA public OWNER TO ${svc}_migration_role;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO ${svc}_service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE ${svc}_migration_role IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ${svc}_service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE ${svc}_migration_role IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO ${svc}_service_role;
SQL
done

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname reference_db -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
echo "JobSarathi: 8 service databases and 16 roles created"
