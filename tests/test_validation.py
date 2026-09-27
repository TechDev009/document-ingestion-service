from io import BytesIO

import pytest
from docx import Document

from document_ingestion.domain.errors import UploadValidationError
from document_ingestion.validation import safe_filename, sha256_bytes, validate_upload


def test_sha256_is_deterministic() -> None:
    assert (
        sha256_bytes(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert sha256_bytes(b"abc") == sha256_bytes(b"abc")


def test_safe_filename_removes_paths_and_unsafe_characters(settings) -> None:
    assert safe_filename("../../secret report?.txt") == "secret report_.txt"
    assert safe_filename(r"C:\\temp\\report.txt") == "report.txt"


def test_upload_validation_checks_type_magic_and_size(settings) -> None:
    valid = validate_upload("notes.txt", "text/plain; charset=utf-8", b"hello", settings)
    assert valid.safe_filename == "notes.txt"
    assert valid.content_type == "text/plain"

    with pytest.raises(UploadValidationError, match="magic"):
        validate_upload("fake.pdf", "application/pdf", b"not a PDF", settings)
    with pytest.raises(UploadValidationError, match="content type"):
        validate_upload("notes.txt", "application/pdf", b"hello", settings)
    with pytest.raises(UploadValidationError, match="empty"):
        validate_upload("notes.txt", "text/plain", b"", settings)


def test_docx_validation_rejects_malformed_zip(settings) -> None:
    with pytest.raises(UploadValidationError, match="DOCX"):
        validate_upload(
            "document.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            b"PK\x03\x04not-a-zip",
            settings,
        )


def test_valid_docx_is_accepted(settings) -> None:
    document = Document()
    document.add_paragraph("safe text")
    output = BytesIO()
    document.save(output)
    result = validate_upload(
        "document.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        output.getvalue(),
        settings,
    )
    assert result.extension == ".docx"
