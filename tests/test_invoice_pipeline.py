import io
from decimal import Decimal
from unittest.mock import patch, MagicMock

import pytest
import requests

from services.invoice_pipeline import InvoicePipelineError, extract_invoice
from services.ai_extraction import InvoiceExtractionResult
from services.ai_provider import AIProviderError, MockAIProvider, AgentRouterAIProvider
from services.document_processing import DocumentProcessor, DocumentProcessingError


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


def _make_png_bytes() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    image = Image.new("RGB", (10, 10), color="red")
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_text_pdf_successful_mock_extraction():
    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC\nTotal: $100.00")
    config = {"AI_PROVIDER": "mock", "AI_MODEL": "mock-model"}
    result = extract_invoice(
        config,
        io.BytesIO(pdf_bytes),
        "invoice.pdf",
        "application/pdf",
    )
    assert isinstance(result, InvoiceExtractionResult)
    assert result.provider == "mock"
    assert result.invoice_number == "INV-001"
    assert result.currency == "USD"
    assert result.total_amount == Decimal("110.00")
    assert result.confidence == 0.95


def test_image_vision_successful_mock_extraction():
    png_bytes = _make_png_bytes()
    config = {"AI_PROVIDER": "mock", "AI_MODEL": "mock-model"}
    result = extract_invoice(
        config,
        io.BytesIO(png_bytes),
        "invoice.png",
        "image/png",
    )
    assert isinstance(result, InvoiceExtractionResult)
    assert result.provider == "mock"
    assert result.invoice_number == "INV-001"


def test_document_processing_failure():
    config = {"AI_PROVIDER": "mock", "AI_MODEL": "mock-model"}
    with pytest.raises(InvoicePipelineError, match="Document processing failed"):
        extract_invoice(
            config,
            io.BytesIO(b"not a real file"),
            "invoice.pdf",
            "application/pdf",
        )


def test_unsupported_provider_configuration():
    pdf_bytes = _make_minimal_pdf_with_text("Invoice")
    config = {"AI_PROVIDER": "anthropic", "AI_MODEL": "claude-3"}
    with pytest.raises(InvoicePipelineError, match="AI provider configuration failed"):
        extract_invoice(
            config,
            io.BytesIO(pdf_bytes),
            "invoice.pdf",
            "application/pdf",
        )


def test_mock_mode_makes_no_network_calls():
    pdf_bytes = _make_minimal_pdf_with_text("Invoice")
    config = {"AI_PROVIDER": "mock", "AI_MODEL": "mock-model"}
    with patch("services.ai_provider.requests.post") as mock_post:
        result = extract_invoice(
            config,
            io.BytesIO(pdf_bytes),
            "invoice.pdf",
            "application/pdf",
        )
    assert result.provider == "mock"
    mock_post.assert_not_called()


def test_agentrouter_success_using_mocked_http():
    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC\nTotal: $500.00")
    config = {
        "AI_PROVIDER": "agentrouter",
        "AI_MODEL": "gpt-4o",
        "AGENTROUTER_API_KEY": "sk-test",
        "AGENTROUTER_BASE_URL": "https://api.agentrouter.com/v1",
    }
    mock_response = {
        "choices": [
            {
                "message": {
                    "content": '{"invoice_number": "INV-999", "amount": "500.00", "currency": "USD", "confidence": 0.92}'
                }
            }
        ]
    }
    with patch("services.ai_provider.requests.post") as mock_post:
        mock_post.return_value.json.return_value = mock_response
        mock_post.return_value.raise_for_status.return_value = None
        result = extract_invoice(
            config,
            io.BytesIO(pdf_bytes),
            "invoice.pdf",
            "application/pdf",
        )
    assert isinstance(result, InvoiceExtractionResult)
    assert result.invoice_number == "INV-999"
    assert result.amount == Decimal("500.00")
    assert result.currency == "USD"
    assert result.confidence == 0.92
    assert result.provider == "agentrouter"


def test_agentrouter_network_failure():
    pdf_bytes = _make_minimal_pdf_with_text("Invoice")
    config = {
        "AI_PROVIDER": "agentrouter",
        "AI_MODEL": "gpt-4o",
        "AGENTROUTER_API_KEY": "sk-test",
        "AGENTROUTER_BASE_URL": "https://api.agentrouter.com/v1",
    }
    with patch("services.ai_provider.requests.post") as mock_post:
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection error")
        with pytest.raises(InvoicePipelineError, match="AI extraction failed"):
            extract_invoice(
                config,
                io.BytesIO(pdf_bytes),
                "invoice.pdf",
                "application/pdf",
            )


def test_agentrouter_malformed_response():
    pdf_bytes = _make_minimal_pdf_with_text("Invoice")
    config = {
        "AI_PROVIDER": "agentrouter",
        "AI_MODEL": "gpt-4o",
        "AGENTROUTER_API_KEY": "sk-test",
        "AGENTROUTER_BASE_URL": "https://api.agentrouter.com/v1",
    }
    with patch("services.ai_provider.requests.post") as mock_post:
        mock_post.return_value.json.return_value = {"choices": []}
        mock_post.return_value.raise_for_status.return_value = None
        with pytest.raises(InvoicePipelineError, match="AI extraction failed"):
            extract_invoice(
                config,
                io.BytesIO(pdf_bytes),
                "invoice.pdf",
                "application/pdf",
            )


def test_api_key_not_leaked_in_errors():
    pdf_bytes = _make_minimal_pdf_with_text("Invoice")
    config = {
        "AI_PROVIDER": "agentrouter",
        "AI_MODEL": "gpt-4o",
        "AGENTROUTER_API_KEY": "super-secret-key",
        "AGENTROUTER_BASE_URL": "https://api.agentrouter.com/v1",
    }
    with patch("services.ai_provider.requests.post") as mock_post:
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection error")
        try:
            extract_invoice(
                config,
                io.BytesIO(pdf_bytes),
                "invoice.pdf",
                "application/pdf",
            )
        except InvoicePipelineError as exc:
            assert "super-secret-key" not in str(exc)


def test_invalid_extracted_fields_raise():
    pdf_bytes = _make_minimal_pdf_with_text("Invoice")
    config = {
        "AI_PROVIDER": "agentrouter",
        "AI_MODEL": "gpt-4o",
        "AGENTROUTER_API_KEY": "sk-test",
        "AGENTROUTER_BASE_URL": "https://api.agentrouter.com/v1",
    }
    mock_response = {
        "choices": [
            {
                "message": {
                    "content": '{"amount": "not-a-number", "currency": "123"}'
                }
            }
        ]
    }
    with patch("services.ai_provider.requests.post") as mock_post:
        mock_post.return_value.json.return_value = mock_response
        mock_post.return_value.raise_for_status.return_value = None
        with pytest.raises(InvoicePipelineError, match="AI extraction failed"):
            extract_invoice(
                config,
                io.BytesIO(pdf_bytes),
                "invoice.pdf",
                "application/pdf",
            )
