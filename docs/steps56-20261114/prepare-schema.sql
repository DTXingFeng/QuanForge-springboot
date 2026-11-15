-- Candidate migration. Apply ONCE only after verifying an offline copy and active ownership.
-- Never use this script to relabel old trades or manufacture order identities.
BEGIN IMMEDIATE;
ALTER TABLE ai_advice_track ADD COLUMN order_link_id VARCHAR(36);
ALTER TABLE ai_advice_track ADD COLUMN demo_slot VARCHAR(64);
CREATE UNIQUE INDEX uq_qfs_order_link ON ai_advice_track(order_link_id) WHERE order_link_id IS NOT NULL;
CREATE UNIQUE INDEX uq_qfs_demo_slot ON ai_advice_track(demo_slot) WHERE demo_slot IS NOT NULL;
CREATE TABLE IF NOT EXISTS execution_event(
    event_id VARCHAR(64) PRIMARY KEY, track_id BIGINT NOT NULL,
    kind VARCHAR(32) NOT NULL, observed_at BIGINT NOT NULL, payload TEXT NOT NULL
);
COMMIT;
