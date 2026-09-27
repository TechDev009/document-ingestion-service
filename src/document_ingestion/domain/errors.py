class IngestionError(Exception):
    """Base class for expected ingestion failures."""


class UploadValidationError(IngestionError):
    """The upload violates a size, type, or content safety policy."""


class ExtractionError(IngestionError):
    """A supported document could not be safely converted to text."""


class StorageError(IngestionError):
    """An object storage operation failed."""


class NotFoundError(IngestionError):
    """A requested document or job does not exist."""
