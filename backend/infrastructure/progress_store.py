"""진행 상태와 outbox의 원자적 저장. 원문 결과는 이벤트에 넣지 않는다."""
from datetime import UTC, datetime
from uuid import uuid4


JOB_FIELDS = ('id', 'status', 'execution_id', 'created_at', 'updated_at', 'queued_at', 'action', 'request', 'message')
STEP_FIELDS = ('id', 'execution_id', 'action', 'title', 'stage', 'status', 'started_at', 'completed_at', 'has_document', 'detail_available', 'summary', 'duration_ms', 'issue_counts', 'has_issues')


def projection(job, nodes):
    return {**{k: job[k] for k in JOB_FIELDS if k in job},
            'execution_graph': {'nodes': [{k: n[k] for k in STEP_FIELDS if k in n} for n in nodes]}}


class ProgressStore:
    def __init__(self, store):
        self.store = store

    def capture(self, conn, job):
        nodes = [r['data'] for r in conn.execute(
            'SELECT data FROM execution_events WHERE job_id=%s ORDER BY sequence', (job['id'],)).fetchall()]
        snapshot = projection(job, nodes)
        row = conn.execute(
            'INSERT INTO execution_progress(job_id,revision,snapshot) VALUES (%s,1,%s) '
            'ON CONFLICT(job_id) DO UPDATE SET revision=execution_progress.revision+1,snapshot=EXCLUDED.snapshot '
            'WHERE execution_progress.snapshot IS DISTINCT FROM EXCLUDED.snapshot RETURNING revision',
            (job['id'], self.store._json(snapshot))).fetchone()
        if row:
            event = {'schema_version': 1, 'event': 'job.progress', 'event_id': uuid4().hex,
                     'job_id': job['id'], 'execution_id': job.get('execution_id'),
                     'revision': row['revision'], 'server_time': datetime.now(UTC).isoformat(), 'job': snapshot}
            conn.execute('INSERT INTO progress_outbox(job_id,owner_id,revision,payload) VALUES (%s,%s,%s,%s)',
                         (job['id'], job.get('owner_id'), row['revision'], self.store._json(event)))

    def snapshot(self, ident):
        with self.store.transaction(mode='read') as conn:
            saved = conn.execute('SELECT revision,snapshot FROM execution_progress WHERE job_id=%s', (ident,)).fetchone()
        if saved:
            return self._envelope(ident, saved)
        with self.store.transaction() as conn:
            row = conn.execute('SELECT data,owner_id FROM jobs WHERE id=%s', (ident,)).fetchone()
            if not row:
                raise KeyError(ident)
            self.capture(conn, {**row['data'], 'owner_id': row['owner_id']})
            saved = conn.execute('SELECT revision,snapshot FROM execution_progress WHERE job_id=%s', (ident,)).fetchone()
            return self._envelope(ident, saved)

    @staticmethod
    def _envelope(ident, saved):
        return {'event': 'job.snapshot', 'job_id': ident, 'revision': saved['revision'],
                'server_time': datetime.now(UTC).isoformat(), 'job': saved['snapshot']}

    def pending(self):
        with self.store.transaction(mode='read') as conn:
            return conn.execute('SELECT id,owner_id,job_id,payload FROM progress_outbox ORDER BY id LIMIT 100').fetchall()

    def delivered(self, ident):
        with self.store.transaction() as conn:
            conn.execute('DELETE FROM progress_outbox WHERE id=%s', (ident,))
