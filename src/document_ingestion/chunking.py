import hashlib
import re
import unicodedata

from document_ingestion.domain.models import TextChunk

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HORIZONTAL_WHITESPACE = re.compile(r"[ \t]+")


def normalize_text(text: str) -> str:
    """Make extracted text stable across platforms and parser versions."""
    normalized = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    normalized = _CONTROL_CHARS.sub("", normalized)
    normalized = _HORIZONTAL_WHITESPACE.sub(" ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return "\n".join(line.rstrip() for line in normalized.strip().split("\n"))


def chunk_text(text: str, max_chars: int = 1_200, overlap: int = 120) -> list[TextChunk]:
    """Split text deterministically at word boundaries with bounded overlap."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap < 0 or overlap >= max_chars:
        raise ValueError("overlap must be non-negative and smaller than max_chars")
    normalized = normalize_text(text)
    if not normalized:
        return []

    chunks: list[TextChunk] = []
    start = 0
    while start < len(normalized):
        candidate_end = min(start + max_chars, len(normalized))
        end = candidate_end
        if candidate_end < len(normalized):
            boundary = normalized.rfind(" ", start + max_chars // 2, candidate_end)
            if boundary > start:
                end = boundary
        piece = normalized[start:end].strip()
        if piece:
            chunks.append(
                TextChunk(
                    position=len(chunks),
                    text=piece,
                    sha256=hashlib.sha256(piece.encode("utf-8")).hexdigest(),
                )
            )
        if end >= len(normalized):
            break
        next_start = max(start + 1, end - overlap)
        while next_start < len(normalized) and normalized[next_start].isspace():
            next_start += 1
        start = next_start
    return chunks
