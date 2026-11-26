#!/usr/bin/env bash
# Runs once, on first start of the compose Postgres container (empty
# volume), via /docker-entrypoint-initdb.d. Creates the read-only role the
# API connects as. POSTGRES_USER stays the owner used for seeding data.
set -euo pipefail

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v ro_user="${APP_DB_READONLY_USER:-ai_bi_readonly}" \
  -v ro_password="${APP_DB_READONLY_PASSWORD:-readonly_pwd}" \
  -v db_name="$POSTGRES_DB" \
  -v owner_role="$POSTGRES_USER" \
  -f /docker-entrypoint-initdb.d/readonly_role.sql.in
