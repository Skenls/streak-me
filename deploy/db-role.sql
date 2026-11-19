\getenv app_password APP_DB_PASSWORD
BEGIN;

SELECT 'CREATE ROLE streakme_app' WHERE NOT EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname = 'streakme_app'
) \gexec

ALTER ROLE streakme_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOREPLICATION NOBYPASSRLS PASSWORD :'app_password';

REVOKE CONNECT, TEMPORARY ON DATABASE streakme FROM PUBLIC;
GRANT CONNECT ON DATABASE streakme TO streakme_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM streakme_app;
GRANT USAGE ON SCHEMA public TO streakme_app;

\ir database-schema.sql

GRANT SELECT, INSERT, UPDATE ON TABLE profiles, streaks TO streakme_app;
GRANT DELETE ON TABLE streaks TO streakme_app;
GRANT SELECT, INSERT ON TABLE inline_pairs TO streakme_app;
GRANT SELECT, INSERT, DELETE ON TABLE streak_reminders TO streakme_app;
GRANT SELECT, INSERT, DELETE ON TABLE claimed_invites TO streakme_app;
GRANT USAGE ON SEQUENCE streaks_id_seq TO streakme_app;

COMMIT;
