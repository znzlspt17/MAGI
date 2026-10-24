CREATE TABLE IF NOT EXISTS magi_projects (
 id text PRIMARY KEY, name text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS magi_jobs (
 id text PRIMARY KEY, project_id text NOT NULL REFERENCES magi_projects(id), data jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS magi_executions (
 id text PRIMARY KEY, job_id text NOT NULL REFERENCES magi_jobs(id), data jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS magi_snapshots (
 id text PRIMARY KEY, job_id text NOT NULL REFERENCES magi_jobs(id), execution_id text NOT NULL,
 stage text NOT NULL, state jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS magi_artifacts (
 id text PRIMARY KEY, job_id text NOT NULL REFERENCES magi_jobs(id), snapshot_id text NOT NULL REFERENCES magi_snapshots(id),
 path text NOT NULL, content text NOT NULL, content_hash text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(snapshot_id, path)
);
CREATE INDEX IF NOT EXISTS magi_artifact_job_path ON magi_artifacts(job_id, path, created_at DESC);
CREATE TABLE IF NOT EXISTS magi_nodes (
 id text PRIMARY KEY, job_id text NOT NULL REFERENCES magi_jobs(id), logical_key text NOT NULL,
 kind text NOT NULL, body text NOT NULL, attrs jsonb NOT NULL,
 active boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS magi_nodes_job_key ON magi_nodes(job_id, logical_key);
CREATE INDEX IF NOT EXISTS magi_nodes_text ON magi_nodes USING gin(to_tsvector('simple', body));
CREATE TABLE IF NOT EXISTS magi_edges (
 id text PRIMARY KEY, source text NOT NULL REFERENCES magi_nodes(id), target text NOT NULL REFERENCES magi_nodes(id),
 kind text NOT NULL, attrs jsonb NOT NULL DEFAULT '{}', UNIQUE(source, target, kind)
);
CREATE INDEX IF NOT EXISTS magi_edges_target ON magi_edges(target);
CREATE TABLE IF NOT EXISTS magi_models (
 id text PRIMARY KEY, dimensions integer NOT NULL, max_length integer NOT NULL, active boolean NOT NULL DEFAULT false
);
CREATE UNIQUE INDEX IF NOT EXISTS magi_one_active_model ON magi_models(active) WHERE active;
CREATE TABLE IF NOT EXISTS magi_embedding_queue (
 node_id text PRIMARY KEY REFERENCES magi_nodes(id), attempts integer NOT NULL DEFAULT 0,
 status text NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS magi_embeddings (
 node_id text NOT NULL REFERENCES magi_nodes(id), model_id text NOT NULL REFERENCES magi_models(id),
 content_hash text NOT NULL, embedding vector NOT NULL, PRIMARY KEY(node_id, model_id)
);
