-- Review-only migration for a COPY first. Not executed against the Raspberry Pi.
-- Stop entry writers and back up the database before applying exactly once.
-- Existing active Demo rows must be reconciled separately; do not invent link IDs for old orders.
BEGIN IMMEDIATE;
ALTER TABLE ai_advice_track ADD COLUMN order_link_id VARCHAR(36);
ALTER TABLE ai_advice_track ADD COLUMN demo_slot VARCHAR(64);
CREATE UNIQUE INDEX uq_qfs_order_link ON ai_advice_track(order_link_id) WHERE order_link_id IS NOT NULL;
CREATE UNIQUE INDEX uq_qfs_demo_slot ON ai_advice_track(demo_slot) WHERE demo_slot IS NOT NULL;
COMMIT;
