-- 늦게 도착한 별도 프로세스의 저장으로 삭제한 작업이 부활하지 않게 한다.
CREATE TABLE magi_deleted_jobs (id text PRIMARY KEY);
CREATE TABLE magi_cleanup_commits (id text PRIMARY KEY);
CREATE TABLE magi_deleted_nodes (id text PRIMARY KEY);
