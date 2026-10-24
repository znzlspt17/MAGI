CREATE TABLE magi_users (
 id text PRIMARY KEY, subject_hash text UNIQUE NOT NULL,
 role text NOT NULL DEFAULT 'user' CHECK (role IN ('user','admin')),
 suspended boolean NOT NULL DEFAULT false,
 daily_runs integer NOT NULL DEFAULT 3 CHECK (daily_runs >= 0),
 daily_usd numeric(14,8) NOT NULL DEFAULT 2 CHECK (daily_usd >= 0)
);
CREATE TABLE magi_sessions (
 hash text PRIMARY KEY, user_id text NOT NULL REFERENCES magi_users(id),
 csrf text NOT NULL, expires_at double precision NOT NULL, revoked boolean NOT NULL DEFAULT false
);
CREATE INDEX magi_sessions_user ON magi_sessions(user_id);
CREATE TABLE magi_login_states (
 hash text PRIMARY KEY, browser_hash text NOT NULL, nonce text NOT NULL,
 verifier text NOT NULL, expires_at double precision NOT NULL
);
ALTER TABLE magi_jobs ADD COLUMN owner_id text REFERENCES magi_users(id);
CREATE INDEX magi_jobs_owner ON magi_jobs(owner_id);
CREATE TABLE magi_service_lease (
 singleton integer PRIMARY KEY CHECK (singleton=1), owner_id text,
 job_id text, phase text NOT NULL DEFAULT 'idle', generation bigint NOT NULL DEFAULT 0,
 deadline double precision, stopping boolean NOT NULL DEFAULT false
);
INSERT INTO magi_service_lease(singleton) VALUES (1);
CREATE TABLE magi_daily_usage (
 day text NOT NULL, user_id text NOT NULL, runs integer NOT NULL DEFAULT 0,
 spent numeric(14,8) NOT NULL DEFAULT 0, reserved numeric(14,8) NOT NULL DEFAULT 0,
 PRIMARY KEY(day,user_id)
);
CREATE TABLE magi_cost_calls (
 id text PRIMARY KEY, day text NOT NULL, user_id text NOT NULL, job_id text NOT NULL,
 model text NOT NULL, reserved numeric(14,8) NOT NULL,
 actual numeric(14,8), state text NOT NULL DEFAULT 'reserved'
);
CREATE TABLE magi_admissions (
 user_id text NOT NULL, key text NOT NULL, fingerprint text NOT NULL,
 result jsonb NOT NULL, PRIMARY KEY(user_id,key)
);
CREATE TABLE magi_admin_audit (
 id text PRIMARY KEY, actor_id text NOT NULL, action text NOT NULL,
 target_id text, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE magi_service_settings (
 singleton integer PRIMARY KEY CHECK(singleton=1), daily_usd numeric(14,8) NOT NULL DEFAULT 10 CHECK(daily_usd>=0)
);
INSERT INTO magi_service_settings(singleton) VALUES (1);
