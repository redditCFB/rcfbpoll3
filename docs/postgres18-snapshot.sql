-- Run before Django migrations on both the source and restored databases.
-- A differing migration set or row count must be investigated before cutover.
COPY (
    SELECT 'migration' AS kind, app || '.' || name AS item, 1::bigint AS value
    FROM django_migrations
    UNION ALL SELECT 'rows', 'auth_user', count(*) FROM auth_user
    UNION ALL SELECT 'rows', 'django_session', count(*) FROM django_session
    UNION ALL SELECT 'rows', 'poll_user', count(*) FROM poll_user
    UNION ALL SELECT 'rows', 'poll_poll', count(*) FROM poll_poll
    UNION ALL SELECT 'rows', 'poll_ballot', count(*) FROM poll_ballot
    UNION ALL SELECT 'rows', 'poll_ballotentry', count(*) FROM poll_ballotentry
    UNION ALL SELECT 'rows', 'poll_redditaccount', count(*) FROM poll_redditaccount
    UNION ALL SELECT 'rows', 'socialaccount_socialaccount', count(*) FROM socialaccount_socialaccount
    ORDER BY kind, item
) TO STDOUT WITH CSV HEADER;
