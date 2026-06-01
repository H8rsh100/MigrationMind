-- Test fixture: risky NOT NULL without DEFAULT
ALTER TABLE orders ADD COLUMN confirmed_at TIMESTAMP NOT NULL;
