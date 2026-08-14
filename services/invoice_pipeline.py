from __future__ import annotations

from typing import Any, BinaryIO, Optional

from services.ai_extraction import ExtractionService, InvoiceExtractionResult
from services.ai_provider import AIProviderError, create_provider
from services.document_processing import DocumentProcessor, DocumentProcessingError


class InvoicePipelineError(Exception):
    pass


def extract_invoice(
    config: dict[str, Any],
    file_stream: BinaryIO,
    filename: str,
    content_type: str,
    max_bytes: Optional[int] = None,
) -> InvoiceExtractionResult:
    processor = DocumentProcessor()
    try:
        doc_result = processor.process(file_stream, filename, content_type, max_bytes)
    except DocumentProcessingError as exc:
        raise InvoicePipelineError(f"Document processing failed: {exc}") from exc

    try:
        provider = create_provider(config)
    except AIProviderError as exc:
        raise InvoicePipelineError(f"AI provider configuration failed: {exc}") from exc

    service = ExtractionService(provider)
    try:
        return service.extract(doc_result)
    except AIProviderError as exc:
        raise InvoicePipelineError(f"AI extraction failed: {exc}") from exc
