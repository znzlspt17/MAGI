-- 실행 checkpoint와 무관하게 작업의 원격 대화 연결을 보존한다.
ALTER TABLE core.jobs
 ADD COLUMN openai_conversation_id text UNIQUE,
 ADD COLUMN openai_conversation_state text NOT NULL DEFAULT 'new'
   CHECK (openai_conversation_state IN ('new','creating','initializing','ready')),
 ADD COLUMN openai_call_pending boolean NOT NULL DEFAULT false,
 ADD COLUMN openai_last_response_id text;
ALTER TABLE core.jobs ADD CONSTRAINT conversation_ready_requires_id
 CHECK ((openai_conversation_state IN ('initializing','ready')) = (openai_conversation_id IS NOT NULL));
