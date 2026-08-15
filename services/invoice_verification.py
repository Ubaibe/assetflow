from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from database.enums import AssetStatus, DocumentStatus

if TYPE_CHECKING:
    from database.models import Asset, InvoiceDocument


@dataclass
class InvoiceVerificationResult:
    eligible: bool = False
    failed_checks: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    message: str | None = None


def _normalize_date(value: datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


def verify_invoice_eligibility(
    asset: Asset,
    document: InvoiceDocument | None = None,
    today: date | None = None,
) -> InvoiceVerificationResult:
    if today is None:
        today = datetime.utcnow().date()

    result = InvoiceVerificationResult()
    checks = result.checks
    reasons = result.reasons

    extraction_complete = document is not None and document.processing_status == DocumentStatus.EXTRACTED
    checks["extraction_complete"] = extraction_complete
    if not extraction_complete:
        reasons.append("Invoice extraction is not complete")

    invoice_number = bool(asset.invoice_number and asset.invoice_number.strip())
    checks["invoice_number"] = invoice_number
    if not invoice_number:
        reasons.append("Invoice number is missing")

    face_value_valid = asset.face_value is not None and asset.face_value > 0
    checks["face_value"] = face_value_valid
    if not face_value_valid:
        reasons.append("Invoice face value must be greater than zero")

    currency_valid = bool(asset.currency and asset.currency.strip() and len(asset.currency.strip()) == 3)
    checks["currency"] = currency_valid
    if not currency_valid:
        reasons.append("Currency must be a valid 3-letter code")

    issue_date_valid = asset.issue_date is not None
    checks["issue_date"] = issue_date_valid
    if not issue_date_valid:
        reasons.append("Issue date is missing")

    due_date_valid = asset.due_date is not None
    checks["due_date"] = due_date_valid
    if not due_date_valid:
        reasons.append("Due date is missing")

    issue_date_normalized = _normalize_date(asset.issue_date)
    due_date_normalized = _normalize_date(asset.due_date)

    date_order_valid = False
    if issue_date_valid and due_date_valid:
        date_order_valid = due_date_normalized > issue_date_normalized
    checks["date_order"] = date_order_valid
    if not date_order_valid and issue_date_valid and due_date_valid:
        reasons.append("Due date must be later than issue date")

    not_past_due = False
    if due_date_valid:
        not_past_due = due_date_normalized >= today
    checks["not_past_due"] = not_past_due
    if not not_past_due and due_date_valid:
        reasons.append("Invoice is past due")

    current_status = asset.status
    if hasattr(current_status, "value"):
        current_status = current_status.value
    asset_state_valid = current_status == AssetStatus.DRAFT.value
    checks["asset_state"] = asset_state_valid
    if not asset_state_valid:
        reasons.append(f"Asset must be in DRAFT state, currently {current_status}")

    result.eligible = all(checks.values())
    result.failed_checks = [name for name, passed in checks.items() if not passed]
    if result.eligible:
        result.message = "Invoice is eligible for financing"
    else:
        result.message = "Invoice is not eligible: " + "; ".join(reasons)
    return result
