from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ProcessingStatus(StrEnum):
    CREATED = "created"
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


_ALLOWED_TRANSITIONS: dict[ProcessingStatus, frozenset[ProcessingStatus]] = {
    ProcessingStatus.CREATED: frozenset({ProcessingStatus.UPLOADED, ProcessingStatus.FAILED}),
    ProcessingStatus.UPLOADED: frozenset({ProcessingStatus.PROCESSING, ProcessingStatus.FAILED}),
    ProcessingStatus.PROCESSING: frozenset(
        {ProcessingStatus.READY, ProcessingStatus.UPLOADED, ProcessingStatus.FAILED}
    ),
    ProcessingStatus.READY: frozenset({ProcessingStatus.READY}),
    ProcessingStatus.FAILED: frozenset(
        {ProcessingStatus.PROCESSING, ProcessingStatus.UPLOADED, ProcessingStatus.FAILED}
    ),
}


def can_transition(current: ProcessingStatus, target: ProcessingStatus) -> bool:
    return target in _ALLOWED_TRANSITIONS[current]


class ChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    position: int = Field(ge=0)
    text: str
    sha256: str


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    original_filename: str
    safe_filename: str
    content_type: str
    size_bytes: int = Field(ge=0)
    sha256: str
    status: ProcessingStatus
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    chunks: list[ChunkRead] = Field(default_factory=list)


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    status: ProcessingStatus
    attempts: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class UploadResponse(BaseModel):
    document: DocumentRead
    job: JobRead


class HealthResponse(BaseModel):
    status: str
    service: str


class TextChunk(BaseModel):
    position: int = Field(ge=0)
    text: str
    sha256: str
