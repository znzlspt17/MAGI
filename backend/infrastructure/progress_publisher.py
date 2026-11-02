"""브로커 장애는 실행 워커에 전파하지 않고 outbox에서 재시도한다."""
import threading
from protocol.amqp import Broker, routing_key
from backend.infrastructure.progress_store import ProgressStore


class ProgressPublisher:
    def __init__(self, store, settings):
        self.store = ProgressStore(store)
        self.broker = Broker(settings)
        self.wake = threading.Event()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._run, name='progress-outbox', daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stopped.is_set():
            try:
                if not self.broker.ready.wait(1):
                    continue
                rows = self.store.pending()
                for row in rows:
                    owner = row['owner_id']
                    if owner:
                        if row['payload'].get('event') == 'records.deleted':
                            self.broker.publish(routing_key(owner), row['payload']).result(timeout=15)
                            self.store.delivered(row['id'])
                            continue
                        self.broker.publish(routing_key(owner, row['job_id']), row['payload']).result(timeout=15)
                        self.broker.publish(routing_key(owner), {
                            'event': 'jobs.changed', 'job_id': row['job_id'], 'revision': row['payload']['revision'],
                            'job': {k: v for k, v in row['payload']['job'].items() if k != 'execution_graph'}
                        }).result(timeout=15)
                    self.store.delivered(row['id'])
                if len(rows) == 100:
                    continue
            except Exception:
                # 원문 응답·접속 문자열은 로그에 남기지 않는다.
                pass
            self.wake.wait(5)
            self.wake.clear()

    def close(self):
        self.stopped.set()
        self.wake.set()
        self.broker.close()
        self.thread.join(timeout=20)
