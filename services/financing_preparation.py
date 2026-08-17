from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from database.enums import AssetStatus
from services.invoice_verification import verify_invoice_eligibility, InvoiceVerificationResult
from services.token_decimals import get_token_decimals, to_base_units

if TYPE_CHECKING:
    from database.models import Asset, InvoiceDocument


@dataclass
class FinancingPreparationResult:
    eligible: bool = False
    asset_id: int | None = None
    invoice_number: str | None = None
    face_value: Decimal | None = None
    currency: str | None = None
    issue_date: datetime | None = None
    due_date: datetime | None = None
    asset_hash: str | None = None
    financing_target: Decimal | None = None
    failed_checks: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    payload: dict | None = None
    message: str | None = None


def _to_timestamp(value: datetime | None) -> int | None:
    if value is None:
        return None
    return int(value.timestamp())


def _to_bytes32_hex(hex_str: str) -> str:
    clean = hex_str.strip().lower()
    if clean.startswith("0x"):
        clean = clean[2:]
    if len(clean) < 64:
        clean = clean.rjust(64, "0")
    return "0x" + clean[:64]


def prepare_financing(
    asset: Asset,
    document: InvoiceDocument | None = None,
    today: datetime | None = None,
    originator_address: str | None = None,
    token_decimals: int | None = None,
) -> FinancingPreparationResult:
    if today is None:
        today = datetime.utcnow()

    decimals = token_decimals if token_decimals is not None else get_token_decimals()

    verification = verify_invoice_eligibility(
        asset,
        document,
        today=today.date() if today else None,
    )

    result = FinancingPreparationResult(
        eligible=verification.eligible,
        asset_id=asset.id,
        invoice_number=asset.invoice_number,
        face_value=asset.face_value,
        currency=asset.currency,
        issue_date=asset.issue_date,
        due_date=asset.due_date,
        asset_hash=asset.asset_hash,
        financing_target=asset.financing_target,
        failed_checks=verification.failed_checks,
        reasons=verification.reasons,
    )

    if not verification.eligible:
        result.message = verification.message
        return result

    face_value_wei = to_base_units(asset.face_value, decimals)
    financing_target_wei = to_base_units(asset.financing_target, decimals)
    maturity_timestamp = _to_timestamp(asset.due_date)

    payload = {
        "assetHash": asset.asset_hash,
        "assetHashBytes32": _to_bytes32_hex(asset.asset_hash),
        "originator": originator_address,
        "faceValue": face_value_wei,
        "financingTarget": financing_target_wei,
        "maturityTimestamp": maturity_timestamp,
        "riskScore": asset.risk_score if asset.risk_score is not None else 0,
    }

    result.payload = payload
    result.message = "Invoice is eligible for financing registration"
    return result
