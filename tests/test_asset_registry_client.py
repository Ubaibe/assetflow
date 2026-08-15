from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from web3 import Web3

from services.asset_registry_client import (
    AssetRegistryClient,
    AssetRegistryClientError,
    AssetRegistryConfigurationError,
    AssetRegistryTransactionError,
    AssetRegistryTransactionResult,
)


def _build_mock_client():
    mock_web3 = MagicMock()
    mock_web3.is_connected.return_value = True
    mock_account = MagicMock()
    mock_account.address = "0x" + "a" * 40
    mock_web3.eth.account.from_key.return_value = mock_account
    mock_web3.eth.get_transaction_count.return_value = 0

    mock_contract = MagicMock()
    mock_event = MagicMock()
    mock_event.process_receipt.return_value = [{"args": {"assetId": 42}}]
    mock_contract.events.AssetCreated.return_value = mock_event

    mock_tx = {"from": mock_account.address}
    mock_contract.functions.createAsset.return_value.build_transaction.return_value = mock_tx

    mock_receipt = MagicMock()
    mock_receipt.status = 1
    mock_receipt.block_number = 12345
    mock_receipt.gas_used = 21000
    mock_web3.eth.wait_for_transaction_receipt.return_value = mock_receipt
    mock_web3.eth.send_raw_transaction.return_value = b"\x00" * 32

    with patch("services.asset_registry_client.Web3") as MockWeb3:
        MockWeb3.HTTPProvider.return_value = MagicMock()
        MockWeb3.to_checksum_address.side_effect = lambda x: x
        MockWeb3.return_value = mock_web3

        with patch.object(Path, "exists", return_value=True):
            with patch("builtins.open", MagicMock()):
                with patch("json.load", return_value={"abi": []}):
                    client = AssetRegistryClient({
                        "RPC_URL": "http://localhost:8545",
                        "ASSET_REGISTRY_ADDRESS": "0x" + "b" * 40,
                        "PRIVATE_KEY": "0x" + "c" * 64,
                        "CHAIN_ID": 31337,
                    })
                    client._web3 = mock_web3
                    client._contract = mock_contract
                    client._account = mock_account
                    return client, mock_web3, mock_contract, mock_account, mock_receipt


def test_client_configuration():
    client, _, _, _, _ = _build_mock_client()
    assert client.config["RPC_URL"] == "http://localhost:8545"
    assert client.config["ASSET_REGISTRY_ADDRESS"] == "0x" + "b" * 40


def test_missing_rpc_configuration():
    with pytest.raises(AssetRegistryConfigurationError, match="RPC_URL is required"):
        AssetRegistryClient({}).connect()


def test_missing_contract_address():
    with pytest.raises(AssetRegistryConfigurationError, match="ASSET_REGISTRY_ADDRESS is required"):
        AssetRegistryClient({"RPC_URL": "http://localhost:8545"}).connect()


def test_missing_signer_configuration():
    with patch("services.asset_registry_client.Web3"):
        with patch.object(Path, "exists", return_value=True):
            with patch("builtins.open", MagicMock()):
                with patch("json.load", return_value={"abi": []}):
                    client = AssetRegistryClient({
                        "RPC_URL": "http://localhost:8545",
                        "ASSET_REGISTRY_ADDRESS": "0x" + "b" * 40,
                    })
                    client._web3 = MagicMock()
                    client._web3.is_connected.return_value = True
                    client._contract = MagicMock()
                    with pytest.raises(AssetRegistryConfigurationError, match="PRIVATE_KEY is required"):
                        client.create_asset({
                            "assetHashBytes32": "0x" + "a" * 64,
                            "originator": "0x" + "b" * 40,
                            "faceValue": 100,
                            "financingTarget": 80,
                            "maturityTimestamp": 1234567890,
                            "riskScore": 50,
                        })


def test_successful_contract_initialization():
    with patch("services.asset_registry_client.Web3") as MockWeb3:
        mock_web3 = MagicMock()
        mock_web3.is_connected.return_value = True
        MockWeb3.return_value = mock_web3
        with patch.object(Path, "exists", return_value=True):
            with patch("builtins.open", MagicMock()):
                with patch("json.load", return_value={"abi": []}):
                    client = AssetRegistryClient({
                        "RPC_URL": "http://localhost:8545",
                        "ASSET_REGISTRY_ADDRESS": "0x" + "b" * 40,
                    })
                    client.connect()
    assert client._web3 is not None
    assert client._contract is not None


def test_successful_create_asset_transaction():
    client, mock_web3, mock_contract, mock_account, mock_receipt = _build_mock_client()

    payload = {
        "assetHashBytes32": "0x" + "a" * 64,
        "originator": "0x" + "b" * 40,
        "faceValue": 100000000000000000000,
        "financingTarget": 80000000000000000000,
        "maturityTimestamp": 4074793200,
        "riskScore": 50,
    }

    result = client.create_asset(payload)

    assert result.success is True
    assert result.transaction_hash == "0x" + "00" * 32
    assert result.asset_id == 42
    assert result.block_number == 12345
    assert result.gas_used == 21000
    assert result.message == "Asset created successfully"


def test_correct_argument_ordering():
    client, mock_web3, mock_contract, mock_account, mock_receipt = _build_mock_client()

    payload = {
        "assetHashBytes32": "0x" + "a" * 64,
        "originator": "0x" + "b" * 40,
        "faceValue": 100000000000000000000,
        "financingTarget": 80000000000000000000,
        "maturityTimestamp": 4074793200,
        "riskScore": 50,
    }

    client.create_asset(payload)

    call_args = mock_contract.functions.createAsset.call_args
    assert call_args[0][0] == payload["assetHashBytes32"]
    assert call_args[0][1] == Web3.to_checksum_address(payload["originator"])
    assert call_args[0][2] == payload["faceValue"]
    assert call_args[0][3] == payload["financingTarget"]
    assert call_args[0][4] == payload["maturityTimestamp"]
    assert call_args[0][5] == payload["riskScore"]


