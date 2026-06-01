-- Migration 0043: Drop legacy columns
-- HIGH RISK — drops columns still referenced by application code

ALTER TABLE users DROP COLUMN legacy_token;
ALTER TABLE users DROP COLUMN old_avatar_url;

-- Also rename a column (COMPLEX rollback)
ALTER TABLE users RENAME COLUMN username TO display_name;
