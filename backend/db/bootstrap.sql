-- Scrollwalk local database bootstrap. Run as a superuser through scripts/db-bootstrap.ps1,
-- which supplies the passwords as psql variables. Safe to re-run.
--
-- Roles (docs/SCOPE.md section 9.1):
--   app_owner   owns the schema, runs migrations only
--   app_rw      the API; not the table owner, cannot bypass row-level security
--   app_public  read-only public pages; table grants come from migrations
--   app_hq      Super-Admin; table grants come from migrations

\set ON_ERROR_STOP on

SELECT format('CREATE ROLE %I LOGIN', r) FROM unnest(ARRAY['app_owner','app_rw','app_public','app_hq']) AS r
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) \gexec

ALTER ROLE app_owner  LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'owner_pw';
ALTER ROLE app_rw     LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'rw_pw';
ALTER ROLE app_public LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'public_pw';
ALTER ROLE app_hq     LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'hq_pw';

ALTER ROLE app_public SET default_transaction_read_only = on;
ALTER ROLE app_rw     SET statement_timeout = '15s';
ALTER ROLE app_public SET statement_timeout = '5s';

SELECT format('CREATE DATABASE %I OWNER app_owner ENCODING ''UTF8'' TEMPLATE template0', d)
FROM unnest(ARRAY['scrollwalk_dev','scrollwalk_test']) AS d
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = d) \gexec

\connect scrollwalk_dev
\ir bootstrap_db.sql

\connect scrollwalk_test
\ir bootstrap_db.sql
