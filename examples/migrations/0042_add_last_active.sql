-- Migration 0042: Add last_active column and drop old index
-- This is the risky example from the MigrationMind demo

-- Operation 1: Add NOT NULL column with DEFAULT (risky on PG < 11)
ALTER TABLE users ADD COLUMN last_active TIMESTAMP NOT NULL DEFAULT NOW();

-- Operation 2: Drop an index that queries depend on
DROP INDEX idx_users_email;

-- Operation 3: Create new audit log table (safe)
CREATE TABLE audit_log (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id),
    action      VARCHAR(100) NOT NULL,
    occurred_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ip_address  INET,
    metadata    JSONB
);
