from unittest.mock import patch, MagicMock

import pytest

from services.financing_funding import (
    FundingResult,
    FundingServiceError,
    FundingValidationError,
    prepare_and_fund,
)
from services.financing_pool_client import (
    FinancingPoolClient,
    FinancingPoolClientError,
    FinancingPoolConfigurationError,
    FinancingPoolTransactionError,
    FundingStateResult,
    FinancingPoolTransactionResult,
)

TOKEN = 10 ** 18
TARGET = 100 * TOKEN
FUNDED = 30 * TOKEN
REMAINING = TARGET - FUNDED


def _build_mock_client():
    mock_client = MagicMock(spec=FinancingPoolClient)
    mock_client.connect.return_value = None
    mock_client.get_asset_status.return_value = 0
    mock_client.get_financing_target.return_value = TARGET
    mock_client.get_funding_state.return_value = FundingStateResult(
        asset_id=1, total_funded=FUNDED, total_repaid=0, exists=True, success=True
    )
    mock_client.fund.return_value = FinancingPoolTransactionResult(
        transaction_hash="0x" + "00" * 32,
        asset_id=1,
        block_number=12345,
        success=True,
        gas_used=21000,
        message="Funding transaction successful",
    )
    return mock_client


def test_successful_funding_of_listed_asset():
    mock_client = _build_mock_client()
    with patch("services.financing_funding.FinancingPoolClient", return_value=mock_client):
        result = prepare_and_fund(1, REMAINING, {"RPC_URL": "http://localhost:8545"})

    assert result.funded is True
    assert result.asset_id == 1
    assert result.requested_amount == REMAINING
    assert result.financing_target == TARGET
    assert result.total_funded_before == FUNDED
    assert result.remaining_funding == 0
    assert result.asset_status == 0
    assert result.transaction_hash == "0x" + "00" * 32
    assert result.block_number == 12345
    assert result.gas_used == 21000
    assert result.message == "Funding transaction successful"
    mock_client.fund.assert_called_once_with(1, REMAINING)


def test_successful_funding_of_partially_funded_asset():
    mock_client = _build_mock_client()
    mock_client.get_asset_status.return_value = 1
    mock_client.get_funding_state.return_value = FundingStateResult(
        asset_id=1, total_funded=FUNDED, total_repaid=0, exists=True, success=True
    )
    with patch("services.financing_funding.FinancingPoolClient", return_value=mock_client):
        result = prepare_and_fund(1, REMAINING, {"RPC_URL": "http://localhost:8545"})

    assert result.funded is True
    assert result.asset_status == 1
    assert result.total_funded_before == FUNDED
    assert result.remaining_funding == 0
    mock_client.fund.assert_called_once_with(1, REMAINING)


def test_reject_zero_amount():
    with pytest.raises(FundingValidationError, match="amount must be a positive integer"):
        prepare_and_fund(1, 0, {})


def test_reject_negative_amount():
    with pytest.raises(FundingValidationError, match="amount must be a positive integer"):
        prepare_and_fund(1, -100, {})


def test_reject_nonexistent_asset():
    mock_client = _build_mock_client()
    mock_client.get_asset_status.return_value = 0
    mock_client.get_funding_state.return_value = FundingStateResult(
        asset_id=1, total_funded=0, total_repaid=0, exists=False, success=True
    )
    with patch("services.financing_funding.FinancingPoolClient", return_value=mock_client):
        result = prepare_and_fund(1, 100, {"RPC_URL": "http://localhost:8545"})

    assert result.funded is False
    assert "Asset does not exist on-chain" in result.message
    mock_client.fund.assert_not_called()


def test_reject_fully_funded_asset():
    mock_client = _build_mock_client()
    mock_client.get_asset_status.return_value = 2
    with patch("services.financing_funding.FinancingPoolClient", return_value=mock_client):
        result = prepare_and_fund(1, 100, {"RPC_URL": "http://localhost:8545"})

    assert result.funded is False
    assert "not fundable" in result.message
    mock_client.fund.assert_not_called()


def test_reject_repaid_asset():
    mock_client = _build_mock_client()
    mock_client.get_asset_status.return_value = 3
    with patch("services.financing_funding.FinancingPoolClient", return_value=mock_client):
        result = prepare_and_fund(1, 100, {"RPC_URL": "http://localhost:8545"})

    assert result.funded is False
    assert "not fundable" in result.message
    mock_client.fund.assert_not_called()


def test_reject_settled_asset():
    mock_client = _build_mock_client()
    mock_client.get_asset_status.return_value = 4
    with patch("services.financing_funding.FinancingPoolClient", return_value=mock_client):
        result = prepare_and_fund(1, 100, {"RPC_URL": "http://localhost:8545"})

    assert result.funded is False
    assert "not fundable" in result.message
    mock_client.fund.assert_not_called()


