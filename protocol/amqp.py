"""AMQP 접속과 채널 조작은 전용 I/O 스레드에 한정한다."""
from concurrent.futures import Future
import json
import threading
from typing import Any
from dataclasses import dataclass

EXCHANGE = 'magi.execution.events'


@dataclass(frozen=True, repr=False)
class BrokerSettings:
    host: str
    port: int
    virtual_host: str
    username: str
    password: str

    @classmethod
    def from_mapping(cls, values):
        names = ('RABBITMQ_HOST', 'RABBITMQ_PORT', 'RABBITMQ_VHOST', 'RABBITMQ_USER', 'RABBITMQ_PASSWORD')
        if any(not isinstance(values.get(name), str) or not values[name] for name in names):
            raise ValueError('RabbitMQ 필수 연결 설정을 확인하세요.')
        try:
            port = int(values['RABBITMQ_PORT'])
            if not 1 <= port <= 65535:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('RabbitMQ 포트 설정을 확인하세요.') from None
        return cls(values['RABBITMQ_HOST'], port, values['RABBITMQ_VHOST'], values['RABBITMQ_USER'], values['RABBITMQ_PASSWORD'])

    def parameters(self):
        import pika
        return pika.ConnectionParameters(host=self.host, port=self.port, virtual_host=self.virtual_host,
            credentials=pika.PlainCredentials(self.username, self.password), heartbeat=30,
            blocked_connection_timeout=15, socket_timeout=5)


def routing_key(owner, job=None):
    # routing key에 와일드카드·구분자를 주입하지 못하게 한다.
    import re
    if not isinstance(owner, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', owner):
        raise ValueError('사용자 식별값을 확인하세요.')
    if job is not None and (not isinstance(job, str) or not re.fullmatch(r'[a-f0-9]{32}', job)):
        raise ValueError('작업 식별값을 확인하세요.')
    return f'user.{owner}.job.{job}' if job else f'user.{owner}.list'


class Broker:
    def __init__(self, settings: BrokerSettings, on_disconnect=lambda: None):
        self.settings, self.on_disconnect = settings, on_disconnect
        self.ready = threading.Event()
        self.stopped = threading.Event()
        self.connection: Any = None
        self.channel: Any = None
        self.pending: dict[int, Future[Any]] = {}
        self.sequence = 0
        self.thread = threading.Thread(target=self._run, name='amqp', daemon=True)
        self.thread.start()

    def _run(self):
        import pika
        import logging
        # 라이브러리의 접속 오류 원문 대신 애플리케이션의 고정 상태만 노출한다.
        logger = logging.getLogger('pika')
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False
        while not self.stopped.is_set():
            try:
                params = self.settings.parameters()
                self.connection = pika.SelectConnection(params, on_open_callback=self._opened,
                    on_open_error_callback=self._failed, on_close_callback=self._failed)
                self.connection.ioloop.start()
            except Exception:
                # 접속 정보나 예외 본문에는 인증 정보가 포함될 수 있어 기록하지 않는다.
                pass
            finally:
                self.ready.clear()
                for future in tuple(self.pending.values()):
                    if not future.done():
                        future.set_exception(ConnectionError('이벤트 서버 연결이 끊어졌습니다.'))
                self.pending.clear()
                self.on_disconnect()
                if self.connection:
                    self.connection.ioloop.close()
            self.stopped.wait(2)

    def _opened(self, connection):
        connection.channel(on_open_callback=self._channel)

    def _channel(self, channel):
        self.channel = channel
        self.sequence = 0
        channel.add_on_close_callback(lambda *_: self.connection.close() if self.connection.is_open else None)
        channel.exchange_declare(exchange=EXCHANGE, exchange_type='topic', durable=True,
            callback=lambda _: channel.basic_qos(prefetch_count=32, callback=lambda _: channel.confirm_delivery(
                ack_nack_callback=self._confirm, callback=lambda _: self.ready.set())))

    def _failed(self, connection, _reason):
        connection.ioloop.stop()

    def _confirm(self, frame):
        tag = frame.method.delivery_tag
        tags = [key for key in self.pending if key <= tag] if frame.method.multiple else [tag]
        for key in tags:
            future = self.pending.pop(key, None)
            if future and not future.done():
                if frame.method.NAME == 'Basic.Ack':
                    future.set_result(True)
                else:
                    future.set_exception(ConnectionError('이벤트 발행을 재시도합니다.'))

    def call(self, callback):
        future: Future[Any] = Future()
        if not self.ready.is_set():
            future.set_exception(ConnectionError('이벤트 서버에 연결 중입니다.'))
            return future
        def invoke():
            try:
                if not self.ready.is_set():
                    raise ConnectionError('이벤트 서버에 연결 중입니다.')
                callback(self.channel, future)
            except Exception:
                if not future.done():
                    future.set_exception(ConnectionError('이벤트 처리를 완료하지 못했습니다.'))
        self.connection.ioloop.add_callback_threadsafe(invoke)
        return future

    def publish(self, key, payload):
        import pika
        body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
        def send(channel, future):
            self.sequence += 1
            self.pending[self.sequence] = future
            channel.basic_publish(EXCHANGE, key, body,
                properties=pika.BasicProperties(content_type='application/json'), mandatory=False)
        return self.call(send)

    def subscribe(self, key, receive):
        def declare(channel, future):
            def declared(frame):
                queue = frame.method.queue
                def consume(_):
                    def delivered(ch, method, _properties, body):
                        try:
                            if len(body) > 4 * 1024 * 1024:
                                raise ValueError()
                            receive(json.loads(body))
                        except Exception:
                            ch.basic_reject(method.delivery_tag, requeue=False)
                        else:
                            ch.basic_ack(method.delivery_tag)
                    tag: str = channel.basic_consume(queue, delivered, auto_ack=False,
                        callback=lambda _: future.set_result((queue, tag)) if not future.done() else None)
                channel.queue_bind(queue, EXCHANGE, routing_key=key, callback=consume)
            channel.queue_declare(queue='', exclusive=True, auto_delete=True, durable=False,
                arguments={'x-queue-type': 'classic', 'x-message-ttl': 60000,
                           'x-max-length-bytes': 4 * 1024 * 1024, 'x-overflow': 'drop-head'}, callback=declared)
        return self.call(declare)

    def unsubscribe(self, subscription):
        queue, tag = subscription
        def cancel(channel, future):
            channel.basic_cancel(tag, callback=lambda _: channel.queue_delete(queue,
                callback=lambda _: future.set_result(True)))
        return self.call(cancel)

    def close(self):
        self.stopped.set()
        connection = self.connection
        if connection:
            try:
                connection.ioloop.add_callback_threadsafe(lambda: connection.close() if connection.is_open else connection.ioloop.stop())
            except RuntimeError:
                pass
        self.thread.join(timeout=10)
