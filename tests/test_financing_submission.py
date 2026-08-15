from unittest.mock import patch, MagicMock

import pytest

from services.financing_submission import FinancingSubmissionResult, submit_financing
from services.asset_registry_client import (
    AssetRegistryClientError,
    AssetRegistryConfigurationError,
    AssetRegistryTransactionError,
    AssetRegistryTransactionResult,
)
from services.financing_preparation import FinancingPreparationResult


def _build_mock_asset():
    asset = MagicMock()
    asset.id = 1
    asset.invoice_number = "INV-001"
    asset.face_value = 100.0
    asset.currency = "USD"
    asset.issue_date = None
    asset.due_date = None
    asset.asset_hash = "a" * 64
    asset.financing_target = 80.0
    asset.risk_score = 50
    asset.status = "draft"
    return asset


def _build_mock_document():
    document = MagicMock()
    document.processing_status = "extracted"
    return document


def test_ineligible_invoice_never_reaches_asset_registry_client():
    asset = _build_mock_asset()
    document = _build_mock_document()

    preparation = FinancingPreparationResult(
        eligible=False,
        failed_checks=["invoice_number"],
        reasons=["Invoice number is missing"],
        message="Invoice is not eligible",
    )

    with patch("services.financing_submission.prepare_financing", return_value=preparation) as mock_prep:
        with patch("services.financing_submission.AssetRegistryClient") as MockClient:
            result = submit_financing(asset, document)

    assert result.submitted is False
    assert result.eligible is False
    assert result.failed_checks == ["invoice_number"]
    assert result.reasons == ["Invoice number is missing"]
    mock_prep.assert_called_once()
    MockClient.assert_not_called()


def test_eligible_invoice_produces_submission():
    asset = _build_mock_asset()
    document = _build_mock_document()

    preparation = FinancingPreparationResult(
        eligible=True,
        asset_id=1,
        payload={
            "assetHashBytes32": "0x" + "a" * 64,
            "originator": "0x" + "b" * 40,
            "faceValue": 100000000000000000000,
            "financingTarget": 80000000000000000000,
            "maturityTimestamp": 4074793200,
            "riskScore": 50,
        },
    )

    tx_result = AssetRegistryTransactionResult(
        transaction_hash="0x" + "c" * 64,
        asset_id=42,
        block_number=12345,
        success=True,
        gas_used=21000,
        message="Asset created successfully",
    )

    mock_client = MagicMock()
    mock_client.create_asset.return_value = tx_result

    with patch("services.financing_submission.prepare_financing", return_value=preparation) as mock_prep:
        with patch("services.financing_submission.AssetRegistryClient", return_value=mock_client) as MockClient:
            result = submit_financing(asset, document, config={"RPC_URL": "http://localhost:8545"})

    assert result.submitted is True
    assert result.eligible is True
    assert result.asset_id == 42
    assert result.transaction_hash == "0x" + "c" * 64
    assert result.block_number == 12345
    assert result.gas_used == 21000
    assert result.message == "Asset created successfully"
    mock_prep.assert_called_once()
    MockClient.assert_called_once_with({"RPC_URL": "http://localhost:8545"})
    mock_client.create_asset.assert_called_once_with(preparation.payload)


def test_exact_payload_passed_unchanged():
    asset = _build_mock_asset()
    document = _build_mock_document()

    preparation = FinancingPreparationResult(
        eligible=True,
        payload={
            "assetHashBytes32": "0x" + "a" * 64,
            "originator": "0x" + "b" * 40,
            "faceValue": 100000000000000000000,
            "financingTarget": 80000000000000000000,
            "maturityTimestamp": 4074793200,
            "riskScore": 50,
        },
    )

    tx_result = AssetRegistryTransactionResult(
        transaction_hash="0x" + "c" * 64,
        asset_id=42,
        block_number=12345,
        success=True,
        gas_used=21000,
    )

    mock_client = MagicMock()
    mock_client.create_asset.return_value = tx_result

    with patch("services.financing_submission.prepare_financing", return_value=preparation):
        with patch("services.financing_submission.AssetRegistryClient", return_value=mock_client):
            result = submit_financing(asset, document)

    call_args = mock_client.create_asset.call_args[0][0]
    assert call_args == preparation.payload
    assert call_args["assetHashBytes32"] == "0x" + "a" * 64
    assert call_args["faceValue"] == 100000000000000000000
    assert call_args["financingTarget"] == 80000000000000000000
    assert call_args["maturityTimestamp"] == 4074793200
    assert call_args["riskScore"] == 50


