#!/bin/sh
# Separate schema ownership (migrations) from the runtime role. The runtime
# role is not a superuser and cannot bypass row-level security.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<SQL
CREATE ROLE assureops_owner LOGIN PASSWORD '${ASSUREOPS_OWNER_PASSWORD}';
CREATE ROLE assureops_app LOGIN PASSWORD '${ASSUREOPS_APP_PASSWORD}' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE DATABASE assureops OWNER assureops_owner;
\c assureops
GRANT USAGE ON SCHEMA public TO assureops_app;
ALTER DEFAULT PRIVILEGES FOR ROLE assureops_owner IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO assureops_app;
ALTER DEFAULT PRIVILEGES FOR ROLE assureops_owner IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO assureops_app;
SQL
