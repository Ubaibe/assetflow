import os
import pytest
from datetime import datetime, timedelta

from decimal import Decimal
from dotenv import load_dotenv
from services.asset_registry_client import AssetRegistryClient, AssetRegistryTransactionResult
from services.financing_pool_client import FinancingPoolClient, FinancingPoolTransactionResult
from services.token_decimals import get_token_decimals, to_base_units, from_base_units

load_dotenv()


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BOTCHAIN_TESTNET_SMOKE") != "1",
    reason="Live BOT Chain testnet smoke tests are disabled. Set RUN_BOTCHAIN_TESTNET_SMOKE=1 to enable.",
)


def _build_config():
    return {
        "RPC_URL": os.getenv("BOT_CHAIN_RPC_URL", "https://rpc.bohr.life"),
        "CHAIN_ID": int(os.getenv("BOT_CHAIN_CHAIN_ID", "968")),
        "ASSET_REGISTRY_ADDRESS": os.getenv("ASSET_REGISTRY_ADDRESS"),
        "FINANCING_POOL_ADDRESS": os.getenv("FINANCING_POOL_ADDRESS"),
        "PAYMENT_TOKEN_ADDRESS": os.getenv("PAYMENT_TOKEN_ADDRESS"),
        "PRIVATE_KEY": os.getenv("PRIVATE_KEY"),
        "PAYMENT_TOKEN_DECIMALS": os.getenv("PAYMENT_TOKEN_DECIMALS", "18"),
    }


def test_bot_chain_testnet_connection():
    config = _build_config()
    for key in ["BOT_CHAIN_RPC_URL", "BOT_CHAIN_CHAIN_ID", "ASSET_REGISTRY_ADDRESS", "FINANCING_POOL_ADDRESS", "PAYMENT_TOKEN_ADDRESS", "PRIVATE_KEY"]:
        if not os.getenv(key):
            pytest.skip(f"{key} is not set")

    client = FinancingPoolClient(config)
    client.connect()

    web3 = client._web3
    chain_id = web3.eth.chain_id
    assert chain_id == 968, f"Expected chain ID 968, got {chain_id}"


def test_bot_chain_testnet_deployer_balance():
    config = _build_config()
    for key in ["BOT_CHAIN_RPC_URL", "BOT_CHAIN_CHAIN_ID", "ASSET_REGISTRY_ADDRESS", "FINANCING_POOL_ADDRESS", "PAYMENT_TOKEN_ADDRESS", "PRIVATE_KEY"]:
        if not os.getenv(key):
            pytest.skip(f"{key} is not set")

    client = FinancingPoolClient(config)
    client.connect()

    address = client._account.address
    balance = client._web3.eth.get_balance(address)
    assert balance > 0, f"Deployer balance is zero: {address}"


def test_bot_chain_testnet_payment_token_decimals():
    config = _build_config()
    for key in ["BOT_CHAIN_RPC_URL", "BOT_CHAIN_CHAIN_ID", "ASSET_REGISTRY_ADDRESS", "FINANCING_POOL_ADDRESS", "PAYMENT_TOKEN_ADDRESS", "PRIVATE_KEY"]:
        if not os.getenv(key):
            pytest.skip(f"{key} is not set")

    from web3 import Web3

    web3 = Web3(Web3.HTTPProvider(config["RPC_URL"]))
    token = web3.eth.contract(
        address=Web3.to_checksum_address(config["PAYMENT_TOKEN_ADDRESS"]),
        abi=[
            {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
        ],
    )
    decimals = token.functions.decimals().call()
    assert decimals >= 0


def test_bot_chain_testnet_create_and_fund_asset():
    config = _build_config()
    for key in ["BOT_CHAIN_RPC_URL", "BOT_CHAIN_CHAIN_ID", "ASSET_REGISTRY_ADDRESS", "FINANCING_POOL_ADDRESS", "PAYMENT_TOKEN_ADDRESS", "PRIVATE_KEY"]:
        if not os.getenv(key):
            pytest.skip(f"{key} is not set")

    from web3 import Web3
    from database.enums import AssetStatus, DocumentStatus

    registry_client = AssetRegistryClient(config)
    registry_client.connect()

    import time
    asset_hash = "0x" + (format(int(time.time()), 'x') + "a" * 55)[:64]
    face_value = Decimal("100.00")
    financing_target = Decimal("80.00")
    issue_date = datetime.utcnow().date()
    due_date = issue_date + timedelta(days=30)
    risk_score = 50

    from services.financing_preparation import prepare_financing
    from database.models import Asset, InvoiceDocument

    dummy_asset = Asset(
        user_id=0,
        asset_hash=asset_hash,
        invoice_number="INV-001",
        face_value=face_value,
        currency="USD",
        financing_target=financing_target,
        issue_date=datetime.combine(issue_date, datetime.min.time()),
        due_date=datetime.combine(due_date, datetime.min.time()),
        risk_score=risk_score,
        status=AssetStatus.DRAFT.value,
    )
    dummy_document = InvoiceDocument(
        asset_id=0,
        original_filename="test.pdf",
        stored_filename="test.pdf",
        mime_type="application/pdf",
        file_size=0,
        file_hash=asset_hash,
        processing_status=DocumentStatus.EXTRACTED.value,
    )

    decimals = get_token_decimals(config)
    prep = prepare_financing(dummy_asset, dummy_document, originator_address=registry_client._account.address, token_decimals=decimals)
    assert prep.eligible is True, f"Financing preparation failed: {prep.message}"
    assert prep.payload is not None

    tx_result = registry_client.create_asset(prep.payload)
    assert tx_result.success is True
    assert tx_result.asset_id is not None
    assert tx_result.transaction_hash is not None

    on_chain_asset_id = tx_result.asset_id

    pool_client = FinancingPoolClient(config)
    pool_client.connect()

    amount_wei = to_base_units(Decimal("50.00"), decimals)

    token_contract = pool_client._web3.eth.contract(
        address=Web3.to_checksum_address(config["PAYMENT_TOKEN_ADDRESS"]),
        abi=pool_client._load_abi("MockUSDT.sol"),
    )
    investor_address = pool_client._account.address
    token_balance = token_contract.functions.balanceOf(investor_address).call()
    assert token_balance >= amount_wei, f"Insufficient token balance: {token_balance} < {amount_wei}"

    approval_result = pool_client.approve(config["PAYMENT_TOKEN_ADDRESS"], amount_wei)
    assert approval_result.success is True
    assert approval_result.transaction_hash is not None

    fund_result = pool_client.fund(on_chain_asset_id, amount_wei)
    assert fund_result.success is True
    assert fund_result.transaction_hash is not None
    assert fund_result.block_number is not None
    assert fund_result.gas_used is not None
    assert "AssetFunded" in fund_result.events
    assert fund_result.events["AssetFunded"]["logIndex"] is not None

    state = pool_client.get_funding_state(on_chain_asset_id)
    assert state.total_funded == amount_wei

    human_amount = from_base_units(fund_result.events["AssetFunded"]["amount"], decimals)
    assert human_amount == Decimal("50.00")
