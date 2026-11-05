#!/bin/sh
# docker-compose Postgres bootstrap (Part 13): the tenant-data DB, the control-plane DB, and
# the NON-superuser runtime role the app queries as (RLS is bypassed for superusers, so the
# app must never connect as one). Passwords come from the compose environment, never here.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<SQL
CREATE ROLE hrms_app LOGIN PASSWORD '${HRMS_APP_DB_PASSWORD}' NOSUPERUSER NOBYPASSRLS;
CREATE DATABASE hrms OWNER "$POSTGRES_USER";
CREATE DATABASE hrms_control_plane OWNER "$POSTGRES_USER";
GRANT CONNECT ON DATABASE hrms TO hrms_app;
GRANT CONNECT ON DATABASE hrms_control_plane TO hrms_app;
SQL
for db in hrms hrms_control_plane; do
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<SQL
GRANT USAGE ON SCHEMA public TO hrms_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO hrms_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO hrms_app;
SQL
done
