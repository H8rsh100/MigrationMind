-- Test fixture: multi-operation migration (mixed risk)
ALTER TABLE users ADD COLUMN last_active TIMESTAMP NOT NULL DEFAULT NOW();
DROP INDEX idx_users_email;
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    action VARCHAR(100) NOT NULL,
    occurred_at TIMESTAMP NOT NULL DEFAULT NOW()
);
