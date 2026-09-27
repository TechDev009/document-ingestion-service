import pytest

from document_ingestion.domain.models import ProcessingStatus


@pytest.mark.asyncio
async def test_status_transitions_duplicate_processing_and_chunks(service) -> None:
    upload = await service.upload(
        filename="notes.txt", content_type="text/plain", data=b"a useful document"
    )
    assert upload.document.status == ProcessingStatus.UPLOADED
    assert upload.job.status == ProcessingStatus.UPLOADED

    first = await service.process_job(upload.job.id)
    assert not first.retry
    ready_job = await service.get_job(upload.job.id)
    ready_document = await service.get_document(upload.document.id)
    assert ready_job is not None and ready_job.status == ProcessingStatus.READY
    assert ready_document is not None and ready_document.status == ProcessingStatus.READY
    assert ready_document.chunks

    # A duplicate delivery is a no-op and does not append duplicate chunks.
    await service.process_job(upload.job.id)
    duplicate = await service.upload(
        filename="renamed.txt", content_type="text/plain", data=b"a useful document"
    )
    assert duplicate.document.id == upload.document.id
    assert duplicate.job.id == upload.job.id
    after_duplicate = await service.get_document(upload.document.id)
    assert after_duplicate is not None
    assert len(after_duplicate.chunks) == len(ready_document.chunks)


@pytest.mark.asyncio
async def test_processing_retry_reaches_failed(service) -> None:
    upload = await service.upload(
        filename="missing.txt", content_type="text/plain", data=b"payload"
    )
    await service.storage.delete(f"documents/{upload.document.id}/missing.txt")

    first = await service.process_job(upload.job.id)
    assert first.retry
    second = await service.process_job(upload.job.id)
    assert not second.retry
    job = await service.get_job(upload.job.id)
    document = await service.get_document(upload.document.id)
    assert job is not None and job.status == ProcessingStatus.FAILED
    assert document is not None and document.status == ProcessingStatus.FAILED
    assert job.attempts == 2
