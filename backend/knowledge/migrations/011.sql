-- 기존 작업의 소유자가 하나로 확인되는 프로젝트만 개인 프로젝트로 이관한다.
ALTER TABLE projects ADD COLUMN owner_id text;
UPDATE projects p SET owner_id=s.owner_id FROM (
 SELECT project_id,min(owner_id) AS owner_id FROM jobs GROUP BY project_id
 HAVING count(*)=count(owner_id) AND count(DISTINCT owner_id)=1
) s WHERE p.id=s.project_id;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects FORCE ROW LEVEL SECURITY;
CREATE POLICY owner ON projects USING (current_setting('app.internal',true)='on' OR owner_id=current_setting('app.actor',true))
 WITH CHECK (current_setting('app.internal',true)='on' OR owner_id=current_setting('app.actor',true));
CREATE TABLE project_decisions (
 id text PRIMARY KEY, project_id text NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 source_job_id text REFERENCES jobs(id) ON DELETE SET NULL,
 completed_id text NOT NULL, decision_id text NOT NULL, version integer NOT NULL DEFAULT 1,
 active boolean NOT NULL DEFAULT true, data jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(project_id,completed_id,decision_id)
);
CREATE INDEX project_decisions_project ON project_decisions(project_id,created_at,id);
ALTER TABLE project_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_decisions FORCE ROW LEVEL SECURITY;
CREATE POLICY owner ON project_decisions USING (current_setting('app.internal',true)='on' OR EXISTS(SELECT 1 FROM projects p WHERE p.id=project_id))
 WITH CHECK (current_setting('app.internal',true)='on' OR (EXISTS(SELECT 1 FROM projects p WHERE p.id=project_id)
 AND (source_job_id IS NULL OR EXISTS(SELECT 1 FROM jobs j WHERE j.id=source_job_id AND j.project_id=project_decisions.project_id))));
