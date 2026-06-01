-- Test fixture: blocking CREATE INDEX (no CONCURRENTLY)
CREATE INDEX idx_orders_status ON orders (status);