def test_reject_cancelled_asset():
    mock_client = _build_mock_client()
    mock_client.get_asset_status.return_value = 5
    with patch("services.financing_funding.FinancingPoolClient", return_value=mock_client):
        result = prepare_and_fund(1, 100, {"RPC_URL": "http://localhost:8545"})

    assert result.funded is False
    assert "not fundable" in result.message
    mock_client.fund.assert_not_called()


def test_reject_defaulted_asset():
    mock_client = _build_mock_client()
    mock_client.get_asset_status.return_value = 6
    with patch("services.financing_funding.FinancingPoolClient", return_value=mock_client):
        result = prepare_and_fund(1, 100, {"RPC_URL": "http://localhost:8545"})

    assert result.funded is False
    assert "not fundable" in result.message
    mock_client.fund.assert_not_called()


def test_reject_amount_greater_than_remaining_financing_capacity():
    mock_client = _build_mock_client()
    mock_client.get_financing_target.return_value = TARGET
    mock_client.get_funding_state.return_value = FundingStateResult(
        asset_id=1, total_funded=FUNDED, total_repaid=0, exists=True, success=True
    )
    with patch("services.financing_funding.FinancingPoolClient", return_value=mock_client):
        result = prepare_and_fund(1, REMAINING + 1, {"RPC_URL": "http://localhost:8545"})

    assert result.funded is False
    assert "exceeds remaining funding capacity" in result.message
    assert result.remaining_funding == REMAINING
    mock_client.fund.assert_not_called()


def test_allow_amount_exactly_equal_to_remaining_financing_capacity():
    mock_client = _build_mock_client()
    mock_client.get_financing_target.return_value = TARGET
    mock_client.get_funding_state.return_value = FundingStateResult(
        asset_id=1, total_funded=FUNDED, total_repaid=0, exists=True, success=True
    )
    with patch("services.financing_funding.FinancingPoolClient", return_value=mock_client):
        result = prepare_and_fund(1, REMAINING, {"RPC_URL": "http://localhost:8545"})

    assert result.funded is True
    assert result.remaining_funding == 0
    mock_client.fund.assert_called_once_with(1, REMAINING)


def test_reject_inconsistent_state_total_funded_exceeds_target():
    mock_client = _build_mock_client()
    mock_client.get_financing_target.return_value = TARGET
    mock_client.get_funding_state.return_value = FundingStateResult(
        asset_id=1, total_funded=TARGET + 1, total_repaid=0, exists=True, success=True
    )
    with patch("services.financing_funding.FinancingPoolClient", return_value=mock_client):
        result = prepare_and_fund(1, 1, {"RPC_URL": "http://localhost:8545"})

    assert result.funded is False
    assert "Inconsistent on-chain state" in result.message
    mock_client.fund.assert_not_called()


def test_correctly_calculate_remaining_funding():
    mock_client = _build_mock_client()
    mock_client.get_financing_target.return_value = TARGET
    mock_client.get_funding_state.return_value = FundingStateResult(
        asset_id=1, total_funded=FUNDED, total_repaid=0, exists=True, success=True
    )
    partial = REMAINING // 2
    with patch("services.financing_funding.FinancingPoolClient", return_value=mock_client):
        result = prepare_and_fund(1, partial, {"RPC_URL": "http://localhost:8545"})

    assert result.remaining_funding == REMAINING - partial
    mock_client.fund.assert_called_once_with(1, partial)


def test_correctly_pass_exact_validated_amount_to_fund():
    mock_client = _build_mock_client()
    mock_client.get_financing_target.return_value = TARGET
    mock_client.get_funding_state.return_value = FundingStateResult(
        asset_id=1, total_funded=0, total_repaid=0, exists=True, success=True
    )
    exact = TARGET - 1
    with patch("services.financing_funding.FinancingPoolClient", return_value=mock_client):
        result = prepare_and_fund(1, exact, {"RPC_URL": "http://localhost:8545"})

    mock_client.fund.assert_called_once_with(1, exact)
    assert result.funded is True


def test_fund_not_called_when_validation_fails():
    mock_client = _build_mock_client()
    with patch("services.financing_funding.FinancingPoolClient", return_value=mock_client):
        with pytest.raises(FundingValidationError):
            prepare_and_fund(1, 0, {"RPC_URL": "http://localhost:8545"})

    mock_client.fund.assert_not_called()


