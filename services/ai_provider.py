from abc import ABC, abstractmethod
from typing import Any


class AIProviderError(Exception):
    pass


class AIProvider(ABC):
    @abstractmethod
    def extract_invoice_fields(
        self,
        document_bytes: bytes,
        mime_type: str,
        processing_mode: str = "text",
        extracted_text: str | None = None,
    ) -> dict[str, Any]:
        """Extract structured invoice fields from a document.

        Returns a dictionary whose contents will be validated into
        ``InvoiceExtractionResult`` by ``ExtractionService``.
        """
        raise NotImplementedError("Invoice extraction not yet implemented")


class MockAIProvider(AIProvider):
    def __init__(self, model: str) -> None:
        if not model:
            raise AIProviderError("AI_MODEL is required for MockAIProvider")
        self.model = model

    def extract_invoice_fields(
        self,
        document_bytes: bytes,
        mime_type: str,
        processing_mode: str = "text",
        extracted_text: str | None = None,
    ) -> dict[str, Any]:
        return {
            "provider": "mock",
            "model": self.model,
            "mime_type": mime_type,
            "size": len(document_bytes),
            "fields": {
                "invoice_number": "INV-001",
                "seller_name": "Mock Seller",
                "seller_address": "123 Mock Street",
                "buyer_name": "Mock Buyer",
                "buyer_address": "456 Buyer Avenue",
                "currency": "USD",
                "subtotal": "100.00",
                "tax": "10.00",
                "total_amount": "110.00",
                "issue_date": "2024-01-15",
                "due_date": "2024-02-15",
                "payment_terms": "Net 30",
                "description": "Mock invoice for testing",
                "confidence": 0.95,
            },
        }


class OpenRouterAIProvider(AIProvider):
    def __init__(self, model: str, api_key: str) -> None:
        if not api_key:
            raise AIProviderError("OPENROUTER_API_KEY is required for OpenRouter provider")
        if not model:
            raise AIProviderError("AI_MODEL is required for OpenRouter provider")
        self.model = model
        self.api_key = api_key

    def extract_invoice_fields(
        self,
        document_bytes: bytes,
        mime_type: str,
        processing_mode: str = "text",
        extracted_text: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError("OpenRouter integration pending Phase 4D")


class OpenAIProvider(AIProvider):
    def __init__(self, model: str, api_key: str) -> None:
        if not api_key:
            raise AIProviderError("OPENAI_API_KEY is required for OpenAI provider")
        if not model:
            raise AIProviderError("AI_MODEL is required for OpenAI provider")
        self.model = model
        self.api_key = api_key

    def extract_invoice_fields(
        self,
        document_bytes: bytes,
        mime_type: str,
        processing_mode: str = "text",
        extracted_text: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError("OpenAI integration pending Phase 4D")


def create_provider(config: dict[str, Any]) -> AIProvider:
    provider_name = (config.get("AI_PROVIDER") or config.get("AI_MODE", "mock")).lower()
    model = config.get("AI_MODEL")

    if not model:
        raise AIProviderError("AI_MODEL is required")

    if provider_name in ("mock", None):
        return MockAIProvider(model=model)

    if provider_name == "openrouter":
        api_key = config.get("OPENROUTER_API_KEY")
        return OpenRouterAIProvider(model=model, api_key=api_key)

    if provider_name == "openai":
        api_key = config.get("OPENAI_API_KEY")
        return OpenAIProvider(model=model, api_key=api_key)

    raise AIProviderError(f"Unsupported AI provider: {provider_name}")
