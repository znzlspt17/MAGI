-- 현재 장애의 사용권만 복구한다. 수정 이미지 배포 전 backend·gateway를 중지한다.
-- 비용·예약·작업·checkpoint는 변경하지 않는다. 조건 불일치 시 전체 롤백한다.
-- psql에서는 -v ON_ERROR_STOP=1 -f 옵션으로 실행한다.
BEGIN;
SET LOCAL row_security = off;
SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
    expected_job CONSTANT text := 'dd60b7f84b7a48258e496f06f636ccba';
    current_lease record;
    current_status text;
    pending_count bigint;
BEGIN
    -- 서비스가 보유하는 프로세스 잠금과 충돌하면 어떤 자료도 수정하지 않는다.
    IF NOT pg_try_advisory_xact_lock(72410635) THEN
        RAISE EXCEPTION 'backend_still_running';
    END IF;

    SELECT job_id, phase, generation INTO STRICT current_lease
    FROM public.service_lease WHERE singleton = 1 FOR UPDATE;
    IF current_lease.job_id IS DISTINCT FROM expected_job
       OR current_lease.phase IS DISTINCT FROM 'recovery'
       OR current_lease.generation IS DISTINCT FROM 94::bigint THEN
        RAISE EXCEPTION 'unexpected_service_lease';
    END IF;

    SELECT data->>'status' INTO STRICT current_status
    FROM public.jobs WHERE id = expected_job FOR UPDATE;
    IF current_status IS DISTINCT FROM 'NEEDS_USER_INPUT' THEN
        RAISE EXCEPTION 'unexpected_job_status';
    END IF;

    SELECT count(*) INTO pending_count FROM (
        SELECT id FROM public.cost_calls
        WHERE job_id = expected_job AND state = 'uncertain'
        FOR SHARE
    ) AS pending;
    IF pending_count <> 3 THEN
        RAISE EXCEPTION 'unexpected_pending_cost_count';
    END IF;

    UPDATE public.service_lease
    SET owner_id = NULL, job_id = NULL, phase = 'idle',
        deadline = NULL, stopping = false
    WHERE singleton = 1;

    INSERT INTO public.admin_audit(id, actor_id, action, target_id)
    VALUES (replace(gen_random_uuid()::text, '-', ''), 'operator',
            'recover-billing-lease', expected_job);
END $$;

COMMIT;
