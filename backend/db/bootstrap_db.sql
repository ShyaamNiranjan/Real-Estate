-- Per-database setup, included by bootstrap.sql after \connect.

SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database()) \gexec
SELECT format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO app_rw, app_hq', current_database()) \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO app_public', current_database()) \gexec

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

ALTER SCHEMA public OWNER TO app_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO app_rw, app_public, app_hq;

-- app_rw gets data access on every table app_owner creates; migrations revoke where needed
-- (e.g. UPDATE/DELETE on audit_log). app_public and app_hq are granted table by table.
ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rw;
ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO app_rw;
