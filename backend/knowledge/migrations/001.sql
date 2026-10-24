-- MAGI 최초 스키마. 적용한 파일은 변경하지 않고 다음 번호 파일을 추가한다.
SET LOCAL search_path TO public;

CREATE TABLE users (
 id text PRIMARY KEY, subject_hash text UNIQUE NOT NULL,
 role text NOT NULL DEFAULT 'user' CHECK (role IN ('user','admin')),
 suspended boolean NOT NULL DEFAULT false,
 daily_runs integer NOT NULL DEFAULT 3 CHECK (daily_runs >= 0),
 daily_usd numeric(14,8) NOT NULL DEFAULT 2 CHECK (daily_usd >= 0)
);
CREATE TABLE sessions (
 hash text PRIMARY KEY, user_id text NOT NULL REFERENCES users(id),
 csrf text NOT NULL, expires_at double precision NOT NULL, revoked boolean NOT NULL DEFAULT false
);
CREATE INDEX sessions_user ON sessions(user_id);
CREATE TABLE login_states (
 hash text PRIMARY KEY, browser_hash text NOT NULL, nonce text NOT NULL,
 verifier text NOT NULL, expires_at double precision NOT NULL
);
CREATE TABLE service_lease (
 singleton integer PRIMARY KEY CHECK (singleton=1), owner_id text,
 job_id text, phase text NOT NULL DEFAULT 'idle', generation bigint NOT NULL DEFAULT 0,
 deadline double precision, stopping boolean NOT NULL DEFAULT false
);
INSERT INTO service_lease(singleton) VALUES (1);
CREATE TABLE daily_usage (
 day text NOT NULL, user_id text NOT NULL, runs integer NOT NULL DEFAULT 0,
 spent numeric(14,8) NOT NULL DEFAULT 0, reserved numeric(14,8) NOT NULL DEFAULT 0,
 PRIMARY KEY(day,user_id)
);
CREATE TABLE cost_calls (
 id text PRIMARY KEY, day text NOT NULL, user_id text NOT NULL, job_id text NOT NULL,
 model text NOT NULL, reserved numeric(14,8) NOT NULL,
 actual numeric(14,8), state text NOT NULL DEFAULT 'reserved',
 reserved_at timestamptz, called_at timestamptz, settled_at timestamptz,
 input_tokens bigint CHECK (input_tokens >= 0),
 output_tokens bigint CHECK (output_tokens >= 0),
 cached_tokens bigint CHECK (cached_tokens >= 0 AND cached_tokens <= input_tokens),
 settlement_source text CHECK (settlement_source IN ('calculated','manual')),
 cache_write_tokens bigint CHECK (cache_write_tokens >= 0),
 cache_write_30m_tokens bigint CHECK (cache_write_30m_tokens >= 0),
 cache_write_12h_tokens bigint CHECK (cache_write_12h_tokens >= 0),
 cost_policy text
);
CREATE INDEX cost_calls_usage_day ON cost_calls(day,user_id,job_id);
CREATE INDEX cost_calls_called_at ON cost_calls(called_at,user_id,job_id);
CREATE TABLE admissions (
 user_id text NOT NULL, key text NOT NULL, fingerprint text NOT NULL,
 result jsonb NOT NULL, PRIMARY KEY(user_id,key)
);
CREATE TABLE admin_audit (
 id text PRIMARY KEY, actor_id text NOT NULL, action text NOT NULL,
 target_id text, created_at timestamptz NOT NULL DEFAULT now(), details jsonb
);
CREATE TABLE service_settings (
 singleton integer PRIMARY KEY CHECK(singleton=1), daily_usd numeric(14,8) NOT NULL DEFAULT 10 CHECK(daily_usd>=0)
);
INSERT INTO service_settings(singleton) VALUES (1);
CREATE TABLE request_windows (
 identity text PRIMARY KEY, minute bigint NOT NULL, calls integer NOT NULL
);

