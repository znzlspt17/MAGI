-- 기존 기록의 누락 사용량과 계산 근거를 추정해서 채우지 않는다.
ALTER TABLE cost_calls
 ADD COLUMN cache_write_tokens bigint CHECK (cache_write_tokens >= 0),
 ADD COLUMN cache_write_30m_tokens bigint CHECK (cache_write_30m_tokens >= 0),
 ADD COLUMN cache_write_12h_tokens bigint CHECK (cache_write_12h_tokens >= 0),
 ADD COLUMN cost_policy text;
ALTER TABLE admin_audit ADD COLUMN details jsonb;
