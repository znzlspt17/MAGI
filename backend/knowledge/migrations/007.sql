-- 2026-11-13: 기존 소유자를 옮기지 않고 익명 작업을 계정에 연결한다.
ALTER TABLE public.users ALTER COLUMN subject_hash DROP NOT NULL;
ALTER TABLE public.users ADD COLUMN account_id text REFERENCES public.users(id);
UPDATE public.users SET account_id=id;
CREATE INDEX users_account ON public.users(account_id);
ALTER TABLE public.login_states ADD COLUMN session_hash text;

-- app.owners는 검증된 서버 세션에서만 전달하며 브라우저 입력을 신뢰하지 않는다.
CREATE FUNCTION public.magi_can_access_owner(owner text) RETURNS boolean
LANGUAGE sql STABLE AS $$
 SELECT current_setting('app.internal',true)='on'
    OR owner=current_setting('app.actor',true)
    OR COALESCE(NULLIF(current_setting('app.owners',true),''),'[]')::jsonb ? owner
$$;

DROP POLICY owner ON core.projects;
CREATE POLICY owner ON core.projects USING (public.magi_can_access_owner(owner_id))
 WITH CHECK (public.magi_can_access_owner(owner_id));
DROP POLICY owner ON core.jobs;
CREATE POLICY owner ON core.jobs USING (public.magi_can_access_owner(owner_id))
 WITH CHECK (public.magi_can_access_owner(owner_id));
DROP POLICY owner ON core.progress_outbox;
CREATE POLICY owner ON core.progress_outbox USING (public.magi_can_access_owner(owner_id))
 WITH CHECK (public.magi_can_access_owner(owner_id));
DROP POLICY mcp_connection_owner ON core.mcp_connections;
CREATE POLICY mcp_connection_owner ON core.mcp_connections USING (public.magi_can_access_owner(owner_id))
 WITH CHECK (public.magi_can_access_owner(owner_id));
DROP POLICY mcp_oauth_state_owner ON core.mcp_oauth_states;
CREATE POLICY mcp_oauth_state_owner ON core.mcp_oauth_states USING (public.magi_can_access_owner(owner_id))
 WITH CHECK (public.magi_can_access_owner(owner_id));
DROP POLICY mcp_oauth_refresh_owner ON core.mcp_oauth_refreshes;
CREATE POLICY mcp_oauth_refresh_owner ON core.mcp_oauth_refreshes USING (public.magi_can_access_owner(owner_id))
 WITH CHECK (public.magi_can_access_owner(owner_id));
