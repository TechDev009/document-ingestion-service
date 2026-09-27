import re
import unicodedata
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath

from document_ingestion.config import Settings
from document_ingestion.domain.errors import UploadValidationError

_ALLOWED_TYPES: dict[str, tuple[str, ...]] = {
    ".pdf": ("application/pdf", "application/octet-stream"),
    ".txt": ("text/plain", "application/octet-stream"),
    ".md": ("text/markdown", "text/x-markdown", "text/plain", "application/octet-stream"),
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
    ),
}
_CANONICAL_TYPES = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    original_filename: str
    safe_filename: str
    extension: str
    content_type: str
    size_bytes: int


def sha256_bytes(data: bytes) -> str:
    """Return the stable SHA-256 digest used for idempotency and chunk identity."""
    import hashlib

    return hashlib.sha256(data).hexdigest()


def safe_filename(filename: str) -> str:
    """Turn an untrusted multipart filename into a display-only basename."""
    if not filename or "\x00" in filename:
        raise UploadValidationError("filename is required and must not contain NUL bytes")
    normalized = unicodedata.normalize("NFKC", filename).replace("\\", "/")
    basename = normalized.rsplit("/", 1)[-1].strip()
    if basename in {"", ".", ".."}:
        raise UploadValidationError("filename must contain a basename")
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "_", basename).strip(" .")
    if not cleaned:
        cleaned = "upload"
    if len(cleaned) > 180:
        suffix = PurePosixPath(cleaned).suffix[:20]
        cleaned = f"{cleaned[: 180 - len(suffix)]}{suffix}"
    return cleaned


def _validate_docx_archive(data: bytes, settings: Settings) -> None:
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except (OSError, zipfile.BadZipFile) as exc:
        raise UploadValidationError("DOCX is not a valid ZIP document") from exc

    try:
        members = archive.infolist()
        if len(members) > settings.max_zip_members:
            raise UploadValidationError("DOCX contains too many ZIP members")
        total_uncompressed = 0
        names: set[str] = set()
        for member in members:
            name = member.filename.replace("\\", "/")
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts:
                raise UploadValidationError("DOCX contains an unsafe ZIP path")
            if member.is_dir():
                continue
            if member.external_attr >> 16 & 0o170000 == 0o120000:
                raise UploadValidationError("DOCX contains a symbolic link")
            if member.file_size < 0 or member.compress_size < 0:
                raise UploadValidationError("DOCX contains invalid ZIP metadata")
            if member.compress_size and member.file_size > member.compress_size * 200:
                raise UploadValidationError("DOCX compression ratio exceeds the safety limit")
            total_uncompressed += member.file_size
            if total_uncompressed > settings.max_uncompressed_bytes:
                raise UploadValidationError("DOCX uncompressed size exceeds the safety limit")
            names.add(name)
        required = {"[Content_Types].xml", "word/document.xml"}
        if not required.issubset(names):
            raise UploadValidationError("DOCX is missing its required document parts")
    finally:
        archive.close()


def validate_upload(
    filename: str,
    declared_content_type: str | None,
    data: bytes,
    settings: Settings,
) -> ValidatedUpload:
    """Validate size, type, magic bytes, and archive limits before storage."""
    if not data:
        raise UploadValidationError("uploaded document is empty")
    if len(data) > settings.max_upload_bytes:
        raise UploadValidationError(
            f"document exceeds the {settings.max_upload_bytes} byte upload limit"
        )
    safe = safe_filename(filename)
    extension = PurePosixPath(safe).suffix.lower()
    if extension not in _ALLOWED_TYPES:
        raise UploadValidationError("unsupported document extension; use PDF, TXT, MD, or DOCX")

    content_type = (declared_content_type or "application/octet-stream").split(";", 1)[0].lower()
    if content_type not in _ALLOWED_TYPES[extension]:
        raise UploadValidationError("declared content type does not match the filename")

    if extension == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise UploadValidationError("PDF magic bytes are missing")
    elif extension in {".txt", ".md"}:
        if b"\x00" in data:
            raise UploadValidationError("text documents must not contain NUL bytes")
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise UploadValidationError("text documents must be valid UTF-8") from exc
    else:
        if not data.startswith(b"PK\x03\x04"):
            raise UploadValidationError("DOCX ZIP magic bytes are missing")
        _validate_docx_archive(data, settings)

    return ValidatedUpload(
        original_filename=filename[:255],
        safe_filename=safe,
        extension=extension,
        content_type=_CANONICAL_TYPES[extension],
        size_bytes=len(data),
    )
