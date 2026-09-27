from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration with safe, dependency-free local defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "document-ingestion-service"
    environment: str = "development"
    debug: bool = False
    database_url: str = "sqlite+aiosqlite:///./data/documents.db"
    auto_create_schema: bool = True
    storage_backend: str = "local"
    storage_path: Path = Path("./data/objects")
    queue_backend: str = "local"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    rabbitmq_queue: str = "document-ingestion"
    s3_bucket: str = ""
    s3_region: str = "us-east-1"
    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    max_pdf_pages: int = Field(default=100, gt=0)
    max_uncompressed_bytes: int = Field(default=50 * 1024 * 1024, gt=0)
    max_zip_members: int = Field(default=2_000, gt=0)
    max_text_chars: int = Field(default=5_000_000, gt=0)
    chunk_size: int = Field(default=1_200, gt=0)
    chunk_overlap: int = Field(default=120, ge=0)
    max_retries: int = Field(default=3, ge=1)
    cors_origins: str = ""

    @field_validator("storage_backend", "queue_backend", mode="before")
    @classmethod
    def normalize_backend(cls, value: str) -> str:
        return str(value).strip().lower()

    @field_validator("chunk_overlap")
    @classmethod
    def validate_overlap(cls, value: int, info: object) -> int:
        chunk_size = info.data.get("chunk_size", 1_200)  # type: ignore[union-attr]
        if value >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
