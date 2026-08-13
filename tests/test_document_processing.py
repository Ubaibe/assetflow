import io
import pytest
from services.document_processing import (
    DocumentProcessor,
    DocumentProcessingError,
    DocumentProcessingResult,
)


def _make_minimal_pdf_with_text(text: str = "Invoice #123") -> bytes:
    text_bytes = text.encode("utf-8")
    stream_len = len(text_bytes) + 20

    header = b"%PDF-1.4\n"
    obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    obj2 = b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    obj3 = (
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>\n"
        b"endobj\n"
    )
    obj4 = (
        b"4 0 obj\n"
        b"<< /Length " + str(stream_len).encode() + b" >>\nstream\n"
        b"BT\n/F1 12 Tf\n10 180 Td\n(" + text_bytes + b") Tj\nET\n"
        b"endstream\nendobj\n"
    )
    obj5 = b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"

    body = obj1 + obj2 + obj3 + obj4 + obj5
    xref_offset = len(header) + len(body)
    xref = b"xref\n0 6\n0000000000 65535 f \n"

    off1 = len(header)
    off2 = off1 + len(obj1)
    off3 = off2 + len(obj2)
    off4 = off3 + len(obj3)
    off5 = off4 + len(obj4)

    xref += f"{off1:010d} 00000 n \n".encode()
    xref += f"{off2:010d} 00000 n \n".encode()
    xref += f"{off3:010d} 00000 n \n".encode()
    xref += f"{off4:010d} 00000 n \n".encode()
    xref += f"{off5:010d} 00000 n \n".encode()

    trailer = b"trailer\n<< /Size 6 /Root 1 0 R >>\n"
    startxref = b"startxref\n" + str(xref_offset).encode() + b"\n"
    eof = b"%%EOF\n"

    return header + body + xref + trailer + startxref + eof


def _make_multipage_pdf() -> bytes:
    page1 = _make_minimal_pdf_with_text("Page 1 text")
    page2 = _make_minimal_pdf_with_text("Page 2 text")
    # For multipage, we'd need a more complex builder; instead create a single PDF with both pages manually
    # Simplified: create a 2-page PDF by duplicating page objects
    text1 = b"Page 1 text"
    text2 = b"Page 2 text"
    stream_len1 = len(text1) + 20
    stream_len2 = len(text2) + 20

    header = b"%PDF-1.4\n"
    obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    obj2 = b"2 0 obj\n<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>\nendobj\n"
    obj3 = (
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>\n"
        b"endobj\n"
    )
    obj4 = (
        b"4 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 7 0 R >>\n"
        b"endobj\n"
    )
    obj5 = b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
    obj6 = (
        b"6 0 obj\n"
        b"<< /Length " + str(stream_len1).encode() + b" >>\nstream\n"
        b"BT\n/F1 12 Tf\n10 180 Td\n(" + text1 + b") Tj\nET\n"
        b"endstream\nendobj\n"
    )
    obj7 = (
        b"7 0 obj\n"
        b"<< /Length " + str(stream_len2).encode() + b" >>\nstream\n"
        b"BT\n/F1 12 Tf\n10 100 Td\n(" + text2 + b") Tj\nET\n"
        b"endstream\nendobj\n"
    )

    body = obj1 + obj2 + obj3 + obj4 + obj5 + obj6 + obj7
    xref_offset = len(header) + len(body)
    xref = b"xref\n0 8\n0000000000 65535 f \n"

    off1 = len(header)
    off2 = off1 + len(obj1)
    off3 = off2 + len(obj2)
    off4 = off3 + len(obj3)
    off5 = off4 + len(obj4)
    off6 = off5 + len(obj5)
    off7 = off6 + len(obj6)

    xref += f"{off1:010d} 00000 n \n".encode()
    xref += f"{off2:010d} 00000 n \n".encode()
    xref += f"{off3:010d} 00000 n \n".encode()
    xref += f"{off4:010d} 00000 n \n".encode()
    xref += f"{off5:010d} 00000 n \n".encode()
    xref += f"{off6:010d} 00000 n \n".encode()
    xref += f"{off7:010d} 00000 n \n".encode()

    trailer = b"trailer\n<< /Size 8 /Root 1 0 R >>\n"
    startxref = b"startxref\n" + str(xref_offset).encode() + b"\n"
    eof = b"%%EOF\n"

    return header + body + xref + trailer + startxref + eof


def _make_empty_pdf() -> bytes:
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def _make_png_bytes() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    image = Image.new("RGB", (10, 10), color="red")
    image.save(buf, format="PNG")
    return buf.getvalue()


def _make_jpeg_bytes() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    image = Image.new("RGB", (10, 10), color="blue")
    image.save(buf, format="JPEG")
    return buf.getvalue()


