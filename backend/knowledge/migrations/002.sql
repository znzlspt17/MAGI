ALTER TABLE magi_snapshots ADD COLUMN sequence bigint GENERATED ALWAYS AS IDENTITY;
CREATE INDEX magi_snapshot_order ON magi_snapshots(job_id, sequence DESC);
ALTER TABLE magi_executions ADD COLUMN sequence bigint GENERATED ALWAYS AS IDENTITY;
ALTER TABLE magi_nodes ADD COLUMN content_id text;
ALTER TABLE magi_nodes ADD COLUMN sequence bigint GENERATED ALWAYS AS IDENTITY;
UPDATE magi_nodes SET content_id=id;
ALTER TABLE magi_nodes ALTER COLUMN content_id SET NOT NULL;
CREATE UNIQUE INDEX magi_one_active_node ON magi_nodes(job_id, logical_key) WHERE active;
