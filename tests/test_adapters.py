import pytest

from document_ingestion.adapters.storage import LocalFileStorage
from document_ingestion.domain.errors import StorageError


@pytest.mark.asyncio
async def test_local_storage_rejects_traversal_and_round_trips(tmp_path) -> None:
    storage = LocalFileStorage(tmp_path / "objects")
    await storage.put("documents/id/file.txt", b"content", "text/plain")
    assert await storage.get("documents/id/file.txt") == b"content"
    with pytest.raises(StorageError):
        await storage.get("../../outside")
    await storage.delete("documents/id/file.txt")
