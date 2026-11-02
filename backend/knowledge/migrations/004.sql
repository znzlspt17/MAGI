-- 실행 화면의 복구 기준과 발행 대기 이벤트를 같은 트랜잭션에 보존한다.
CREATE TABLE core.execution_progress (
 job_id text PRIMARY KEY REFERENCES core.jobs(id) ON DELETE CASCADE,
 revision bigint NOT NULL DEFAULT 0,
 snapshot jsonb NOT NULL
);
CREATE TABLE core.progress_outbox (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 job_id text REFERENCES core.jobs(id) ON DELETE CASCADE,
 owner_id text,
 revision bigint NOT NULL,
 payload jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX progress_outbox_job ON core.progress_outbox(job_id);
ALTER TABLE core.execution_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.execution_progress FORCE ROW LEVEL SECURITY;
CREATE POLICY owner ON core.execution_progress USING (
 current_setting('app.internal',true)='on' OR EXISTS(SELECT 1 FROM core.jobs j WHERE j.id=job_id)
) WITH CHECK (
 current_setting('app.internal',true)='on' OR EXISTS(SELECT 1 FROM core.jobs j WHERE j.id=job_id)
);
ALTER TABLE core.progress_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.progress_outbox FORCE ROW LEVEL SECURITY;
CREATE POLICY owner ON core.progress_outbox USING (
 current_setting('app.internal',true)='on' OR owner_id=current_setting('app.actor',true)
) WITH CHECK (
 current_setting('app.internal',true)='on' OR owner_id=current_setting('app.actor',true)
);
