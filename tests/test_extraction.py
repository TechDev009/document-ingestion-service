from io import BytesIO

import fitz
from docx import Document

from document_ingestion.extractors import extract_text


def test_text_and_markdown_extraction(settings) -> None:
    assert extract_text(b"hello\nworld", ".txt", settings) == "hello\nworld"
    assert "Heading" in extract_text(b"# Heading\n\nbody", ".md", settings)


def test_docx_and_pdf_extraction(settings) -> None:
    document = Document()
    document.add_paragraph("DOCX body")
    output = BytesIO()
    document.save(output)
    assert "DOCX body" in extract_text(output.getvalue(), ".docx", settings)

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "PDF body")
    pdf_bytes = pdf.tobytes()
    pdf.close()
    assert "PDF body" in extract_text(pdf_bytes, ".pdf", settings)