-- 업무 저장소. 계정·비용·사용권은 public, 실행 checkpoint는 workflow에 저장한다.
CREATE SCHEMA IF NOT EXISTS core;
SET LOCAL search_path TO core, public;
CREATE TABLE projects (id text PRIMARY KEY, name text NOT NULL, owner_id text,
 created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE jobs (id text PRIMARY KEY, project_id text NOT NULL REFERENCES projects(id),
 owner_id text REFERENCES public.users(id), data jsonb NOT NULL);
CREATE TABLE executions (id text PRIMARY KEY, job_id text NOT NULL REFERENCES jobs(id), data jsonb NOT NULL,
 timeline jsonb NOT NULL DEFAULT '{}',
 sequence bigint GENERATED ALWAYS AS IDENTITY);
CREATE TABLE document_bodies (job_id text NOT NULL REFERENCES jobs(id), hash text NOT NULL,
 content text NOT NULL, PRIMARY KEY(job_id,hash));
CREATE TABLE document_versions (id text PRIMARY KEY, job_id text NOT NULL REFERENCES jobs(id),
 name text NOT NULL, content_hash text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 sequence bigint GENERATED ALWAYS AS IDENTITY,
 FOREIGN KEY(job_id,content_hash) REFERENCES document_bodies(job_id,hash));
CREATE INDEX document_latest ON document_versions(job_id,name,sequence DESC);
CREATE TABLE execution_events (id text PRIMARY KEY, job_id text NOT NULL REFERENCES jobs(id),
 execution_id text NOT NULL REFERENCES executions(id), data jsonb NOT NULL,
 sequence bigint GENERATED ALWAYS AS IDENTITY);
CREATE INDEX execution_events_job ON execution_events(job_id,sequence);
CREATE TABLE model_usage (job_id text NOT NULL REFERENCES jobs(id),scope text NOT NULL,data jsonb NOT NULL,
 PRIMARY KEY(job_id,scope));
CREATE TABLE projection_commits (id text PRIMARY KEY,job_id text NOT NULL REFERENCES jobs(id));
CREATE TABLE nodes (id text PRIMARY KEY, content_id text NOT NULL, job_id text NOT NULL REFERENCES jobs(id),
 logical_key text NOT NULL, kind text NOT NULL, body text NOT NULL, attrs jsonb NOT NULL,
 active boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now(),
 sequence bigint GENERATED ALWAYS AS IDENTITY);
CREATE UNIQUE INDEX one_active_node ON nodes(job_id,logical_key) WHERE active;
CREATE INDEX nodes_text ON nodes USING gin(to_tsvector('simple',body));
CREATE TABLE edges (id text PRIMARY KEY, source text NOT NULL REFERENCES nodes(id),
 target text NOT NULL REFERENCES nodes(id), kind text NOT NULL, attrs jsonb NOT NULL DEFAULT '{}',
 UNIQUE(source,target,kind));
CREATE INDEX edges_target ON edges(target);
CREATE TABLE models (id text PRIMARY KEY,dimensions integer NOT NULL,max_length integer NOT NULL,active boolean NOT NULL DEFAULT false);
CREATE UNIQUE INDEX one_active_model ON models(active) WHERE active;
CREATE TABLE embedding_queue (node_id text PRIMARY KEY REFERENCES nodes(id),
 attempts integer NOT NULL DEFAULT 0, status text NOT NULL DEFAULT 'pending');
CREATE TABLE chunks (id text PRIMARY KEY, node_id text NOT NULL REFERENCES nodes(id), ordinal integer NOT NULL,
 rule text NOT NULL, title_path text NOT NULL, body text NOT NULL, input text NOT NULL,
 input_hash text NOT NULL, source_ranges jsonb NOT NULL);
CREATE INDEX chunks_node ON chunks(node_id,ordinal);
CREATE INDEX chunks_text ON chunks USING gin(to_tsvector('simple',input));
CREATE INDEX chunks_input_hash ON chunks(input_hash);
CREATE TABLE chunk_sets (node_id text NOT NULL REFERENCES nodes(id), model_id text NOT NULL REFERENCES models(id),
 completed boolean NOT NULL DEFAULT false, PRIMARY KEY(node_id,model_id));
CREATE TABLE chunk_vectors (chunk_id text NOT NULL REFERENCES chunks(id), model_id text NOT NULL REFERENCES models(id),
 embedding vector NOT NULL, PRIMARY KEY(chunk_id,model_id));
CREATE TABLE project_decisions (id text PRIMARY KEY, project_id text NOT NULL REFERENCES projects(id),
 source_job_id text REFERENCES jobs(id) ON DELETE SET NULL, completed_id text NOT NULL, decision_id text NOT NULL,
 version integer NOT NULL DEFAULT 1, active boolean NOT NULL DEFAULT true, data jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(project_id,completed_id,decision_id));
CREATE TABLE deleted_jobs (id text PRIMARY KEY);
CREATE TABLE deleted_nodes (id text PRIMARY KEY);
CREATE TABLE cleanup_commits (id text PRIMARY KEY, data jsonb NOT NULL DEFAULT '{}');
-- 사용자 소유 자료는 테이블 소유자에게도 같은 격리를 적용한다.
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects FORCE ROW LEVEL SECURITY;
CREATE POLICY owner ON projects USING (current_setting('app.internal',true)='on' OR owner_id=current_setting('app.actor',true))
 WITH CHECK (current_setting('app.internal',true)='on' OR owner_id=current_setting('app.actor',true));
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs FORCE ROW LEVEL SECURITY;
CREATE POLICY owner ON jobs USING (current_setting('app.internal',true)='on' OR owner_id=current_setting('app.actor',true))
 WITH CHECK (current_setting('app.internal',true)='on' OR owner_id=current_setting('app.actor',true));
DO $$ DECLARE t text; condition text; BEGIN
 FOREACH t IN ARRAY ARRAY['executions','document_bodies','document_versions','execution_events','model_usage','nodes','projection_commits'] LOOP
  EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
  condition := 'current_setting(''app.internal'',true)=''on'' OR EXISTS(SELECT 1 FROM core.jobs j WHERE j.id=job_id)';
  EXECUTE format('CREATE POLICY owner ON %I USING (%s) WITH CHECK (%s)',t,condition,condition);
 END LOOP;
 FOREACH t IN ARRAY ARRAY['chunks','chunk_sets','embedding_queue','edges','chunk_vectors','project_decisions'] LOOP
  condition := CASE WHEN t='edges' THEN 'EXISTS(SELECT 1 FROM core.nodes n WHERE n.id=source) AND EXISTS(SELECT 1 FROM core.nodes n WHERE n.id=target)'
   WHEN t='chunk_vectors' THEN 'EXISTS(SELECT 1 FROM core.chunks c WHERE c.id=chunk_id)'
   WHEN t='project_decisions' THEN 'EXISTS(SELECT 1 FROM core.projects p WHERE p.id=project_id) AND (source_job_id IS NULL OR EXISTS(SELECT 1 FROM core.jobs j WHERE j.id=source_job_id AND j.project_id=project_decisions.project_id))'
   ELSE 'EXISTS(SELECT 1 FROM core.nodes n WHERE n.id=node_id)' END;
  condition := 'current_setting(''app.internal'',true)=''on'' OR ('||condition||')';
  EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY owner ON %I USING (%s) WITH CHECK (%s)',t,condition,condition);
 END LOOP;
END $$;

CREATE SCHEMA workflow;
CREATE TABLE workflow.workflow_task_results (
 thread_id text NOT NULL, task_id text NOT NULL, status text NOT NULL, payload text NOT NULL,
 PRIMARY KEY(thread_id,task_id)
);
