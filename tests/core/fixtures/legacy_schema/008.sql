-- 이전 기록에는 없는 시각과 사용량을 채우지 않는다.
ALTER TABLE magi_cost_calls
 ADD COLUMN reserved_at timestamptz,
 ADD COLUMN called_at timestamptz,
 ADD COLUMN settled_at timestamptz,
 ADD COLUMN input_tokens bigint CHECK (input_tokens >= 0),
 ADD COLUMN output_tokens bigint CHECK (output_tokens >= 0),
 ADD COLUMN cached_tokens bigint CHECK (cached_tokens >= 0 AND cached_tokens <= input_tokens),
 ADD COLUMN settlement_source text CHECK (settlement_source IN ('calculated','manual'));
CREATE INDEX magi_cost_calls_usage_day ON magi_cost_calls(day,user_id,job_id);
CREATE INDEX magi_cost_calls_called_at ON magi_cost_calls(called_at,user_id,job_id);