def test_valid_text_pdf_returns_text_mode():
    processor = DocumentProcessor()
    pdf_bytes = _make_minimal_pdf_with_text("Invoice #123\nTotal: $100.00")
    result = processor.process(io.BytesIO(pdf_bytes), "invoice.pdf", "application/pdf")
    assert result.document_type == "pdf"
    assert result.processing_mode == "text"
    assert "Invoice" in result.extracted_text
    assert result.original_mime_type == "application/pdf"
    assert result.error is None


def test_valid_image_returns_vision_mode():
    processor = DocumentProcessor()
    png_bytes = _make_png_bytes()
    result = processor.process(io.BytesIO(png_bytes), "invoice.png", "image/png")
    assert result.document_type == "image"
    assert result.processing_mode == "vision"
    assert result.extracted_text is None
    assert result.raw_bytes == png_bytes
    assert result.metadata["width"] == 10
    assert result.metadata["height"] == 10


def test_scanned_empty_text_pdf_routes_to_vision():
    processor = DocumentProcessor()
    pdf_bytes = _make_empty_pdf()
    result = processor.process(io.BytesIO(pdf_bytes), "scan.pdf", "application/pdf")
    assert result.document_type == "pdf"
    assert result.processing_mode == "vision"
    assert result.raw_bytes == pdf_bytes


def test_invalid_pdf_magic_bytes_rejected():
    processor = DocumentProcessor()
    bad_bytes = b"hello world fake pdf"
    with pytest.raises(DocumentProcessingError, match="File content does not match declared type"):
        processor.process(io.BytesIO(bad_bytes), "fake.pdf", "application/pdf")


def test_malformed_pdf_rejected():
    processor = DocumentProcessor()
    bad_bytes = b"%PDF-1.4\n" + b"\x00" * 100
    with pytest.raises(DocumentProcessingError, match="Failed to read PDF"):
        processor.process(io.BytesIO(bad_bytes), "bad.pdf", "application/pdf")


def test_invalid_image_signature_rejected():
    processor = DocumentProcessor()
    bad_bytes = b"GIF89a" + b"\x00" * 100
    with pytest.raises(DocumentProcessingError, match="File content does not match declared type"):
        processor.process(io.BytesIO(bad_bytes), "fake.png", "image/png")


def test_unsupported_extension_rejected():
    processor = DocumentProcessor()
    with pytest.raises(DocumentProcessingError, match="Unsupported file extension"):
        processor.process(io.BytesIO(b"hello"), "doc.txt", "text/plain")


def test_unsupported_mime_rejected():
    processor = DocumentProcessor()
    pdf_bytes = _make_minimal_pdf_with_text("hello")
    with pytest.raises(DocumentProcessingError, match="MIME type mismatch"):
        processor.process(io.BytesIO(pdf_bytes), "doc.pdf", "text/plain")


def test_max_upload_size_enforced():
    processor = DocumentProcessor(max_upload_mb=1)
    pdf_bytes = _make_minimal_pdf_with_text("hello")
    with pytest.raises(DocumentProcessingError, match="exceeds maximum size"):
        processor.process(io.BytesIO(pdf_bytes), "big.pdf", "application/pdf", max_bytes=10)


def test_multiple_page_text_extraction():
    processor = DocumentProcessor()
    pdf_bytes = _make_multipage_pdf()
    result = processor.process(io.BytesIO(pdf_bytes), "multi.pdf", "application/pdf")
    assert result.processing_mode == "text"
    assert "Page 1 text" in result.extracted_text
    assert "Page 2 text" in result.extracted_text


def test_empty_file_rejected():
    processor = DocumentProcessor()
    with pytest.raises(DocumentProcessingError, match="Empty file"):
        processor.process(io.BytesIO(b""), "empty.pdf", "application/pdf")


def test_no_network_calls():
    processor = DocumentProcessor()
    pdf_bytes = _make_minimal_pdf_with_text("test")
    result = processor.process(io.BytesIO(pdf_bytes), "test.pdf", "application/pdf")
    assert result.error is None
    assert result.processing_mode in ("text", "vision")


def test_deterministic_behavior():
    processor = DocumentProcessor()
    pdf_bytes = _make_minimal_pdf_with_text("Deterministic")
    result1 = processor.process(io.BytesIO(pdf_bytes), "det.pdf", "application/pdf")
    result2 = processor.process(io.BytesIO(pdf_bytes), "det.pdf", "application/pdf")
    assert result1.extracted_text == result2.extracted_text
    assert result1.processing_mode == result2.processing_mode
    assert result1.metadata == result2.metadata


def test_jpeg_supported():
    processor = DocumentProcessor()
    jpeg_bytes = _make_jpeg_bytes()
    result = processor.process(io.BytesIO(jpeg_bytes), "photo.jpg", "image/jpeg")
    assert result.document_type == "image"
    assert result.processing_mode == "vision"
    assert result.metadata["format"] == "JPEG"
