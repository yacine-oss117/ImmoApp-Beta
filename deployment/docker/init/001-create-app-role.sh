#!/usr/bin/env bash
set -e

app_user="${IMMOAPP_APP_DB_USER:-}"
app_password="${IMMOAPP_APP_DB_PASSWORD:-}"
db_name="${POSTGRES_DB:-}"

if [[ -z "$app_user" || -z "$app_password" || -z "$db_name" ]]; then
  echo "Missing IMMOAPP_APP_DB_USER/IMMOAPP_APP_DB_PASSWORD/POSTGRES_DB for app role init." >&2
  exit 1
fi

psql -v ON_ERROR_STOP=1 \
  -v app_user="$app_user" \
  -v app_password="$app_password" \
  --username "${POSTGRES_USER}" \
  --dbname "${db_name}" <<'SQL'
SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS',
  :'app_user',
  :'app_password'
) AS create_role
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user');
\gexec

SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'app_user') AS grant_connect;
\gexec

SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'app_user') AS grant_usage_schema;
\gexec

SELECT format(
  'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO %I',
  :'app_user'
) AS grant_tables;
\gexec

SELECT format(
  'GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO %I',
  :'app_user'
) AS grant_sequences;
\gexec

SELECT format(
  'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
  :'app_user'
) AS alter_default_tables;
\gexec

SELECT format(
  'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO %I',
  :'app_user'
) AS alter_default_sequences;
\gexec
SQL
