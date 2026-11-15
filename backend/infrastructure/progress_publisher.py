"""브로커 장애는 실행 워커에 전파하지 않고 outbox에서 재시도한다."""
import asyncio
from protocol.amqp import Broker, routing_key
from backend.infrastructure.progress_store import ProgressStore


class ProgressPublisher:
    def __init__(self, store, settings):
        self.store = ProgressStore(store)
        self.broker = Broker(settings)
        self.wake = asyncio.Event()
        self.stopped = asyncio.Event()
        self.task = asyncio.create_task(self._run(), name='progress-outbox')

    async def _run(self):
        # 2026-11-13: outbox DB 대기는 이벤트 루프에서 비동기로 처리한다.
        while not self.stopped.is_set():
            try:
                if not self.broker.ready.is_set():
                    try:
                        await asyncio.wait_for(self.stopped.wait(), timeout=1)
                    except asyncio.TimeoutError:
                        pass
                    continue
                rows = await self.store.pending()
                for row in rows:
                    owner = row['owner_id']
                    if owner:
                        if row['payload'].get('event') == 'records.deleted':
                            await asyncio.wait_for(asyncio.wrap_future(self.broker.publish(routing_key(owner), row['payload'])), timeout=15)
                            await self.store.delivered(row['id'])
                            continue
                        await asyncio.wait_for(asyncio.wrap_future(self.broker.publish(routing_key(owner, row['job_id']), row['payload'])), timeout=15)
                        await asyncio.wait_for(asyncio.wrap_future(self.broker.publish(routing_key(owner), {
                            'event': 'jobs.changed', 'job_id': row['job_id'], 'revision': row['payload']['revision'],
                            'job': {k: v for k, v in row['payload']['job'].items() if k != 'execution_graph'}
                        })), timeout=15)
                    await self.store.delivered(row['id'])
                if len(rows) == 100:
                    continue
            except Exception:
                # 원문 응답·접속 문자열은 로그에 남기지 않는다.
                pass
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
            self.wake.clear()

    async def close(self):
        self.stopped.set()
        self.wake.set()
        await asyncio.to_thread(self.broker.close)
        await self.task
