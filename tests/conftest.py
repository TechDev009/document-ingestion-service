from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from document_ingestion.adapters.storage import LocalFileStorage
from document_ingestion.config import Settings
from document_ingestion.database import Database
from document_ingestion.main import create_app
from document_ingestion.services import IngestionService


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'documents.db'}",
        storage_path=tmp_path / "objects",
        chunk_size=32,
        chunk_overlap=4,
        max_retries=2,
    )


@pytest.fixture
async def service(settings: Settings) -> AsyncIterator[IngestionService]:
    database = Database(settings.database_url)
    await database.create_all()
    storage = LocalFileStorage(settings.storage_path)
    yield IngestionService(database, storage, settings)
    await database.dispose()


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
