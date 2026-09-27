from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import BackgroundTasks, FastAPI, File, Header, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from document_ingestion.adapters.queue import JobQueue, build_queue
from document_ingestion.adapters.storage import ObjectStorage, build_storage
from document_ingestion.config import Settings
from document_ingestion.database import Database
from document_ingestion.domain.errors import IngestionError, StorageError, UploadValidationError
from document_ingestion.domain.models import DocumentRead, HealthResponse, JobRead, UploadResponse
from document_ingestion.services import IngestionService


@dataclass(slots=True)
class AppContainer:
    settings: Settings
    database: Database
    storage: ObjectStorage
    service: IngestionService
    queue: JobQueue


async def _read_upload(file: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = await file.read(min(1024 * 1024, max_bytes + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise UploadValidationError(f"document exceeds the {max_bytes} byte upload limit")
            chunks.append(chunk)
    finally:
        await file.close()
    return b"".join(chunks)


def _container(app: FastAPI) -> AppContainer:
    return app.state.container


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or Settings()
    database = Database(runtime_settings.database_url, echo=runtime_settings.debug)
    storage = build_storage(runtime_settings)
    service = IngestionService(database, storage, runtime_settings)
    queue = build_queue(runtime_settings, service)
    container = AppContainer(runtime_settings, database, storage, service, queue)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if runtime_settings.auto_create_schema:
            await database.create_all()
        await storage.healthcheck()
        yield
        await queue.close()
        await database.dispose()

    app = FastAPI(
        title=runtime_settings.app_name,
        version="0.1.0",
        debug=runtime_settings.debug,
        lifespan=lifespan,
    )
    app.state.container = container
    if runtime_settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=runtime_settings.cors_origin_list,
            allow_credentials=False,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Content-Type", "Idempotency-Key"],
        )

    @app.exception_handler(UploadValidationError)
    async def upload_validation_handler(_, exc: UploadValidationError) -> JSONResponse:
        message = str(exc)
        code = (
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            if "exceed" in message
            else status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(status_code=code, content={"detail": message})

    @app.exception_handler(StorageError)
    async def storage_handler(_, exc: StorageError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)}
        )

    @app.get("/v1/health/live", response_model=HealthResponse, tags=["health"])
    async def live() -> HealthResponse:
        return HealthResponse(status="ok", service=runtime_settings.app_name)

    @app.get("/v1/health/ready", response_model=HealthResponse, tags=["health"])
    async def ready() -> HealthResponse:
        try:
            await database.ping()
            await storage.healthcheck()
        except Exception as exc:
            raise HTTPException(
                status_code=503, detail="service dependencies are not ready"
            ) from exc
        return HealthResponse(status="ready", service=runtime_settings.app_name)

    @app.post(
        "/v1/documents",
        response_model=UploadResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["documents"],
    )
    async def upload_document(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> UploadResponse:
        del idempotency_key  # SHA-256 content identity provides replay-safe behavior.
        data = await _read_upload(file, runtime_settings.max_upload_bytes)
        try:
            result = await service.upload(
                filename=file.filename or "upload.txt",
                content_type=file.content_type,
                data=data,
            )
        except IngestionError:
            raise
        background_tasks.add_task(queue.enqueue, result.job.id)
        return result

    @app.get("/v1/documents/{document_id}", response_model=DocumentRead, tags=["documents"])
    async def get_document(document_id: str) -> DocumentRead:
        result = await service.get_document(document_id)
        if result is None:
            raise HTTPException(status_code=404, detail="document not found")
        return result

    @app.delete("/v1/documents/{document_id}", status_code=204, tags=["documents"])
    async def delete_document(document_id: str) -> Response:
        deleted = await service.delete_document(document_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="document not found")
        return Response(status_code=204)

    @app.get("/v1/jobs/{job_id}", response_model=JobRead, tags=["jobs"])
    async def get_job(job_id: str) -> JobRead:
        result = await service.get_job(job_id)
        if result is None:
            raise HTTPException(status_code=404, detail="job not found")
        return result

    return app


app = create_app()
