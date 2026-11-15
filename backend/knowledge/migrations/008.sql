-- 2026-11-13: 원본 보존과 색인 접수를 함께 기록해 재시작 후에도 처리한다.
ALTER TABLE core.embedding_queue ADD COLUMN next_attempt double precision NOT NULL DEFAULT 0;
CREATE TABLE core.projection_queue (
 id text PRIMARY KEY,
 sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
 job_id text NOT NULL REFERENCES core.jobs(id) ON DELETE CASCADE,
 execution_id text NOT NULL,
 stage text NOT NULL,
 state jsonb NOT NULL,
 artifacts jsonb NOT NULL,
 status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','running','failed','completed')),
 attempts integer NOT NULL DEFAULT 0,
 lease_token text,
 lease_until double precision,
 next_attempt double precision NOT NULL DEFAULT 0
);
CREATE INDEX projection_queue_job_sequence ON core.projection_queue(job_id,sequence);
CREATE INDEX projection_queue_pending ON core.projection_queue(status,next_attempt,sequence);
ALTER TABLE core.projection_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.projection_queue FORCE ROW LEVEL SECURITY;
CREATE POLICY projection_queue_owner ON core.projection_queue USING (
 current_setting('app.internal',true)='on' OR EXISTS (
  SELECT 1 FROM core.jobs j WHERE j.id=job_id AND public.magi_can_access_owner(j.owner_id)
 )
) WITH CHECK (
 current_setting('app.internal',true)='on' OR EXISTS (
  SELECT 1 FROM core.jobs j WHERE j.id=job_id AND public.magi_can_access_owner(j.owner_id)
 )
);
