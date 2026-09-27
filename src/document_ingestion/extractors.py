from io import BytesIO
from pathlib import PurePosixPath

from markdown_it import MarkdownIt

from document_ingestion.config import Settings
from document_ingestion.domain.errors import ExtractionError


def _extract_markdown(data: bytes) -> str:
    try:
        source = data.decode("utf-8-sig")
        tokens = MarkdownIt("commonmark").parse(source)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ExtractionError("Markdown could not be parsed as UTF-8") from exc
    contents: list[str] = []
    for token in tokens:
        if token.type in {"inline", "code_block", "fence", "html_block"} and token.content:
            contents.append(token.content)
    return "\n".join(contents)


def _extract_docx(data: bytes, settings: Settings) -> str:
    try:
        from docx import Document

        document = Document(BytesIO(data))
        parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text]
        for table in document.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        return "\n".join(parts)
    except Exception as exc:  # python-docx exposes several parser-specific exceptions.
        raise ExtractionError("DOCX text extraction failed") from exc


def _extract_pdf(data: bytes, settings: Settings) -> str:
    try:
        import fitz

        with fitz.open(stream=data, filetype="pdf") as document:
            if document.page_count > settings.max_pdf_pages:
                raise ExtractionError("PDF page count exceeds the configured safety limit")
            return "\n".join(str(page.get_text("text")) for page in document)
    except ExtractionError:
        raise
    except Exception as exc:  # PyMuPDF uses multiple exception types across versions.
        raise ExtractionError("PDF text extraction failed") from exc


def extract_text(data: bytes, extension: str, settings: Settings) -> str:
    """Extract text without evaluating macros, embedded files, or uploaded code."""
    if len(data) > settings.max_upload_bytes:
        raise ExtractionError("stored object exceeds the configured upload limit")
    if extension == ".pdf":
        text = _extract_pdf(data, settings)
    elif extension == ".txt":
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ExtractionError("TXT is not valid UTF-8") from exc
    elif extension == ".md":
        text = _extract_markdown(data)
    elif extension == ".docx":
        text = _extract_docx(data, settings)
    else:
        raise ExtractionError(f"unsupported extraction extension: {extension}")
    if len(text) > settings.max_text_chars:
        raise ExtractionError("extracted text exceeds the configured character limit")
    return text


def extension_from_filename(filename: str) -> str:
    return PurePosixPath(filename).suffix.lower()


__all__ = ["extract_text", "extension_from_filename"]
