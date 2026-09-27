import asyncio

from document_ingestion.adapters.queue import RabbitMQQueue
from document_ingestion.adapters.storage import build_storage
from document_ingestion.config import Settings
from document_ingestion.database import Database
from document_ingestion.services import IngestionService


async def run_worker(settings: Settings | None = None) -> None:
    runtime_settings = settings or Settings()
    database = Database(runtime_settings.database_url, echo=runtime_settings.debug)
    storage = build_storage(runtime_settings)
    service = IngestionService(database, storage, runtime_settings)
    if runtime_settings.auto_create_schema:
        await database.create_all()
    await storage.healthcheck()
    if runtime_settings.queue_backend != "rabbitmq":
        await database.dispose()
        raise RuntimeError("the standalone worker requires QUEUE_BACKEND=rabbitmq")
    queue = RabbitMQQueue(runtime_settings.rabbitmq_url, runtime_settings.rabbitmq_queue)
    try:
        await queue.consume(service)
    finally:
        await queue.close()
        await database.dispose()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
