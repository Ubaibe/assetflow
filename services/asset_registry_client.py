from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from web3 import Web3

if TYPE_CHECKING:
    from web3.contract import Contract


class AssetRegistryClientError(Exception):
    pass


class AssetRegistryConfigurationError(AssetRegistryClientError):
    pass


class AssetRegistryTransactionError(AssetRegistryClientError):
    pass


@dataclass
class AssetRegistryTransactionResult:
    transaction_hash: str | None = None
    asset_id: int | None = None
    block_number: int | None = None
    success: bool = False
    gas_used: int | None = None
    message: str | None = None


class AssetRegistryClient:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._web3: Web3 | None = None
        self._contract: Contract | None = None
        self._account = None

    def _load_abi(self) -> dict[str, Any]:
        artifact_path = (
            Path(__file__).resolve().parent.parent
            / "blockchain"
            / "artifacts"
            / "contracts"
            / "AssetRegistry.sol"
            / "AssetRegistry.json"
        )
        if not artifact_path.exists():
            raise AssetRegistryConfigurationError(f"AssetRegistry artifact not found at {artifact_path}")
        with artifact_path.open("r", encoding="utf-8") as f:
            artifact = json.load(f)
        return artifact["abi"]

    def connect(self) -> None:
        rpc_url = self.config.get("RPC_URL")
        contract_address = self.config.get("ASSET_REGISTRY_ADDRESS")
        private_key = self.config.get("PRIVATE_KEY")

        if not rpc_url:
            raise AssetRegistryConfigurationError("RPC_URL is required")
        if not contract_address:
            raise AssetRegistryConfigurationError("ASSET_REGISTRY_ADDRESS is required")

        self._web3 = Web3(Web3.HTTPProvider(rpc_url))

        if not self._web3.is_connected():
            raise AssetRegistryConfigurationError(f"Cannot connect to RPC at {rpc_url}")

        abi = self._load_abi()
        self._contract = self._web3.eth.contract(
            address=Web3.to_checksum_address(contract_address),
            abi=abi,
        )

        if private_key:
            self._account = self._web3.eth.account.from_key(private_key)
        else:
            self._account = None

    def create_asset(self, payload: dict[str, Any]) -> AssetRegistryTransactionResult:
        if self._contract is None or self._web3 is None:
            raise AssetRegistryConfigurationError("Client is not connected. Call connect() first.")

        required_fields = [
            "assetHashBytes32",
            "originator",
            "faceValue",
            "financingTarget",
            "maturityTimestamp",
            "riskScore",
        ]
        missing = [field for field in required_fields if field not in payload]
        if missing:
            raise AssetRegistryTransactionError(f"Missing payload fields: {', '.join(missing)}")

        originator = Web3.to_checksum_address(payload["originator"])
        face_value = payload["faceValue"]
        financing_target = payload["financingTarget"]
        maturity_timestamp = payload["maturityTimestamp"]
        risk_score = payload["riskScore"]

        if self._account is None:
            raise AssetRegistryConfigurationError("PRIVATE_KEY is required to send transactions")

        nonce = self._web3.eth.get_transaction_count(self._account.address)
        tx = self._contract.functions.createAsset(
            payload["assetHashBytes32"],
            originator,
            face_value,
            financing_target,
            maturity_timestamp,
            risk_score,
        ).build_transaction({
            "chainId": self.config.get("CHAIN_ID", 31337),
            "nonce": nonce,
            "from": self._account.address,
        })

        signed_tx = self._web3.eth.account.sign_transaction(tx, self._account.key)
        tx_hash = self._web3.eth.send_raw_transaction(signed_tx.raw_transaction)

        try:
            receipt = self._web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        except Exception as exc:
            raise AssetRegistryTransactionError(f"Transaction receipt failed: {exc}") from exc

        if receipt.status != 1:
            raise AssetRegistryTransactionError(f"Transaction reverted: {Web3.to_hex(tx_hash)}")

        asset_id = None
        try:
            event = self._contract.events.AssetCreated().process_receipt(receipt)
            if not event:
                raise AssetRegistryTransactionError("AssetCreated event not found in receipt")
            asset_id = event[0]["args"]["assetId"]
        except AssetRegistryTransactionError:
            raise
        except Exception as exc:
            raise AssetRegistryTransactionError(f"Failed to decode AssetCreated event: {exc}") from exc

        result = AssetRegistryTransactionResult(
            transaction_hash=Web3.to_hex(tx_hash),
            asset_id=asset_id,
            block_number=receipt.block_number,
            success=True,
            gas_used=receipt.gas_used,
            message="Asset created successfully",
        )
        return result
