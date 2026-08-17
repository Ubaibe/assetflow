from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from services.financing_pool_client import (
    FinancingPoolClient,
    FinancingPoolClientError,
    FinancingPoolConfigurationError,
    FinancingPoolTransactionError,
    FundingStateResult,
)

if TYPE_CHECKING:
    from services.financing_pool_client import FinancingPoolTransactionResult


class FundingServiceError(Exception):
    pass


class FundingValidationError(FundingServiceError):
    pass


@dataclass
class FundingResult:
    funded: bool = False
    asset_id: int | None = None
    requested_amount: int | None = None
    financing_target: int | None = None
    total_funded_before: int | None = None
    remaining_funding: int | None = None
    asset_status: int | None = None
    transaction_hash: str | None = None
    block_number: int | None = None
    gas_used: int | None = None
    events: dict[str, Any] = field(default_factory=dict)
    message: str | None = None


def prepare_and_fund(asset_id: int, amount: int, config: dict[str, Any]) -> FundingResult:
    if asset_id < 0:
        raise FundingValidationError("asset_id must be a non-negative integer")
    if amount <= 0:
        raise FundingValidationError("amount must be a positive integer")

    client = FinancingPoolClient(config)
    try:
        client.connect()
    except FinancingPoolConfigurationError as exc:
        safe_msg = _sanitize(str(exc))
        return FundingResult(
            funded=False,
            asset_id=asset_id,
            requested_amount=amount,
            message=f"Financing pool configuration error: {safe_msg}",
        )

    try:
        asset_status = client.get_asset_status(asset_id)
    except FinancingPoolClientError as exc:
        safe_msg = _sanitize(str(exc))
        return FundingResult(
            funded=False,
            asset_id=asset_id,
            requested_amount=amount,
            message=f"Failed to fetch asset status: {safe_msg}",
        )

    try:
        financing_target = client.get_financing_target(asset_id)
        funding_state = client.get_funding_state(asset_id)
    except FinancingPoolClientError as exc:
        safe_msg = _sanitize(str(exc))
        return FundingResult(
            funded=False,
            asset_id=asset_id,
            requested_amount=amount,
            asset_status=asset_status,
            message=f"Failed to fetch funding data: {safe_msg}",
        )

    total_funded = funding_state.total_funded or 0
    exists = funding_state.exists

    if not exists:
        return FundingResult(
            funded=False,
            asset_id=asset_id,
            requested_amount=amount,
            asset_status=asset_status,
            financing_target=financing_target,
            total_funded_before=total_funded,
            remaining_funding=0,
            message="Asset does not exist on-chain",
        )

    if asset_status not in (0, 1):
        return FundingResult(
            funded=False,
            asset_id=asset_id,
            requested_amount=amount,
            asset_status=asset_status,
            financing_target=financing_target,
            total_funded_before=total_funded,
            remaining_funding=financing_target - total_funded,
            message=f"Asset status {asset_status} is not fundable; expected LISTED (0) or PARTIALLY_FUNDED (1)",
        )

    remaining_funding = financing_target - total_funded
    if remaining_funding < 0:
        return FundingResult(
            funded=False,
            asset_id=asset_id,
            requested_amount=amount,
            asset_status=asset_status,
            financing_target=financing_target,
            total_funded_before=total_funded,
            remaining_funding=remaining_funding,
            message="Inconsistent on-chain state: total funded exceeds financing target",
        )

    if amount > remaining_funding:
        return FundingResult(
            funded=False,
            asset_id=asset_id,
            requested_amount=amount,
            asset_status=asset_status,
            financing_target=financing_target,
            total_funded_before=total_funded,
            remaining_funding=remaining_funding,
            message=f"Requested amount exceeds remaining funding capacity of {remaining_funding}",
        )

    try:
        tx_result = client.fund(asset_id, amount)
    except FinancingPoolConfigurationError as exc:
        safe_msg = _sanitize(str(exc))
        return FundingResult(
            funded=False,
            asset_id=asset_id,
            requested_amount=amount,
            asset_status=asset_status,
            financing_target=financing_target,
            total_funded_before=total_funded,
            remaining_funding=remaining_funding,
            message=f"Financing pool configuration error: {safe_msg}",
        )
    except FinancingPoolTransactionError as exc:
        safe_msg = _sanitize(str(exc))
        return FundingResult(
            funded=False,
            asset_id=asset_id,
            requested_amount=amount,
            asset_status=asset_status,
            financing_target=financing_target,
            total_funded_before=total_funded,
            remaining_funding=remaining_funding,
            message=f"Funding transaction failed: {safe_msg}",
        )

    return FundingResult(
        funded=True,
        asset_id=asset_id,
        requested_amount=amount,
        asset_status=asset_status,
        financing_target=financing_target,
        total_funded_before=total_funded,
        remaining_funding=remaining_funding - amount,
        transaction_hash=tx_result.transaction_hash,
        block_number=tx_result.block_number,
        gas_used=tx_result.gas_used,
        events=tx_result.events,
        message="Funding transaction successful",
    )


def _sanitize(message: str) -> str:
    if "PRIVATE_KEY" in message:
        return "Financing pool configuration error"
    if "RPC_URL" in message:
        return "Financing pool configuration error"
    if "FINANCING_POOL_ADDRESS" in message:
        return "Financing pool configuration error"
    if "ASSET_REGISTRY_ADDRESS" in message:
        return "Financing pool configuration error"
    if "Authorization" in message or "Bearer" in message:
        return "Financing pool authorization error"
    import re
    url_pattern = re.compile(r"https?://[^\s]+")
    if url_pattern.search(message):
        return "Financing pool configuration error"
    return message
