import asyncio
from pathlib import Path
from typing import Protocol

from document_ingestion.domain.errors import StorageError


class ObjectStorage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def healthcheck(self) -> None: ...


class LocalFileStorage:
    """Atomic local filesystem storage for development and deterministic tests."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise StorageError("storage key escapes the storage root")
        return candidate

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        del content_type
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        try:
            await asyncio.to_thread(temporary.write_bytes, data)
            await asyncio.to_thread(temporary.replace, path)
        except OSError as exc:
            raise StorageError("could not write the local object") from exc

    async def get(self, key: str) -> bytes:
        try:
            return await asyncio.to_thread(self._path(key).read_bytes)
        except OSError as exc:
            raise StorageError("could not read the stored object") from exc

    async def delete(self, key: str) -> None:
        try:
            path = self._path(key)
            if path.exists():
                await asyncio.to_thread(path.unlink)
        except OSError as exc:
            raise StorageError("could not delete the stored object") from exc

    async def healthcheck(self) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError("local storage is unavailable") from exc


class S3ObjectStorage:
    """Production object storage adapter; boto3 is isolated behind the async port."""

    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
    ) -> None:
        if not bucket:
            raise ValueError("S3_BUCKET is required for the S3 storage backend")
        self.bucket = bucket
        self._client_kwargs = {
            "region_name": region,
            "endpoint_url": endpoint_url,
            "aws_access_key_id": access_key_id,
            "aws_secret_access_key": secret_access_key,
        }

    def _client(self):
        import boto3

        return boto3.client("s3", **self._client_kwargs)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self._client().put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )

    async def get(self, key: str) -> bytes:
        response = await asyncio.to_thread(self._client().get_object, Bucket=self.bucket, Key=key)
        return await asyncio.to_thread(response["Body"].read)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client().delete_object, Bucket=self.bucket, Key=key)

    async def healthcheck(self) -> None:
        await asyncio.to_thread(self._client().head_bucket, Bucket=self.bucket)


def build_storage(settings) -> ObjectStorage:
    if settings.storage_backend == "local":
        return LocalFileStorage(settings.storage_path)
    if settings.storage_backend == "s3":
        return S3ObjectStorage(
            bucket=settings.s3_bucket,
            region=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
        )
    raise ValueError(f"unsupported storage backend: {settings.storage_backend}")