def test_correct_payload_values_passed_to_create_asset():
    client, mock_web3, mock_contract, mock_account, mock_receipt = _build_mock_client()

    payload = {
        "assetHashBytes32": "0x" + "a" * 64,
        "originator": "0x" + "b" * 40,
        "faceValue": 100000000000000000000,
        "financingTarget": 80000000000000000000,
        "maturityTimestamp": 4074793200,
        "riskScore": 50,
    }

    client.create_asset(payload)

    call_args = mock_contract.functions.createAsset.call_args
    assert call_args[0][2] == 100000000000000000000
    assert call_args[0][3] == 80000000000000000000
    assert call_args[0][4] == 4074793200
    assert call_args[0][5] == 50


def test_transaction_receipt_handling():
    client, mock_web3, mock_contract, mock_account, mock_receipt = _build_mock_client()

    payload = {
        "assetHashBytes32": "0x" + "a" * 64,
        "originator": "0x" + "b" * 40,
        "faceValue": 100,
        "financingTarget": 80,
        "maturityTimestamp": 1234567890,
        "riskScore": 50,
    }

    result = client.create_asset(payload)
    assert result.block_number == 12345
    assert result.gas_used == 21000


def test_asset_created_event_decoding():
    client, mock_web3, mock_contract, mock_account, mock_receipt = _build_mock_client()

    payload = {
        "assetHashBytes32": "0x" + "a" * 64,
        "originator": "0x" + "b" * 40,
        "faceValue": 100,
        "financingTarget": 80,
        "maturityTimestamp": 1234567890,
        "riskScore": 50,
    }

    result = client.create_asset(payload)
    assert result.asset_id == 42


def test_returned_asset_id():
    client, mock_web3, mock_contract, mock_account, mock_receipt = _build_mock_client()

    payload = {
        "assetHashBytes32": "0x" + "a" * 64,
        "originator": "0x" + "b" * 40,
        "faceValue": 100,
        "financingTarget": 80,
        "maturityTimestamp": 1234567890,
        "riskScore": 50,
    }

    result = client.create_asset(payload)
    assert result.asset_id == 42


def test_transaction_hash_returned_correctly():
    client, mock_web3, mock_contract, mock_account, mock_receipt = _build_mock_client()

    payload = {
        "assetHashBytes32": "0x" + "a" * 64,
        "originator": "0x" + "b" * 40,
        "faceValue": 100,
        "financingTarget": 80,
        "maturityTimestamp": 1234567890,
        "riskScore": 50,
    }

    result = client.create_asset(payload)
    assert result.transaction_hash == "0x" + "00" * 32


def test_reverted_transaction():
    client, mock_web3, mock_contract, mock_account, mock_receipt = _build_mock_client()
    mock_receipt.status = 0

    payload = {
        "assetHashBytes32": "0x" + "a" * 64,
        "originator": "0x" + "b" * 40,
        "faceValue": 100,
        "financingTarget": 80,
        "maturityTimestamp": 1234567890,
        "riskScore": 50,
    }

    with pytest.raises(AssetRegistryTransactionError, match="reverted"):
        client.create_asset(payload)


def test_failed_receipt():
    client, mock_web3, mock_contract, mock_account, mock_receipt = _build_mock_client()
    mock_web3.eth.wait_for_transaction_receipt.side_effect = Exception("timeout")

    payload = {
        "assetHashBytes32": "0x" + "a" * 64,
        "originator": "0x" + "b" * 40,
        "faceValue": 100,
        "financingTarget": 80,
        "maturityTimestamp": 1234567890,
        "riskScore": 50,
    }

    with pytest.raises(AssetRegistryTransactionError, match="Transaction receipt failed"):
        client.create_asset(payload)


def test_missing_asset_created_event():
    client, mock_web3, mock_contract, mock_account, mock_receipt = _build_mock_client()
    mock_contract.events.AssetCreated.return_value.process_receipt.return_value = []

    payload = {
        "assetHashBytes32": "0x" + "a" * 64,
        "originator": "0x" + "b" * 40,
        "faceValue": 100,
        "financingTarget": 80,
        "maturityTimestamp": 1234567890,
        "riskScore": 50,
    }

    with pytest.raises(AssetRegistryTransactionError, match="AssetCreated event not found in receipt"):
        client.create_asset(payload)


def test_private_key_never_exposed_in_errors():
    fake_key = "0x" + "deadbeef" * 16
    with patch("services.asset_registry_client.Web3") as MockWeb3:
        mock_web3 = MagicMock()
        mock_web3.is_connected.return_value = True
        MockWeb3.return_value = mock_web3
        with patch.object(Path, "exists", return_value=True):
            with patch("builtins.open", MagicMock()):
                with patch("json.load", return_value={"abi": []}):
                    client = AssetRegistryClient({
                        "RPC_URL": "http://localhost:8545",
                        "ASSET_REGISTRY_ADDRESS": "0x" + "b" * 40,
                        "PRIVATE_KEY": fake_key,
                    })
                    client._web3 = mock_web3
                    client._contract = MagicMock()
                    client._account = MagicMock()
                    try:
                        client.create_asset({})
                    except AssetRegistryTransactionError as exc:
                        assert fake_key not in str(exc)


def test_missing_payload_fields():
    client, _, _, _, _ = _build_mock_client()
    with pytest.raises(AssetRegistryTransactionError, match="Missing payload fields"):
        client.create_asset({})