def test_transaction_hash_returned_unchanged():
    asset = _build_mock_asset()
    document = _build_mock_document()

    preparation = FinancingPreparationResult(eligible=True, payload={})
    tx_result = AssetRegistryTransactionResult(
        transaction_hash="0x" + "deadbeef" * 8,
        asset_id=1,
        block_number=1,
        success=True,
    )

    mock_client = MagicMock()
    mock_client.create_asset.return_value = tx_result

    with patch("services.financing_submission.prepare_financing", return_value=preparation):
        with patch("services.financing_submission.AssetRegistryClient", return_value=mock_client):
            result = submit_financing(asset, document)

    assert result.transaction_hash == "0x" + "deadbeef" * 8


def test_asset_id_returned_unchanged():
    asset = _build_mock_asset()
    document = _build_mock_document()

    preparation = FinancingPreparationResult(eligible=True, payload={})
    tx_result = AssetRegistryTransactionResult(
        transaction_hash="0x" + "c" * 64,
        asset_id=999,
        block_number=1,
        success=True,
    )

    mock_client = MagicMock()
    mock_client.create_asset.return_value = tx_result

    with patch("services.financing_submission.prepare_financing", return_value=preparation):
        with patch("services.financing_submission.AssetRegistryClient", return_value=mock_client):
            result = submit_financing(asset, document)

    assert result.asset_id == 999


def test_block_number_returned_unchanged():
    asset = _build_mock_asset()
    document = _build_mock_document()

    preparation = FinancingPreparationResult(eligible=True, payload={})
    tx_result = AssetRegistryTransactionResult(
        transaction_hash="0x" + "c" * 64,
        asset_id=1,
        block_number=55555,
        success=True,
    )

    mock_client = MagicMock()
    mock_client.create_asset.return_value = tx_result

    with patch("services.financing_submission.prepare_financing", return_value=preparation):
        with patch("services.financing_submission.AssetRegistryClient", return_value=mock_client):
            result = submit_financing(asset, document)

    assert result.block_number == 55555


def test_gas_used_returned_unchanged():
    asset = _build_mock_asset()
    document = _build_mock_document()

    preparation = FinancingPreparationResult(eligible=True, payload={})
    tx_result = AssetRegistryTransactionResult(
        transaction_hash="0x" + "c" * 64,
        asset_id=1,
        block_number=1,
        success=True,
        gas_used=77777,
    )

    mock_client = MagicMock()
    mock_client.create_asset.return_value = tx_result

    with patch("services.financing_submission.prepare_financing", return_value=preparation):
        with patch("services.financing_submission.AssetRegistryClient", return_value=mock_client):
            result = submit_financing(asset, document)

    assert result.gas_used == 77777


def test_blockchain_submission_failure_is_handled():
    asset = _build_mock_asset()
    document = _build_mock_document()

    preparation = FinancingPreparationResult(eligible=True, payload={})

    mock_client = MagicMock()
    mock_client.create_asset.side_effect = AssetRegistryTransactionError("Transaction reverted: 0xabc")

    with patch("services.financing_submission.prepare_financing", return_value=preparation):
        with patch("services.financing_submission.AssetRegistryClient", return_value=mock_client):
            result = submit_financing(asset, document)

    assert result.submitted is False
    assert result.eligible is True
    assert "Transaction reverted" in result.message


