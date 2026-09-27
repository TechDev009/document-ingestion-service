import hashlib

import pytest

from document_ingestion.chunking import chunk_text, normalize_text


def test_normalization_is_stable() -> None:
    assert normalize_text("  A\r\n\r\n\r\nB\x00  ") == "A\n\nB"


def test_chunking_is_deterministic_and_hashed() -> None:
    text = "one two three four five six seven eight nine ten"
    first = chunk_text(text, max_chars=18, overlap=3)
    second = chunk_text(text, max_chars=18, overlap=3)
    assert first == second
    assert [chunk.position for chunk in first] == list(range(len(first)))
    assert all(len(chunk.text) <= 18 for chunk in first)
    assert all(chunk.sha256 == hashlib.sha256(chunk.text.encode()).hexdigest() for chunk in first)


def test_chunking_rejects_invalid_bounds() -> None:
    with pytest.raises(ValueError):
        chunk_text("text", max_chars=0)
    with pytest.raises(ValueError):
        chunk_text("text", max_chars=5, overlap=5)
    assert chunk_text("  \n") == []
