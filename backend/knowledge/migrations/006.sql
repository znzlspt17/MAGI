-- 2026-11-03: 인증 중 상태와 갱신 예약을 작업 checkpoint와 분리한다.
CREATE TABLE core.mcp_oauth_states (
 state_hash text PRIMARY KEY, owner_id text NOT NULL REFERENCES public.users(id),
 connection_id text NOT NULL REFERENCES core.mcp_connections(id) ON DELETE CASCADE,
 session_hash text NOT NULL, expires_at double precision NOT NULL,
 payload_ciphertext text NOT NULL
);
CREATE INDEX mcp_oauth_states_owner ON core.mcp_oauth_states(owner_id, connection_id);
CREATE TABLE core.mcp_oauth_refreshes (
 connection_id text PRIMARY KEY REFERENCES core.mcp_connections(id) ON DELETE CASCADE,
 owner_id text NOT NULL REFERENCES public.users(id), started_at double precision NOT NULL
);
ALTER TABLE core.mcp_oauth_states ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.mcp_oauth_states FORCE ROW LEVEL SECURITY;
CREATE POLICY mcp_oauth_state_owner ON core.mcp_oauth_states
 USING (current_setting('app.internal',true)='on' OR owner_id=current_setting('app.actor',true))
 WITH CHECK (current_setting('app.internal',true)='on' OR owner_id=current_setting('app.actor',true));
ALTER TABLE core.mcp_oauth_refreshes ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.mcp_oauth_refreshes FORCE ROW LEVEL SECURITY;
CREATE POLICY mcp_oauth_refresh_owner ON core.mcp_oauth_refreshes
 USING (current_setting('app.internal',true)='on' OR owner_id=current_setting('app.actor',true))
 WITH CHECK (current_setting('app.internal',true)='on' OR owner_id=current_setting('app.actor',true));
