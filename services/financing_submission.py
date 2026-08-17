from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from services.asset_registry_client import (
    AssetRegistryClient,
    AssetRegistryClientError,
    AssetRegistryTransactionResult,
)
from services.financing_preparation import (
    FinancingPreparationResult,
    prepare_financing,
)

if TYPE_CHECKING:
    from database.models import Asset, InvoiceDocument


@dataclass
class FinancingSubmissionResult:
    submitted: bool = False
    eligible: bool = False
    asset_id: int | None = None
    transaction_hash: str | None = None
    block_number: int | None = None
    gas_used: int | None = None
    failed_checks: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    message: str | None = None


def submit_financing(
    asset: Asset,
    document: InvoiceDocument | None = None,
    today: Any = None,
    originator_address: str | None = None,
    config: dict[str, Any] | None = None,
) -> FinancingSubmissionResult:
    preparation = prepare_financing(
        asset,
        document,
        today=today,
        originator_address=originator_address,
    )

    result = FinancingSubmissionResult(
        eligible=preparation.eligible,
        failed_checks=preparation.failed_checks,
        reasons=preparation.reasons,
        message=preparation.message,
    )

    if not preparation.eligible:
        return result

    client_config = config or {}
    client = AssetRegistryClient(client_config)
    try:
        tx_result = client.create_asset(preparation.payload)
    except AssetRegistryClientError as exc:
        result.submitted = False
        result.message = _safe_message(exc)
        return result

    result.submitted = True
    result.asset_id = tx_result.asset_id
    result.transaction_hash = tx_result.transaction_hash
    result.block_number = tx_result.block_number
    result.gas_used = tx_result.gas_used
    result.message = tx_result.message or "Asset created successfully"
    return result


def _safe_message(exc: BaseException) -> str:
    message = str(exc)
    if "PRIVATE_KEY" in message:
        return "AssetRegistry configuration error"
    if "RPC_URL" in message:
        return "AssetRegistry configuration error"
    if "ASSET_REGISTRY_ADDRESS" in message:
        return "AssetRegistry configuration error"
    if "Authorization" in message or "Bearer" in message:
        return "AssetRegistry authorization error"
    import re
    url_pattern = re.compile(r"https?://[^\s]+")
    if url_pattern.search(message):
        return "AssetRegistry configuration error"
    return message


def sanitize_message(message: str | None) -> str | None:
    if not message:
        return message
    if "PRIVATE_KEY" in message:
        return "AssetRegistry configuration error"
    if "RPC_URL" in message:
        return "AssetRegistry configuration error"
    if "ASSET_REGISTRY_ADDRESS" in message:
        return "AssetRegistry configuration error"
    if "Authorization" in message or "Bearer" in message:
        return "AssetRegistry authorization error"
    import re
    url_pattern = re.compile(r"https?://[^\s]+")
    if url_pattern.search(message):
        return "AssetRegistry configuration error"
    return message