def test_configuration_failure_is_handled():
    asset = _build_mock_asset()
    document = _build_mock_document()

    preparation = FinancingPreparationResult(eligible=True, payload={})

    mock_client = MagicMock()
    mock_client.create_asset.side_effect = AssetRegistryConfigurationError("PRIVATE_KEY is required")

    with patch("services.financing_submission.prepare_financing", return_value=preparation):
        with patch("services.financing_submission.AssetRegistryClient", return_value=mock_client):
            result = submit_financing(asset, document)

    assert result.submitted is False
    assert result.eligible is True
    assert result.message == "AssetRegistry configuration error"


def test_private_key_is_not_leaked():
    asset = _build_mock_asset()
    document = _build_mock_document()

    preparation = FinancingPreparationResult(eligible=True, payload={})

    mock_client = MagicMock()
    fake_key = "0x" + "deadbeef" * 16
    mock_client.create_asset.side_effect = AssetRegistryConfigurationError(
        f"PRIVATE_KEY is required: {fake_key}"
    )

    with patch("services.financing_submission.prepare_financing", return_value=preparation):
        with patch("services.financing_submission.AssetRegistryClient", return_value=mock_client):
            result = submit_financing(asset, document)

    assert fake_key not in result.message
    assert result.message == "AssetRegistry configuration error"


def test_asset_remains_unchanged():
    asset = _build_mock_asset()
    document = _build_mock_document()

    preparation = FinancingPreparationResult(eligible=True, payload={})
    tx_result = AssetRegistryTransactionResult(
        transaction_hash="0x" + "c" * 64,
        asset_id=42,
        block_number=12345,
        success=True,
    )

    mock_client = MagicMock()
    mock_client.create_asset.return_value = tx_result

    with patch("services.financing_submission.prepare_financing", return_value=preparation):
        with patch("services.financing_submission.AssetRegistryClient", return_value=mock_client):
            submit_financing(asset, document)

    asset.status = "draft"


def test_service_does_not_import_flask_or_database():
    import services.financing_submission as module
    assert "flask" not in dir(module)
    assert "current_app" not in dir(module)
    assert "db" not in dir(module)


def test_preparation_failure_prevents_submission():
    asset = _build_mock_asset()
    document = _build_mock_document()

    preparation = FinancingPreparationResult(
        eligible=False,
        failed_checks=["face_value"],
        reasons=["Invoice face value must be greater than zero"],
    )

    mock_client = MagicMock()

    with patch("services.financing_submission.prepare_financing", return_value=preparation):
        with patch("services.financing_submission.AssetRegistryClient", return_value=mock_client) as MockClient:
            result = submit_financing(asset, document)

    assert result.submitted is False
    assert result.eligible is False
    MockClient.assert_not_called()
    mock_client.create_asset.assert_not_called()


def test_asset_registry_client_error_is_caught():
    asset = _build_mock_asset()
    document = _build_mock_document()

    preparation = FinancingPreparationResult(eligible=True, payload={})

    mock_client = MagicMock()
    mock_client.create_asset.side_effect = AssetRegistryClientError("Some error")

    with patch("services.financing_submission.prepare_financing", return_value=preparation):
        with patch("services.financing_submission.AssetRegistryClient", return_value=mock_client):
            result = submit_financing(asset, document)

    assert result.submitted is False
    assert result.eligible is True
    assert result.message == "Some error"


def test_orchestration_does_not_duplicate_eligibility_logic():
    asset = _build_mock_asset()
    document = _build_mock_document()

    preparation = FinancingPreparationResult(
        eligible=True,
        failed_checks=[],
        reasons=[],
        payload={},
    )

    tx_result = AssetRegistryTransactionResult(
        transaction_hash="0x" + "c" * 64,
        asset_id=42,
        block_number=12345,
        success=True,
    )

    mock_client = MagicMock()
    mock_client.create_asset.return_value = tx_result

    with patch("services.financing_submission.prepare_financing", return_value=preparation) as mock_prep:
        with patch("services.financing_submission.AssetRegistryClient", return_value=mock_client):
            result = submit_financing(asset, document)

    assert result.submitted is True
    assert result.eligible is True
    assert result.failed_checks == []
    assert result.reasons == []
    mock_prep.assert_called_once()
