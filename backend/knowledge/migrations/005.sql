-- 2026-11-03: 연결과 암호문은 사용자 소유로 격리하고 작업 문서에 저장하지 않는다.
CREATE TABLE core.mcp_connections (
 id text PRIMARY KEY, owner_id text NOT NULL REFERENCES public.users(id),
 name text NOT NULL, url text NOT NULL, auth_type text NOT NULL,
 api_key_header text, oauth_client_id text, secret_ciphertext text,
 enabled boolean NOT NULL DEFAULT false, status text NOT NULL DEFAULT 'disconnected',
 tools jsonb NOT NULL DEFAULT '[]', version bigint NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX mcp_connections_owner ON core.mcp_connections(owner_id);
ALTER TABLE core.mcp_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.mcp_connections FORCE ROW LEVEL SECURITY;
CREATE POLICY mcp_connection_owner ON core.mcp_connections
 USING (current_setting('app.internal',true)='on' OR owner_id=current_setting('app.actor',true))
 WITH CHECK (current_setting('app.internal',true)='on' OR owner_id=current_setting('app.actor',true));
