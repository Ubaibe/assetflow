from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from web3 import Web3
from web3.middleware.proof_of_authority import ExtraDataToPOAMiddleware

if TYPE_CHECKING:
    from web3.contract import Contract


class FinancingPoolClientError(Exception):
    pass


class FinancingPoolConfigurationError(FinancingPoolClientError):
    pass


class FinancingPoolTransactionError(FinancingPoolClientError):
    pass


@dataclass
class FundingStateResult:
    asset_id: int | None = None
    total_funded: int | None = None
    total_repaid: int | None = None
    exists: bool = False
    success: bool = False
    message: str | None = None


@dataclass
class FinancingPoolTransactionResult:
    transaction_hash: str | None = None
    asset_id: int | None = None
    block_number: int | None = None
    success: bool = False
    gas_used: int | None = None
    message: str | None = None
    events: dict[str, Any] = field(default_factory=dict)


class FinancingPoolClient:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._web3: Web3 | None = None
        self._contract: Contract | None = None
        self._account = None
        self._asset_registry_contract: Contract | None = None

    def _load_abi(self, artifact_name: str) -> dict[str, Any]:
        artifact_path = (
            Path(__file__).resolve().parent.parent
            / "blockchain"
            / "artifacts"
            / "contracts"
            / artifact_name
            / f"{artifact_name.split('.')[0]}.json"
        )
        if not artifact_path.exists():
            raise FinancingPoolConfigurationError(f"{artifact_name} artifact not found at {artifact_path}")
        with artifact_path.open("r", encoding="utf-8") as f:
            artifact = json.load(f)
        return artifact["abi"]

    def approve(self, token_address: str, amount: int) -> FinancingPoolTransactionResult:
        if self._web3 is None or self._contract is None:
            raise FinancingPoolConfigurationError("Client is not connected. Call connect() first.")
        if self._account is None:
            raise FinancingPoolConfigurationError("PRIVATE_KEY is required to send transactions")
        if amount <= 0:
            raise FinancingPoolTransactionError("amount must be a positive integer")

        erc20_abi = self._load_abi("MockUSDT.sol")
        token_contract = self._web3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=erc20_abi,
        )

        nonce = self._web3.eth.get_transaction_count(self._account.address)
        tx = token_contract.functions.approve(self._contract.address, amount).build_transaction({
            "chainId": self.config.get("CHAIN_ID", 31337),
            "nonce": nonce,
            "from": self._account.address,
        })

        signed_tx = self._web3.eth.account.sign_transaction(tx, self._account.key)
        tx_hash = self._web3.eth.send_raw_transaction(signed_tx.raw_transaction)

        try:
            receipt = self._web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        except Exception as exc:
            raise FinancingPoolTransactionError(f"Approval transaction failed: {exc}") from exc

        if receipt.status != 1:
            raise FinancingPoolTransactionError(f"Approval transaction reverted: {Web3.to_hex(tx_hash)}")

        return FinancingPoolTransactionResult(
            transaction_hash=Web3.to_hex(tx_hash),
            success=True,
            block_number=receipt.blockNumber,
            gas_used=receipt.gasUsed,
            message="Approval transaction successful",
        )

    def connect(self) -> None:
        rpc_url = self.config.get("RPC_URL")
        pool_address = self.config.get("FINANCING_POOL_ADDRESS")
        private_key = self.config.get("PRIVATE_KEY")

        if not rpc_url:
            raise FinancingPoolConfigurationError("RPC_URL is required")
        if not pool_address:
            raise FinancingPoolConfigurationError("FINANCING_POOL_ADDRESS is required")

        self._web3 = Web3(Web3.HTTPProvider(rpc_url))
        self._web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        try:
            connected = self._web3.is_connected()
        except Exception as exc:
            raise FinancingPoolConfigurationError("Cannot connect to RPC") from exc

        if not connected:
            raise FinancingPoolConfigurationError("Cannot connect to RPC")

        abi = self._load_abi("FinancingPool.sol")
        try:
            self._contract = self._web3.eth.contract(
                address=Web3.to_checksum_address(pool_address),
                abi=abi,
            )
        except ValueError as exc:
            raise FinancingPoolConfigurationError("Invalid FINANCING_POOL_ADDRESS") from exc

        if private_key:
            self._account = self._web3.eth.account.from_key(private_key)
        else:
            self._account = None

    def _load_asset_registry_contract(self) -> Contract:
        if self._asset_registry_contract is not None:
            return self._asset_registry_contract

        if self._web3 is None:
            raise FinancingPoolConfigurationError("Client is not connected. Call connect() first.")

        asset_registry_address = self.config.get("ASSET_REGISTRY_ADDRESS")
        if not asset_registry_address:
            raise FinancingPoolConfigurationError("ASSET_REGISTRY_ADDRESS is required for read operations")

        abi = self._load_abi("AssetRegistry.sol")
        self._asset_registry_contract = self._web3.eth.contract(
            address=Web3.to_checksum_address(asset_registry_address),
            abi=abi,
        )
        return self._asset_registry_contract

    def get_funding_state(self, asset_id: int) -> FundingStateResult:
        if self._contract is None or self._web3 is None:
            raise FinancingPoolConfigurationError("Client is not connected. Call connect() first.")

        if asset_id < 0:
            raise FinancingPoolTransactionError("asset_id must be a non-negative integer")

        try:
            total_funded, total_repaid, exists = self._contract.functions.getFundingState(asset_id).call()
        except Exception as exc:
            raise FinancingPoolTransactionError(f"Failed to fetch funding state: {exc}") from exc

        return FundingStateResult(
            asset_id=asset_id,
            total_funded=total_funded,
            total_repaid=total_repaid,
            exists=exists,
            success=True,
            message="Funding state retrieved successfully",
        )

    def get_asset_status(self, asset_id: int) -> int:
        if self._web3 is None:
            raise FinancingPoolConfigurationError("Client is not connected. Call connect() first.")

        if asset_id < 0:
            raise FinancingPoolTransactionError("asset_id must be a non-negative integer")

        contract = self._load_asset_registry_contract()
        try:
            status = contract.functions.getAssetStatus(asset_id).call()
        except Exception as exc:
            raise FinancingPoolTransactionError(f"Failed to fetch asset status: {exc}") from exc

        return int(status)

    def get_financing_target(self, asset_id: int) -> int:
        if self._web3 is None:
            raise FinancingPoolConfigurationError("Client is not connected. Call connect() first.")

        if asset_id < 0:
            raise FinancingPoolTransactionError("asset_id must be a non-negative integer")

        contract = self._load_asset_registry_contract()
        try:
            target = contract.functions.getAssetFinancingTarget(asset_id).call()
        except Exception as exc:
            raise FinancingPoolTransactionError(f"Failed to fetch financing target: {exc}") from exc

        return int(target)

    def fund(self, asset_id: int, amount: int) -> FinancingPoolTransactionResult:
        if self._contract is None or self._web3 is None:
            raise FinancingPoolConfigurationError("Client is not connected. Call connect() first.")

        if asset_id < 0:
            raise FinancingPoolTransactionError("asset_id must be a non-negative integer")
        if amount <= 0:
            raise FinancingPoolTransactionError("amount must be a positive integer")
        if self._account is None:
            raise FinancingPoolConfigurationError("PRIVATE_KEY is required to send transactions")

        nonce = self._web3.eth.get_transaction_count(self._account.address)
        tx = self._contract.functions.fund(asset_id, amount).build_transaction({
            "chainId": self.config.get("CHAIN_ID", 31337),
            "nonce": nonce,
            "from": self._account.address,
        })

        signed_tx = self._web3.eth.account.sign_transaction(tx, self._account.key)
        tx_hash = self._web3.eth.send_raw_transaction(signed_tx.raw_transaction)

        try:
            receipt = self._web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        except Exception as exc:
            raise FinancingPoolTransactionError(f"Transaction receipt failed: {exc}") from exc

        if receipt.status != 1:
            raise FinancingPoolTransactionError(f"Transaction reverted: {Web3.to_hex(tx_hash)}")

        events = self._process_fund_events(receipt)

        return FinancingPoolTransactionResult(
            transaction_hash=Web3.to_hex(tx_hash),
            asset_id=asset_id,
            block_number=receipt.blockNumber,
            success=True,
            gas_used=receipt.gasUsed,
            message="Funding transaction successful",
            events=events,
        )

    def repay(self, asset_id: int, amount: int) -> FinancingPoolTransactionResult:
        if self._contract is None or self._web3 is None:
            raise FinancingPoolConfigurationError("Client is not connected. Call connect() first.")

        if asset_id < 0:
            raise FinancingPoolTransactionError("asset_id must be a non-negative integer")
        if amount <= 0:
            raise FinancingPoolTransactionError("amount must be a positive integer")
        if self._account is None:
            raise FinancingPoolConfigurationError("PRIVATE_KEY is required to send transactions")

        nonce = self._web3.eth.get_transaction_count(self._account.address)
        tx = self._contract.functions.repay(asset_id, amount).build_transaction({
            "chainId": self.config.get("CHAIN_ID", 31337),
            "nonce": nonce,
            "from": self._account.address,
        })

        signed_tx = self._web3.eth.account.sign_transaction(tx, self._account.key)
        tx_hash = self._web3.eth.send_raw_transaction(signed_tx.raw_transaction)

        try:
            receipt = self._web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        except Exception as exc:
            raise FinancingPoolTransactionError(f"Transaction receipt failed: {exc}") from exc

        if receipt.status != 1:
            raise FinancingPoolTransactionError(f"Transaction reverted: {Web3.to_hex(tx_hash)}")

        events = self._process_repay_events(receipt)

        return FinancingPoolTransactionResult(
            transaction_hash=Web3.to_hex(tx_hash),
            asset_id=asset_id,
            block_number=receipt.blockNumber,
            success=True,
            gas_used=receipt.gasUsed,
            message="Repayment transaction successful",
            events=events,
        )

    def claim(self, asset_id: int) -> FinancingPoolTransactionResult:
        if self._contract is None or self._web3 is None:
            raise FinancingPoolConfigurationError("Client is not connected. Call connect() first.")

        if asset_id < 0:
            raise FinancingPoolTransactionError("asset_id must be a non-negative integer")
        if self._account is None:
            raise FinancingPoolConfigurationError("PRIVATE_KEY is required to send transactions")

        nonce = self._web3.eth.get_transaction_count(self._account.address)
        tx = self._contract.functions.claim(asset_id).build_transaction({
            "chainId": self.config.get("CHAIN_ID", 31337),
            "nonce": nonce,
            "from": self._account.address,
        })

        signed_tx = self._web3.eth.account.sign_transaction(tx, self._account.key)
        tx_hash = self._web3.eth.send_raw_transaction(signed_tx.raw_transaction)

        try:
            receipt = self._web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        except Exception as exc:
            raise FinancingPoolTransactionError(f"Transaction receipt failed: {exc}") from exc

        if receipt.status != 1:
            raise FinancingPoolTransactionError(f"Transaction reverted: {Web3.to_hex(tx_hash)}")

        events = self._process_claim_events(receipt)

        return FinancingPoolTransactionResult(
            transaction_hash=Web3.to_hex(tx_hash),
            asset_id=asset_id,
            block_number=receipt.blockNumber,
            success=True,
            gas_used=receipt.gasUsed,
            message="Claim transaction successful",
            events=events,
        )

    def _process_fund_events(self, receipt) -> dict[str, Any]:
        events: dict[str, Any] = {}
        try:
            asset_funded_events = self._contract.events.AssetFunded().process_receipt(receipt)
            if asset_funded_events:
                event = asset_funded_events[0]
                events["AssetFunded"] = {
                    "assetId": event["args"]["assetId"],
                    "investor": event["args"]["investor"],
                    "amount": event["args"]["amount"],
                    "logIndex": getattr(event, "logIndex", None),
                }
        except Exception:
            pass

        try:
            funding_completed_events = self._contract.events.FundingCompleted().process_receipt(receipt)
            if funding_completed_events:
                event = funding_completed_events[0]
                events["FundingCompleted"] = {
                    "assetId": event["args"]["assetId"],
                    "totalFunded": event["args"]["totalFunded"],
                    "logIndex": getattr(event, "logIndex", None),
                }
        except Exception:
            pass

        return events

    def _process_repay_events(self, receipt) -> dict[str, Any]:
        events: dict[str, Any] = {}
        try:
            repayment_events = self._contract.events.RepaymentReceived().process_receipt(receipt)
            if repayment_events:
                event = repayment_events[0]
                events["RepaymentReceived"] = {
                    "assetId": event["args"]["assetId"],
                    "payer": event["args"]["payer"],
                    "amount": event["args"]["amount"],
                    "logIndex": getattr(event, "logIndex", None),
                }
        except Exception:
            pass

        return events

    def _process_claim_events(self, receipt) -> dict[str, Any]:
        events: dict[str, Any] = {}
        try:
            claim_events = self._contract.events.ReturnsClaimed().process_receipt(receipt)
            if claim_events:
                event = claim_events[0]
                events["ReturnsClaimed"] = {
                    "assetId": event["args"]["assetId"],
                    "investor": event["args"]["investor"],
                    "amount": event["args"]["amount"],
                    "logIndex": getattr(event, "logIndex", None),
                }
        except Exception:
            pass

        return events