def test_map_successful_transaction_result_into_funding_result():
    mock_client = _build_mock_client()
    mock_client.fund.return_value = FinancingPoolTransactionResult(
        transaction_hash="0x" + "aa" * 32,
        asset_id=1,
        block_number=99999,
        success=True,
        gas_used=50000,
        message="Funding transaction successful",
        events={"AssetFunded": {"assetId": 1, "investor": "0x" + "b" * 40, "amount": 100}},
    )
    with patch("services.financing_funding.FinancingPoolClient", return_value=mock_client):
        result = prepare_and_fund(1, REMAINING, {"RPC_URL": "http://localhost:8545"})

    assert result.transaction_hash == "0x" + "aa" * 32
    assert result.block_number == 99999
    assert result.gas_used == 50000
    assert result.message == "Funding transaction successful"


def test_map_financing_pool_configuration_error():
    mock_client = _build_mock_client()
    mock_client.connect.side_effect = FinancingPoolConfigurationError(
        "PRIVATE_KEY is required: 0xsuper-secret-key"
    )
    with patch("services.financing_funding.FinancingPoolClient", return_value=mock_client):
        result = prepare_and_fund(1, REMAINING, {"RPC_URL": "http://localhost:8545"})

    assert result.funded is False
    assert "super-secret-key" not in result.message
    assert "Financing pool configuration error" in result.message


def test_map_financing_pool_transaction_error():
    mock_client = _build_mock_client()
    mock_client.get_asset_status.return_value = 0
    mock_client.get_financing_target.return_value = TARGET
    mock_client.get_funding_state.return_value = FundingStateResult(
        asset_id=1, total_funded=0, total_repaid=0, exists=True, success=True
    )
    mock_client.fund.side_effect = FinancingPoolTransactionError("Transaction reverted: 0xabc")
    with patch("services.financing_funding.FinancingPoolClient", return_value=mock_client):
        result = prepare_and_fund(1, REMAINING, {"RPC_URL": "http://localhost:8545"})

    assert result.funded is False
    assert "Funding transaction failed" in result.message
    assert "0xabc" in result.message


def test_sensitive_strings_never_appear_in_error_messages():
    mock_client = _build_mock_client()
    mock_client.get_asset_status.side_effect = FinancingPoolTransactionError(
        "Failed with PRIVATE_KEY=0xsuper-secret RPC_URL=http://secret.example.com Authorization=Bearer token"
    )
    with patch("services.financing_funding.FinancingPoolClient", return_value=mock_client):
        result = prepare_and_fund(1, REMAINING, {"RPC_URL": "http://localhost:8545"})

    assert "super-secret" not in result.message
    assert "secret.example.com" not in result.message
    assert "Bearer" not in result.message
    assert "Authorization" not in result.message
    assert "PRIVATE_KEY" not in result.message
    assert "RPC_URL" not in result.message


def test_url_never_appears_in_error_messages():
    mock_client = _build_mock_client()
    mock_client.get_asset_status.side_effect = FinancingPoolTransactionError(
        "Connection failed to https://rpc.bohr.life with timeout"
    )
    with patch("services.financing_funding.FinancingPoolClient", return_value=mock_client):
        result = prepare_and_fund(1, REMAINING, {"RPC_URL": "http://localhost:8545"})

    assert "https://rpc.bohr.life" not in result.message
    assert "Connection failed" not in result.message


def test_no_database_interaction():
    mock_client = _build_mock_client()
    with patch("services.financing_funding.FinancingPoolClient", return_value=mock_client):
        result = prepare_and_fund(1, REMAINING, {"RPC_URL": "http://localhost:8545"})

    assert not hasattr(result, "session")
    assert not hasattr(result, "db")


def test_verify_client_call_order():
    mock_client = _build_mock_client()
    with patch("services.financing_funding.FinancingPoolClient", return_value=mock_client) as MockClient:
        prepare_and_fund(1, REMAINING, {"RPC_URL": "http://localhost:8545"})

    assert mock_client.connect.call_count == 1
    assert mock_client.get_asset_status.call_count == 1
    assert mock_client.get_financing_target.call_count == 1
    assert mock_client.get_funding_state.call_count == 1
    assert mock_client.fund.call_count == 1

    status_call = mock_client.get_asset_status.call_args
    target_call = mock_client.get_financing_target.call_args
    state_call = mock_client.get_funding_state.call_args
    fund_call = mock_client.fund.call_args

    assert status_call[0][0] == 1
    assert target_call[0][0] == 1
    assert state_call[0][0] == 1
    assert fund_call[0][0] == 1
    assert fund_call[0][1] == REMAINING


def test_service_does_not_directly_depend_on_web3():
    import services.financing_funding as module

    assert "web3" not in dir(module)
    assert "Web3" not in dir(module)
    assert "HTTPProvider" not in dir(module)
    assert "Account" not in dir(module)
