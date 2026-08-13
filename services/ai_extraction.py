from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Optional, Union

from pydantic import BaseModel, field_validator, model_validator

if TYPE_CHECKING:
    from services.ai_provider import AIProvider

from services.ai_provider import AIProviderError


class InvoiceExtractionResult(BaseModel):
    invoice_number: Optional[str] = None
    seller_name: Optional[str] = None
    seller_address: Optional[str] = None
    buyer_name: Optional[str] = None
    buyer_address: Optional[str] = None
    currency: Optional[str] = None
    subtotal: Optional[Decimal] = None
    tax: Optional[Decimal] = None
    total_amount: Optional[Decimal] = None
    issue_date: Optional[date] = None
    due_date: Optional[date] = None
    payment_terms: Optional[str] = None
    description: Optional[str] = None
    confidence: Optional[float] = None
    raw_text: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip().upper()
        if len(v) != 3 or not v.isalpha():
            raise ValueError(f"Invalid currency code: {v}")
        return v

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {v}")
        return v

    @field_validator("subtotal", "tax", "total_amount", mode="before")
    @classmethod
    def validate_monetary(cls, v: Optional[Union[Decimal, str, float]]) -> Optional[Decimal]:
        if v is None:
            return v
        if isinstance(v, Decimal):
            if v < 0:
                raise ValueError(f"Monetary value cannot be negative: {v}")
            return v
        try:
            d = Decimal(str(v))
            if d < 0:
                raise ValueError(f"Monetary value cannot be negative: {v}")
            return d
        except Exception as exc:
            raise ValueError(f"Invalid monetary value: {v}") from exc

    @model_validator(mode="after")
    def validate_total_against_subtotal_and_tax(self) -> InvoiceExtractionResult:
        subtotal = self.subtotal
        tax = self.tax
        total = self.total_amount

        if total is None:
            return self

        if subtotal is not None and tax is not None:
            expected = subtotal + tax
            if abs(expected - total) > Decimal("0.02"):
                raise ValueError(
                    f"total_amount {total} does not match subtotal {subtotal} + tax {tax}"
                )
        return self


class ExtractionService:
    def __init__(self, provider: AIProvider) -> None:
        self.provider = provider

    def extract(self, document_result) -> InvoiceExtractionResult:
        if document_result.processing_mode == "text":
            return self._extract_from_text(document_result)
        return self._extract_from_vision(document_result)

    def _extract_from_text(self, document_result) -> InvoiceExtractionResult:
        raw_result = self.provider.extract_invoice_fields(
            document_bytes=document_result.extracted_text.encode("utf-8"),
            mime_type=document_result.original_mime_type,
            processing_mode="text",
            extracted_text=document_result.extracted_text,
        )
        return self._validate_result(raw_result, document_result)

    def _extract_from_vision(self, document_result) -> InvoiceExtractionResult:
        raw_result = self.provider.extract_invoice_fields(
            document_bytes=document_result.raw_bytes or b"",
            mime_type=document_result.original_mime_type,
            processing_mode="vision",
            extracted_text=document_result.extracted_text,
        )
        return self._validate_result(raw_result, document_result)

    def _validate_result(self, raw_result: dict, document_result) -> InvoiceExtractionResult:
        if not isinstance(raw_result, dict):
            raise AIProviderError("Extraction result must be a dictionary")

        data = {
            "raw_text": document_result.extracted_text,
            "provider": raw_result.get("provider"),
            "model": raw_result.get("model"),
        }
        fields = raw_result.get("fields", raw_result)
        if isinstance(fields, dict):
            data.update(fields)

        try:
            return InvoiceExtractionResult(**data)
        except Exception as exc:
            raise AIProviderError(f"Invalid extraction result: {exc}") from exc
