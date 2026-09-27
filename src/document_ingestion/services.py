import uuid
from dataclasses import dataclass

from document_ingestion.adapters.storage import ObjectStorage
from document_ingestion.chunking import chunk_text
from document_ingestion.config import Settings
from document_ingestion.database import Database
from document_ingestion.domain.errors import ExtractionError, StorageError
from document_ingestion.domain.models import DocumentRead, JobRead, ProcessingStatus, UploadResponse
from document_ingestion.extractors import extension_from_filename, extract_text
from document_ingestion.repositories import DocumentRepository
from document_ingestion.validation import sha256_bytes, validate_upload


def _document_read(document, chunks=None) -> DocumentRead:
    return DocumentRead(
        id=document.id,
        original_filename=document.original_filename,
        safe_filename=document.safe_filename,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        sha256=document.sha256,
        status=document.status,
        error_message=document.error_message,
        created_at=document.created_at,
        updated_at=document.updated_at,
        chunks=chunks or [],
    )


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    retry: bool


class IngestionService:
    """Application service coordinating validation, persistence, storage, and processing."""

    def __init__(self, database: Database, storage: ObjectStorage, settings: Settings) -> None:
        self.database = database
        self.storage = storage
        self.settings = settings

    async def upload(
        self, *, filename: str, content_type: str | None, data: bytes
    ) -> UploadResponse:
        validated = validate_upload(filename, content_type, data, self.settings)
        checksum = sha256_bytes(data)
        async with self.database.session_factory() as session:
            repository = DocumentRepository(session)
            existing = await repository.get_document_by_checksum(checksum)
            if existing is not None:
                job = await repository.get_job_for_document(existing.id)
                if job is None:
                    job = await repository.create_job(
                        document_id=existing.id, max_attempts=self.settings.max_retries
                    )
                    await session.commit()
                return UploadResponse(
                    document=_document_read(existing),
                    job=JobRead.model_validate(job),
                )

            document_id = str(uuid.uuid4())
            storage_key = f"documents/{document_id}/{validated.safe_filename}"
            document = await repository.create_document(
                document_id=document_id,
                original_filename=validated.original_filename,
                safe_filename=validated.safe_filename,
                content_type=validated.content_type,
                size_bytes=validated.size_bytes,
                sha256=checksum,
                storage_key=storage_key,
            )
            job = await repository.create_job(
                document_id=document_id, max_attempts=self.settings.max_retries
            )
            try:
                await self.storage.put(storage_key, data, validated.content_type)
                await repository.set_document_status(document, ProcessingStatus.UPLOADED)
                await repository.set_job_status(job, ProcessingStatus.UPLOADED)
                await session.commit()
            except Exception as exc:
                await session.rollback()
                failed_document = await repository.get_document(document_id)
                failed_job = await repository.get_job(job.id)
                if failed_document is not None and failed_job is not None:
                    try:
                        await repository.set_document_status(
                            failed_document, ProcessingStatus.FAILED, str(exc)[:500]
                        )
                        await repository.set_job_status(
                            failed_job, ProcessingStatus.FAILED, str(exc)[:500]
                        )
                        await session.commit()
                    except Exception:
                        await session.rollback()
                if isinstance(exc, StorageError):
                    raise
                raise StorageError("could not persist the uploaded document") from exc

            return UploadResponse(
                document=_document_read(document),
                job=JobRead.model_validate(job),
            )

    async def process_job(self, job_id: str) -> ProcessingResult:
        """Run one idempotent processing attempt; return whether a queue retry is needed."""
        async with self.database.session_factory() as session:
            repository = DocumentRepository(session)
            job = await repository.get_job(job_id)
            if job is None:
                return ProcessingResult(retry=False)
            document = await repository.get_document(job.document_id)
            if document is None:
                return ProcessingResult(retry=False)
            if (
                job.status == ProcessingStatus.READY.value
                and document.status == ProcessingStatus.READY.value
            ):
                return ProcessingResult(retry=False)
            if job.status == ProcessingStatus.PROCESSING.value:
                return ProcessingResult(retry=False)
            if job.attempts >= job.max_attempts and job.status == ProcessingStatus.FAILED.value:
                return ProcessingResult(retry=False)
            if job.status == ProcessingStatus.CREATED.value:
                await repository.set_job_status(job, ProcessingStatus.UPLOADED)
            if document.status == ProcessingStatus.CREATED.value:
                await repository.set_document_status(document, ProcessingStatus.UPLOADED)
            await repository.set_job_status(job, ProcessingStatus.PROCESSING)
            await repository.set_document_status(document, ProcessingStatus.PROCESSING)
            job.attempts += 1
            await session.commit()
            document_key = document.storage_key
            document_id = document.id
            safe_name = document.safe_filename

        try:
            data = await self.storage.get(document_key)
            if sha256_bytes(data) != document.sha256:
                raise ExtractionError("stored object checksum does not match the database")
            extracted = extract_text(data, extension_from_filename(safe_name), self.settings)
            chunks = chunk_text(
                extracted, max_chars=self.settings.chunk_size, overlap=self.settings.chunk_overlap
            )
        except Exception as exc:
            return await self._record_failure(job_id, str(exc)[:500])

        async with self.database.session_factory() as session:
            repository = DocumentRepository(session)
            job = await repository.get_job(job_id)
            document = await repository.get_document(document_id)
            if job is None or document is None:
                return ProcessingResult(retry=False)
            if job.status == ProcessingStatus.READY.value:
                return ProcessingResult(retry=False)
            await repository.add_chunks(
                document_id,
                [(chunk.position, chunk.text, chunk.sha256) for chunk in chunks],
            )
            await repository.set_document_status(document, ProcessingStatus.READY)
            await repository.set_job_status(job, ProcessingStatus.READY)
            await session.commit()
        return ProcessingResult(retry=False)

    async def _record_failure(self, job_id: str, message: str) -> ProcessingResult:
        async with self.database.session_factory() as session:
            repository = DocumentRepository(session)
            job = await repository.get_job(job_id)
            if job is None:
                return ProcessingResult(retry=False)
            document = await repository.get_document(job.document_id)
            if document is None:
                return ProcessingResult(retry=False)
            if job.attempts < job.max_attempts:
                await repository.set_job_status(job, ProcessingStatus.UPLOADED, message)
                await repository.set_document_status(document, ProcessingStatus.UPLOADED, message)
                await session.commit()
                return ProcessingResult(retry=True)
            await repository.set_job_status(job, ProcessingStatus.FAILED, message)
            await repository.set_document_status(document, ProcessingStatus.FAILED, message)
            await session.commit()
            return ProcessingResult(retry=False)

    async def get_document(self, document_id: str) -> DocumentRead | None:
        async with self.database.session_factory() as session:
            result = await DocumentRepository(session).get_document_with_chunks(document_id)
            if result is None:
                return None
            document, chunks = result
            return _document_read(
                document,
                [
                    {
                        "id": chunk.id,
                        "document_id": chunk.document_id,
                        "position": chunk.position,
                        "text": chunk.text,
                        "sha256": chunk.sha256,
                    }
                    for chunk in chunks
                ],
            )

    async def get_job(self, job_id: str) -> JobRead | None:
        async with self.database.session_factory() as session:
            job = await DocumentRepository(session).get_job(job_id)
            return JobRead.model_validate(job) if job is not None else None

    async def delete_document(self, document_id: str) -> bool:
        async with self.database.session_factory() as session:
            repository = DocumentRepository(session)
            document = await repository.get_document(document_id)
            if document is None:
                return False
            storage_key = document.storage_key
            await repository.delete_document(document)
            await session.commit()
        await self.storage.delete(storage_key)
        return True
