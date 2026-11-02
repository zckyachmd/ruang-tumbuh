-- Historical reservations have no observed outcome; never infer success from them.
ALTER TABLE ai_reservations ADD COLUMN outcome text NOT NULL DEFAULT 'unknown'
    CHECK (outcome IN ('unknown','reserved','succeeded','provider_error','internal_error'));
ALTER TABLE ai_reservations ALTER COLUMN outcome SET DEFAULT 'reserved';
ALTER TABLE ai_reservations ADD COLUMN latency_ms bigint CHECK (latency_ms >= 0);
ALTER TABLE ai_reservations ADD COLUMN finished_at timestamptz;
