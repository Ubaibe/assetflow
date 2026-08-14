from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from database.models import Asset, AIAnalysis
from services.ai_extraction import InvoiceExtractionResult


def _to_datetime(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime(value.year, value.month, value.day)


def _safe_raw_result(extraction_result: InvoiceExtractionResult) -> str | None:
    data = {
        "invoice_number": extraction_result.invoice_number,
        "seller_name": extraction_result.seller_name,
        "seller_address": extraction_result.seller_address,
        "buyer_name": extraction_result.buyer_name,
        "buyer_address": extraction_result.buyer_address,
        "amount": str(extraction_result.amount) if extraction_result.amount is not None else None,
        "currency": extraction_result.currency,
        "subtotal": str(extraction_result.subtotal) if extraction_result.subtotal is not None else None,
        "tax": str(extraction_result.tax) if extraction_result.tax is not None else None,
        "total_amount": str(extraction_result.total_amount) if extraction_result.total_amount is not None else None,
        "issue_date": extraction_result.issue_date.isoformat() if extraction_result.issue_date else None,
        "due_date": extraction_result.due_date.isoformat() if extraction_result.due_date else None,
        "payment_terms": extraction_result.payment_terms,
        "description": extraction_result.description,
        "confidence": extraction_result.confidence,
    }
    text = str(data)
    return text[:255] if len(text) > 255 else text


def persist_extraction(
    session: Session,
    asset_id: int,
    extraction_result: InvoiceExtractionResult,
    processing_mode: str | None = None,
) -> None:
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise ValueError(f"Asset {asset_id} not found")

    if extraction_result.invoice_number is not None:
        asset.invoice_number = extraction_result.invoice_number
    if extraction_result.amount is not None:
        asset.face_value = extraction_result.amount
    if extraction_result.currency is not None:
        asset.currency = extraction_result.currency
    if extraction_result.issue_date is not None:
        asset.issue_date = _to_datetime(extraction_result.issue_date)
    if extraction_result.due_date is not None:
        asset.due_date = _to_datetime(extraction_result.due_date)

    analysis = AIAnalysis(
        asset_id=asset_id,
        provider=extraction_result.provider,
        model=extraction_result.model,
        confidence=extraction_result.confidence,
        extraction_output=processing_mode,
        raw_result=_safe_raw_result(extraction_result),
    )
    session.add(analysis)
