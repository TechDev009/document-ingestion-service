import asyncio
import json
from typing import Protocol

from document_ingestion.config import Settings
from document_ingestion.services import IngestionService


class JobQueue(Protocol):
    async def enqueue(self, job_id: str) -> None: ...

    async def close(self) -> None: ...


class LocalBackgroundQueue:
    """Development queue: in-process tasks with durable state in the database."""

    def __init__(self, worker: IngestionService) -> None:
        self.worker = worker
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def enqueue(self, job_id: str) -> None:
        current = self._tasks.get(job_id)
        if current is not None and not current.done():
            return
        task = asyncio.create_task(self._run(job_id), name=f"document-job-{job_id}")
        self._tasks[job_id] = task
        await task

    async def _run(self, job_id: str) -> None:
        try:
            for delay in (0.0, 0.25, 0.75, 2.0):
                if delay:
                    await asyncio.sleep(delay)
                result = await self.worker.process_job(job_id)
                if not result.retry:
                    return
        finally:
            self._tasks.pop(job_id, None)

    async def wait_for_idle(self) -> None:
        tasks = list(self._tasks.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()


class RabbitMQQueue:
    """Durable RabbitMQ adapter used when API and workers run as separate processes."""

    def __init__(self, url: str, queue_name: str) -> None:
        self.url = url
        self.queue_name = queue_name
        self._connection = None
        self._channel = None

    async def _ensure_channel(self):
        import aio_pika

        if self._channel is None or self._channel.is_closed:
            self._connection = await aio_pika.connect_robust(self.url)
            self._channel = await self._connection.channel()
            await self._channel.set_qos(prefetch_count=4)
            await self._channel.declare_queue(self.queue_name, durable=True)
        return self._channel

    async def enqueue(self, job_id: str) -> None:
        import aio_pika

        channel = await self._ensure_channel()
        await channel.default_exchange.publish(
            aio_pika.Message(
                body=json.dumps({"job_id": job_id}).encode("utf-8"),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                content_type="application/json",
            ),
            routing_key=self.queue_name,
        )

    async def consume(self, worker: IngestionService) -> None:
        channel = await self._ensure_channel()
        queue = await channel.declare_queue(self.queue_name, durable=True)
        async with queue.iterator() as iterator:
            async for message in iterator:
                async with message.process(requeue=False):
                    payload = json.loads(message.body.decode("utf-8"))
                    job_id = str(payload["job_id"])
                    result = await worker.process_job(job_id)
                    if result.retry:
                        await self.enqueue(job_id)

    async def close(self) -> None:
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()


def build_queue(settings: Settings, worker: IngestionService) -> JobQueue:
    if settings.queue_backend == "local":
        return LocalBackgroundQueue(worker)
    if settings.queue_backend == "rabbitmq":
        return RabbitMQQueue(settings.rabbitmq_url, settings.rabbitmq_queue)
    raise ValueError(f"unsupported queue backend: {settings.queue_backend}")
