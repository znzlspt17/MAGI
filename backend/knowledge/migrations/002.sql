-- 전역 사용권 대신 실행별 세대와 상태로 저장·정산을 보호한다.
CREATE TABLE public.execution_leases (
 execution_id text PRIMARY KEY,
 generation bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
 owner_id text NOT NULL REFERENCES public.users(id),
 job_id text NOT NULL,
 kind text NOT NULL CHECK(kind IN ('workflow','auxiliary')),
 phase text NOT NULL CHECK(phase IN ('queued','running','finished','interrupted','recovery')),
 stopping boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX one_active_workflow_per_job ON public.execution_leases(job_id)
 WHERE kind='workflow' AND phase IN ('queued','running');
CREATE INDEX execution_leases_active ON public.execution_leases(owner_id,phase);
ALTER TABLE public.cost_calls ADD COLUMN execution_id text;
ALTER TABLE public.cost_calls ADD COLUMN execution_generation bigint;
-- 중단 전 호출 여부를 추정하지 않고 기존 예약액을 보존한다.
UPDATE public.cost_calls SET state='uncertain' WHERE state='reserved';
DROP TABLE public.service_lease;
