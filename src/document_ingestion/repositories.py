from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from document_ingestion.domain.models import ProcessingStatus, can_transition
from document_ingestion.persistence import ChunkRecord, DocumentRecord, JobRecord


def _now() -> datetime:
    return datetime.now(UTC)


class DocumentRepository:
    """Persistence port implemented with SQLAlchemy records."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_document(self, document_id: str) -> DocumentRecord | None:
        return await self.session.get(DocumentRecord, document_id)

    async def get_document_by_checksum(self, checksum: str) -> DocumentRecord | None:
        result = await self.session.execute(
            select(DocumentRecord)
            .where(DocumentRecord.sha256 == checksum)
            .order_by(DocumentRecord.created_at)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_document_with_chunks(
        self, document_id: str
    ) -> tuple[DocumentRecord, list[ChunkRecord]] | None:
        document = await self.get_document(document_id)
        if document is None:
            return None
        chunks_result = await self.session.execute(
            select(ChunkRecord)
            .where(ChunkRecord.document_id == document_id)
            .order_by(ChunkRecord.position)
        )
        return document, list(chunks_result.scalars())

    async def create_document(
        self,
        *,
        document_id: str,
        original_filename: str,
        safe_filename: str,
        content_type: str,
        size_bytes: int,
        sha256: str,
        storage_key: str,
    ) -> DocumentRecord:
        document = DocumentRecord(
            id=document_id,
            original_filename=original_filename,
            safe_filename=safe_filename,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256,
            storage_key=storage_key,
            status=ProcessingStatus.CREATED.value,
        )
        self.session.add(document)
        await self.session.flush()
        return document

    async def create_job(
        self, *, document_id: str, max_attempts: int, job_id: str | None = None
    ) -> JobRecord:
        job = JobRecord(
            id=job_id or str(uuid4()),
            document_id=document_id,
            status=ProcessingStatus.CREATED.value,
            max_attempts=max_attempts,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get_job(self, job_id: str) -> JobRecord | None:
        return await self.session.get(JobRecord, job_id)

    async def get_job_for_document(self, document_id: str) -> JobRecord | None:
        result = await self.session.execute(
            select(JobRecord)
            .where(JobRecord.document_id == document_id)
            .order_by(JobRecord.created_at)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def set_document_status(
        self,
        document: DocumentRecord,
        status: ProcessingStatus,
        error_message: str | None = None,
    ) -> None:
        current = ProcessingStatus(document.status)
        if not can_transition(current, status):
            raise ValueError(f"invalid document transition: {current.value} -> {status.value}")
        document.status = status.value
        document.error_message = error_message
        document.updated_at = _now()
        await self.session.flush()

    async def set_job_status(
        self,
        job: JobRecord,
        status: ProcessingStatus,
        error_message: str | None = None,
    ) -> None:
        current = ProcessingStatus(job.status)
        if not can_transition(current, status):
            raise ValueError(f"invalid job transition: {current.value} -> {status.value}")
        job.status = status.value
        job.error_message = error_message
        job.updated_at = _now()
        if status == ProcessingStatus.PROCESSING:
            job.started_at = _now()
        elif status in {ProcessingStatus.READY, ProcessingStatus.FAILED}:
            job.completed_at = _now()
        await self.session.flush()

    async def add_chunks(self, document_id: str, chunks: list[tuple[int, str, str]]) -> None:
        await self.session.execute(
            delete(ChunkRecord).where(ChunkRecord.document_id == document_id)
        )
        self.session.add_all(
            [
                ChunkRecord(
                    id=str(uuid4()),
                    document_id=document_id,
                    position=position,
                    text=text,
                    sha256=sha256,
                )
                for position, text, sha256 in chunks
            ]
        )
        await self.session.flush()

    async def delete_document(self, document: DocumentRecord) -> None:
        await self.session.delete(document)
        await self.session.flush()
