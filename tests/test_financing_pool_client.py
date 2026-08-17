from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from web3 import Web3

from services.financing_pool_client import (
    FinancingPoolClient,
    FinancingPoolClientError,
    FinancingPoolConfigurationError,
    FinancingPoolTransactionError,
    FundingStateResult,
    FinancingPoolTransactionResult,
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
    mock_event.process_receipt.return_value = [{"args": {"assetId": 42, "investor": "0x" + "b" * 40, "amount": 100}}]
    mock_contract.events.AssetFunded.return_value = mock_event
    mock_contract.events.FundingCompleted.return_value = mock_event
    mock_contract.events.RepaymentReceived.return_value = mock_event
    mock_contract.events.ReturnsClaimed.return_value = mock_event

    mock_tx = {"from": mock_account.address}
    mock_contract.functions.fund.return_value.build_transaction.return_value = mock_tx
    mock_contract.functions.repay.return_value.build_transaction.return_value = mock_tx
    mock_contract.functions.claim.return_value.build_transaction.return_value = mock_tx
    mock_contract.functions.getFundingState.return_value.call.return_value = (100, 0, True)

    mock_receipt = MagicMock()
    mock_receipt.status = 1
    mock_receipt.blockNumber = 12345
    mock_receipt.gasUsed = 21000
    mock_web3.eth.wait_for_transaction_receipt.return_value = mock_receipt
    mock_web3.eth.send_raw_transaction.return_value = b"\x00" * 32

    mock_asset_registry_contract = MagicMock()
    mock_asset_registry_contract.functions.getAssetStatus.return_value.call.return_value = 0
    mock_asset_registry_contract.functions.getAssetFinancingTarget.return_value.call.return_value = 100000000000000000000
    mock_web3.eth.contract.return_value = mock_asset_registry_contract

    with patch("services.financing_pool_client.Web3") as MockWeb3:
        MockWeb3.HTTPProvider.return_value = MagicMock()
        MockWeb3.to_checksum_address.side_effect = lambda x: x
        MockWeb3.return_value = mock_web3

        with patch.object(Path, "exists", return_value=True):
            with patch("builtins.open", MagicMock()):
                with patch("json.load", return_value={"abi": []}):
                    client = FinancingPoolClient({
                        "RPC_URL": "http://localhost:8545",
                        "FINANCING_POOL_ADDRESS": "0x" + "b" * 40,
                        "PRIVATE_KEY": "0x" + "c" * 64,
                        "CHAIN_ID": 31337,
                        "ASSET_REGISTRY_ADDRESS": "0x" + "d" * 40,
                    })
                    client._web3 = mock_web3
                    client._contract = mock_contract
                    client._account = mock_account
                    client._asset_registry_contract = mock_asset_registry_contract
                    return client, mock_web3, mock_contract, mock_account, mock_receipt, mock_asset_registry_contract


def test_client_configuration():
    client, _, _, _, _, _ = _build_mock_client()
    assert client.config["RPC_URL"] == "http://localhost:8545"
    assert client.config["FINANCING_POOL_ADDRESS"] == "0x" + "b" * 40


def test_missing_rpc_configuration():
    with pytest.raises(FinancingPoolConfigurationError, match="RPC_URL is required"):
        FinancingPoolClient({}).connect()


def test_missing_financing_pool_address():
    with pytest.raises(FinancingPoolConfigurationError, match="FINANCING_POOL_ADDRESS is required"):
        FinancingPoolClient({"RPC_URL": "http://localhost:8545"}).connect()


def test_missing_signer_configuration():
    with patch("services.financing_pool_client.Web3"):
        with patch.object(Path, "exists", return_value=True):
            with patch("builtins.open", MagicMock()):
                with patch("json.load", return_value={"abi": []}):
                    client = FinancingPoolClient({
                        "RPC_URL": "http://localhost:8545",
                        "FINANCING_POOL_ADDRESS": "0x" + "b" * 40,
                    })
                    client._web3 = MagicMock()
                    client._web3.is_connected.return_value = True
                    client._contract = MagicMock()
                    with pytest.raises(FinancingPoolConfigurationError, match="PRIVATE_KEY is required"):
                        client.fund(1, 100)


def test_invalid_financing_pool_address():
    with patch("services.financing_pool_client.Web3") as MockWeb3:
        mock_web3 = MagicMock()
        mock_web3.is_connected.return_value = True
        MockWeb3.return_value = mock_web3
        MockWeb3.to_checksum_address.side_effect = ValueError("Invalid address")
        with patch.object(Path, "exists", return_value=True):
            with patch("builtins.open", MagicMock()):
                with patch("json.load", return_value={"abi": []}):
                    client = FinancingPoolClient({
                        "RPC_URL": "http://localhost:8545",
                        "FINANCING_POOL_ADDRESS": "invalid_address",
                    })
                    with pytest.raises(FinancingPoolConfigurationError, match="Invalid FINANCING_POOL_ADDRESS"):
                        client.connect()


def test_successful_contract_initialization():
    with patch("services.financing_pool_client.Web3") as MockWeb3:
        mock_web3 = MagicMock()
        mock_web3.is_connected.return_value = True
        MockWeb3.return_value = mock_web3
        with patch.object(Path, "exists", return_value=True):
            with patch("builtins.open", MagicMock()):
                with patch("json.load", return_value={"abi": []}):
                    client = FinancingPoolClient({
                        "RPC_URL": "http://localhost:8545",
                        "FINANCING_POOL_ADDRESS": "0x" + "b" * 40,
                    })
                    client.connect()
    assert client._web3 is not None
    assert client._contract is not None


def test_get_funding_state_success():
    client, _, _, _, _, _ = _build_mock_client()

    result = client.get_funding_state(1)

    assert result.success is True
    assert result.asset_id == 1
    assert result.total_funded == 100
    assert result.total_repaid == 0
    assert result.exists is True
    assert result.message == "Funding state retrieved successfully"


def test_get_funding_state_failure():
    client, mock_web3, mock_contract, mock_account, mock_receipt, _ = _build_mock_client()
    mock_contract.functions.getFundingState.return_value.call.side_effect = Exception("RPC error")

    with pytest.raises(FinancingPoolTransactionError, match="Failed to fetch funding state"):
        client.get_funding_state(1)


def test_get_asset_status_success():
    client, _, _, _, _, mock_asset_registry = _build_mock_client()
    mock_asset_registry.functions.getAssetStatus.return_value.call.return_value = 2

    status = client.get_asset_status(1)

    assert status == 2


def test_get_financing_target_success():
    client, _, _, _, _, mock_asset_registry = _build_mock_client()
    mock_asset_registry.functions.getAssetFinancingTarget.return_value.call.return_value = 100000000000000000000

    target = client.get_financing_target(1)

    assert target == 100000000000000000000


def test_fund_constructs_exact_contract_call():
    client, _, mock_contract, _, _, _ = _build_mock_client()

    result = client.fund(1, 100000000000000000000)

    call_args = mock_contract.functions.fund.call_args
    assert call_args[0][0] == 1
    assert call_args[0][1] == 100000000000000000000


def test_fund_returns_transaction_info():
    client, _, mock_contract, _, mock_receipt, _ = _build_mock_client()

    result = client.fund(1, 100000000000000000000)

    assert result.success is True
    assert result.transaction_hash == "0x" + "00" * 32
    assert result.asset_id == 1
    assert result.block_number == 12345
    assert result.gas_used == 21000
    assert result.message == "Funding transaction successful"


def test_fund_processes_asset_funded_event():
    client, _, mock_contract, _, mock_receipt, _ = _build_mock_client()
    mock_event = MagicMock()
    mock_event.process_receipt.return_value = [{"args": {"assetId": 42, "investor": "0x" + "b" * 40, "amount": 100}}]
    mock_contract.events.AssetFunded.return_value = mock_event
    mock_contract.events.FundingCompleted.return_value = MagicMock(return_value=MagicMock(process_receipt=MagicMock(return_value=[])))

    result = client.fund(1, 100)

    assert "AssetFunded" in result.events
    assert result.events["AssetFunded"]["assetId"] == 42
    assert result.events["AssetFunded"]["amount"] == 100


def test_fund_processes_funding_completed_event():
    client, _, mock_contract, _, mock_receipt, _ = _build_mock_client()
    mock_event = MagicMock()
    mock_event.process_receipt.return_value = [{"args": {"assetId": 42, "totalFunded": 800}}]
    mock_contract.events.FundingCompleted.return_value = mock_event
    mock_contract.events.AssetFunded.return_value = MagicMock(return_value=MagicMock(process_receipt=MagicMock(return_value=[])))

    result = client.fund(1, 800)

    assert "FundingCompleted" in result.events
    assert result.events["FundingCompleted"]["assetId"] == 42
    assert result.events["FundingCompleted"]["totalFunded"] == 800


def test_repay_constructs_exact_contract_call():
    client, _, mock_contract, _, _, _ = _build_mock_client()

    result = client.repay(1, 100000000000000000000)

    call_args = mock_contract.functions.repay.call_args
    assert call_args[0][0] == 1
    assert call_args[0][1] == 100000000000000000000


def test_repay_returns_transaction_info():
    client, _, mock_contract, _, mock_receipt, _ = _build_mock_client()

    result = client.repay(1, 100000000000000000000)

    assert result.success is True
    assert result.transaction_hash == "0x" + "00" * 32
    assert result.asset_id == 1
    assert result.block_number == 12345
    assert result.gas_used == 21000
    assert result.message == "Repayment transaction successful"


def test_repay_processes_repayment_received_event():
    client, _, mock_contract, _, mock_receipt, _ = _build_mock_client()
    mock_event = MagicMock()
    mock_event.process_receipt.return_value = [{"args": {"assetId": 42, "payer": "0x" + "c" * 40, "amount": 100}}]
    mock_contract.events.RepaymentReceived.return_value = mock_event

    result = client.repay(1, 100)

    assert "RepaymentReceived" in result.events
    assert result.events["RepaymentReceived"]["assetId"] == 42
    assert result.events["RepaymentReceived"]["amount"] == 100


def test_claim_constructs_exact_contract_call():
    client, _, mock_contract, _, _, _ = _build_mock_client()

    result = client.claim(1)

    call_args = mock_contract.functions.claim.call_args
    assert call_args[0][0] == 1


def test_claim_processes_returns_claimed_event():
    client, _, mock_contract, _, mock_receipt, _ = _build_mock_client()
    mock_event = MagicMock()
    mock_event.process_receipt.return_value = [{"args": {"assetId": 42, "investor": "0x" + "b" * 40, "amount": 50}}]
    mock_contract.events.ReturnsClaimed.return_value = mock_event

    result = client.claim(1)

    assert "ReturnsClaimed" in result.events
    assert result.events["ReturnsClaimed"]["assetId"] == 42
    assert result.events["ReturnsClaimed"]["amount"] == 50


def test_transaction_provider_errors_become_controlled_exception():
    client, mock_web3, mock_contract, mock_account, mock_receipt, _ = _build_mock_client()
    mock_web3.eth.wait_for_transaction_receipt.side_effect = Exception("provider error")

    with pytest.raises(FinancingPoolTransactionError, match="Transaction receipt failed"):
        client.fund(1, 100)


def test_reverted_transaction():
    client, mock_web3, mock_contract, mock_account, mock_receipt, _ = _build_mock_client()
    mock_receipt.status = 0

    with pytest.raises(FinancingPoolTransactionError, match="reverted"):
        client.fund(1, 100)


def test_private_key_never_exposed_in_errors():
    fake_key = "0x" + "deadbeef" * 16
    with patch("services.financing_pool_client.Web3") as MockWeb3:
        mock_web3 = MagicMock()
        mock_web3.is_connected.return_value = True
        MockWeb3.return_value = mock_web3
        with patch.object(Path, "exists", return_value=True):
            with patch("builtins.open", MagicMock()):
                with patch("json.load", return_value={"abi": []}):
                    client = FinancingPoolClient({
                        "RPC_URL": "http://localhost:8545",
                        "FINANCING_POOL_ADDRESS": "0x" + "b" * 40,
                        "PRIVATE_KEY": fake_key,
                    })
                    client._web3 = mock_web3
                    client._contract = MagicMock()
                    client._account = MagicMock()
                    try:
                        client.fund(1, 100)
                    except FinancingPoolTransactionError as exc:
                        assert fake_key not in str(exc)


def test_rpc_url_not_exposed_in_errors():
    rpc_url = "http://secret-rpc.example.com"
    with patch("services.financing_pool_client.Web3") as MockWeb3:
        mock_web3 = MagicMock()
        mock_web3.is_connected.side_effect = Exception("connection failed")
        MockWeb3.return_value = mock_web3
        with patch.object(Path, "exists", return_value=True):
            with patch("builtins.open", MagicMock()):
                with patch("json.load", return_value={"abi": []}):
                    client = FinancingPoolClient({
                        "RPC_URL": rpc_url,
                        "FINANCING_POOL_ADDRESS": "0x" + "b" * 40,
                    })
                    try:
                        client.connect()
                    except FinancingPoolConfigurationError as exc:
                        assert rpc_url not in str(exc)


def test_financing_pool_address_not_exposed_in_errors():
    pool_address = "0x" + "secret" * 10
    with patch("services.financing_pool_client.Web3") as MockWeb3:
        mock_web3 = MagicMock()
        mock_web3.is_connected.side_effect = Exception("connection failed")
        MockWeb3.return_value = mock_web3
        with patch.object(Path, "exists", return_value=True):
            with patch("builtins.open", MagicMock()):
                with patch("json.load", return_value={"abi": []}):
                    client = FinancingPoolClient({
                        "RPC_URL": "http://localhost:8545",
                        "FINANCING_POOL_ADDRESS": pool_address,
                    })
                    try:
                        client.connect()
                    except FinancingPoolConfigurationError as exc:
                        assert pool_address not in str(exc)


def test_no_real_rpc_calls():
    client = FinancingPoolClient({
        "RPC_URL": "http://localhost:8545",
        "FINANCING_POOL_ADDRESS": "0x" + "b" * 40,
    })
    assert client._web3 is None


def test_abi_artifact_loading():
    with patch("services.financing_pool_client.Web3") as MockWeb3:
        mock_web3 = MagicMock()
        mock_web3.is_connected.return_value = True
        MockWeb3.return_value = mock_web3
        with patch.object(Path, "exists", return_value=True):
            with patch("builtins.open", MagicMock()):
                with patch("json.load", return_value={"abi": []}):
                    client = FinancingPoolClient({
                        "RPC_URL": "http://localhost:8545",
                        "FINANCING_POOL_ADDRESS": "0x" + "b" * 40,
                    })
                    client.connect()
    assert client._contract is not None
