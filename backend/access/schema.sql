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
 actual numeric(14,8), state text NOT NULL DEFAULT 'reserved'
);
CREATE TABLE admissions (
 user_id text NOT NULL, key text NOT NULL, fingerprint text NOT NULL,
 result jsonb NOT NULL, PRIMARY KEY(user_id,key)
);
CREATE TABLE admin_audit (
 id text PRIMARY KEY, actor_id text NOT NULL, action text NOT NULL,
 target_id text, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE service_settings (
 singleton integer PRIMARY KEY CHECK(singleton=1), daily_usd numeric(14,8) NOT NULL DEFAULT 10 CHECK(daily_usd>=0)
);
INSERT INTO service_settings(singleton) VALUES (1);
CREATE TABLE request_windows (
 identity text PRIMARY KEY, minute bigint NOT NULL, calls integer NOT NULL
);

-- 이전 기록에는 없는 시각과 사용량을 채우지 않는다.
ALTER TABLE cost_calls
 ADD COLUMN reserved_at timestamptz,
 ADD COLUMN called_at timestamptz,
 ADD COLUMN settled_at timestamptz,
 ADD COLUMN input_tokens bigint CHECK (input_tokens >= 0),
 ADD COLUMN output_tokens bigint CHECK (output_tokens >= 0),
 ADD COLUMN cached_tokens bigint CHECK (cached_tokens >= 0 AND cached_tokens <= input_tokens),
 ADD COLUMN settlement_source text CHECK (settlement_source IN ('calculated','manual'));
CREATE INDEX cost_calls_usage_day ON cost_calls(day,user_id,job_id);
CREATE INDEX cost_calls_called_at ON cost_calls(called_at,user_id,job_id);

-- 기존 기록의 누락 사용량과 계산 근거를 추정해서 채우지 않는다.
ALTER TABLE cost_calls
 ADD COLUMN cache_write_tokens bigint CHECK (cache_write_tokens >= 0),
 ADD COLUMN cache_write_30m_tokens bigint CHECK (cache_write_30m_tokens >= 0),
 ADD COLUMN cache_write_12h_tokens bigint CHECK (cache_write_12h_tokens >= 0),
 ADD COLUMN cost_policy text;
ALTER TABLE admin_audit ADD COLUMN details jsonb;
