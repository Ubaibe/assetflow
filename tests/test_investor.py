import pytest
from decimal import Decimal
from unittest.mock import patch

from app import create_app
from database import db
from database.models import User, Wallet, Asset, Investment, BlockchainTransaction
from database.enums import UserRole, AssetStatus, InvestmentStatus, TransactionType, TransactionStatus
from services.financing_funding import FundingResult


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def _create_investor(app, email="investor@example.com"):
    with app.app_context():
        from eth_account import Account
        account = Account.create()
        user = User(email=email, password_hash=None, role=UserRole.INVESTOR)
        db.session.add(user)
        db.session.commit()

        wallet = Wallet(user_id=user.id, address=account.address, chain_id=1)
        db.session.add(wallet)
        db.session.commit()

        return user.id, account


def _create_asset(app, user_id, status=AssetStatus.LISTED, **kwargs):
    with app.app_context():
        asset = Asset(
            user_id=user_id,
            asset_hash=kwargs.get("asset_hash", "0x" + "ab" * 32),
            blockchain_asset_id=kwargs.get("blockchain_asset_id", 1),
            status=status,
            face_value=kwargs.get("face_value", Decimal("1000.00")),
            financing_target=kwargs.get("financing_target", Decimal("1000.00")),
            currency=kwargs.get("currency", "USD"),
            risk_score=kwargs.get("risk_score", 85),
            risk_grade=kwargs.get("risk_grade", "A"),
        )
        db.session.add(asset)
        db.session.commit()
        return asset.id


def _login(client, user_id, account):
    with client.application.app_context():
        user = User.query.get(user_id)
        wallet = user.wallets[0]

        from auth.services import create_challenge
        from eth_account.messages import encode_defunct

        challenge = create_challenge(wallet.address)
        encoded = encode_defunct(text=challenge["message"])
        signature = account.sign_message(encoded).signature.hex()

        response = client.post("/auth/verify", json={
            "wallet_address": wallet.address,
            "signature": signature,
            "challenge_id": challenge["challenge_id"],
        })
        assert response.status_code == 200


def test_unauthenticated_dashboard_access(client):
    response = client.get("/investor/dashboard")
    assert response.status_code == 401


def test_authenticated_investor_dashboard_access(client):
    user_id, account = _create_investor(client.application)
    _login(client, user_id, account)
    response = client.get("/investor/dashboard")
    assert response.status_code == 200
    assert b"Investor Marketplace" in response.data


def test_dashboard_excludes_non_investable_statuses(client):
    user_id, account = _create_investor(client.application)
    _login(client, user_id, account)

    with client.application.app_context():
        _create_asset(client.application, user_id, status=AssetStatus.DRAFT, asset_hash="0x" + "aa" * 32, blockchain_asset_id=None)
        _create_asset(client.application, user_id, status=AssetStatus.CANCELLED, asset_hash="0x" + "bb" * 32, blockchain_asset_id=None)
        _create_asset(client.application, user_id, status=AssetStatus.DEFAULTED, asset_hash="0x" + "cc" * 32, blockchain_asset_id=None)
        _create_asset(client.application, user_id, status=AssetStatus.REPAID, asset_hash="0x" + "dd" * 32, blockchain_asset_id=None)
        _create_asset(client.application, user_id, status=AssetStatus.SETTLED, asset_hash="0x" + "ee" * 32, blockchain_asset_id=None)
        listed_id = _create_asset(client.application, user_id, status=AssetStatus.LISTED, asset_hash="0x" + "ff" * 32)

    response = client.get("/investor/dashboard")
    assert response.status_code == 200
    data = response.data.decode()
    assert str(listed_id) in data
    assert "draft" not in data.lower()
    assert "cancelled" not in data.lower()
    assert "defaulted" not in data.lower()


def test_dashboard_displays_eligible_assets(client):
    user_id, account = _create_investor(client.application)
    _login(client, user_id, account)

    with client.application.app_context():
        asset_id = _create_asset(client.application, user_id, status=AssetStatus.LISTED)

    response = client.get("/investor/dashboard")
    assert response.status_code == 200
    data = response.data.decode()
    assert str(asset_id) in data


def test_investor_can_view_asset_detail(client):
    user_id, account = _create_investor(client.application)
    _login(client, user_id, account)

    with client.application.app_context():
        asset_id = _create_asset(client.application, user_id, status=AssetStatus.LISTED)

    response = client.get(f"/investor/assets/{asset_id}")
    assert response.status_code == 200
    assert b"Investment Opportunity" in response.data


def test_nonexistent_asset_returns_404(client):
    user_id, account = _create_investor(client.application)
    _login(client, user_id, account)
    response = client.get("/investor/assets/99999")
    assert response.status_code == 404


def test_funding_form_requires_amount(client):
    user_id, account = _create_investor(client.application)
    _login(client, user_id, account)

    with client.application.app_context():
        asset_id = _create_asset(client.application, user_id, status=AssetStatus.LISTED)

    response = client.post(f"/investor/assets/{asset_id}/fund", data={})
    assert response.status_code == 302
    with client.session_transaction() as sess:
        flashes = sess.get("_flashes", [])
    assert any("Investment amount is required" in msg for _, msg in flashes)


def test_zero_amount_rejected(client):
    user_id, account = _create_investor(client.application)
    _login(client, user_id, account)

    with client.application.app_context():
        asset_id = _create_asset(client.application, user_id, status=AssetStatus.LISTED)

    response = client.post(
        f"/investor/assets/{asset_id}/fund",
        data={"amount": "0"},
    )
    assert response.status_code == 302
    with client.session_transaction() as sess:
        flashes = sess.get("_flashes", [])
    assert any("Amount must be greater than zero" in msg for _, msg in flashes)


def test_negative_amount_rejected(client):
    user_id, account = _create_investor(client.application)
    _login(client, user_id, account)

    with client.application.app_context():
        asset_id = _create_asset(client.application, user_id, status=AssetStatus.LISTED)

    response = client.post(
        f"/investor/assets/{asset_id}/fund",
        data={"amount": "-10"},
    )
    assert response.status_code == 302
    with client.session_transaction() as sess:
        flashes = sess.get("_flashes", [])
    assert any("Amount must be greater than zero" in msg for _, msg in flashes)


def test_missing_blockchain_asset_id_blocks_funding(client):
    user_id, account = _create_investor(client.application)
    _login(client, user_id, account)

    with client.application.app_context():
        asset_id = _create_asset(client.application, user_id, status=AssetStatus.LISTED, blockchain_asset_id=None)

    response = client.post(
        f"/investor/assets/{asset_id}/fund",
        data={"amount": "100"},
    )
    assert response.status_code == 302
    with client.session_transaction() as sess:
        flashes = sess.get("_flashes", [])
    assert any("not yet been registered on the blockchain" in msg for _, msg in flashes)


def test_valid_funding_calls_prepare_and_fund(client):
    user_id, account = _create_investor(client.application)
    _login(client, user_id, account)

    with client.application.app_context():
        asset_id = _create_asset(client.application, user_id, status=AssetStatus.LISTED)

    mock_result = FundingResult(
        funded=True,
        asset_id=1,
        requested_amount=100000000,
        transaction_hash="0x" + "aa" * 32,
        block_number=12345,
        gas_used=21000,
        events={"AssetFunded": {"assetId": 1, "investor": "0x" + "b" * 40, "amount": 100, "logIndex": 0}},
        message="Funding transaction successful",
    )
    with patch("investor.routes.prepare_and_fund", return_value=mock_result) as mock_fund:
        response = client.post(
            f"/investor/assets/{asset_id}/fund",
            data={"amount": "100"},
        )
    assert response.status_code == 302
    mock_fund.assert_called_once()
    args, kwargs = mock_fund.call_args
    assert args[0] == 1
    assert args[1] == 100000000


def test_successful_funding_redirects_with_success(client):
    user_id, account = _create_investor(client.application)
    _login(client, user_id, account)

    with client.application.app_context():
        asset_id = _create_asset(client.application, user_id, status=AssetStatus.LISTED)

    mock_result = FundingResult(
        funded=True,
        asset_id=1,
        requested_amount=100000000,
        transaction_hash="0x" + "aa" * 32,
        block_number=12345,
        gas_used=21000,
        events={"AssetFunded": {"assetId": 1, "investor": "0x" + "b" * 40, "amount": 100, "logIndex": 0}},
        message="Funding transaction successful",
    )
    with patch("investor.routes.prepare_and_fund", return_value=mock_result):
        response = client.post(
            f"/investor/assets/{asset_id}/fund",
            data={"amount": "100"},
        )
    assert response.status_code == 302
    assert response.headers["Location"] == f"/investor/assets/{asset_id}"
    with client.session_transaction() as sess:
        flashes = sess.get("_flashes", [])
    assert any("Investment submitted successfully" in msg for _, msg in flashes)
    assert any("0x" + "aa" * 32 in msg for _, msg in flashes)


def test_failed_funding_does_not_create_fake_investment(client):
    user_id, account = _create_investor(client.application)
    _login(client, user_id, account)

    with client.application.app_context():
        asset_id = _create_asset(client.application, user_id, status=AssetStatus.LISTED)

    mock_result = FundingResult(
        funded=False,
        asset_id=1,
        requested_amount=100000000,
        message="Funding transaction failed",
    )
    with patch("investor.routes.prepare_and_fund", return_value=mock_result):
        response = client.post(
            f"/investor/assets/{asset_id}/fund",
            data={"amount": "100"},
        )
    assert response.status_code == 302
    with client.application.app_context():
        assert Investment.query.first() is None
        assert BlockchainTransaction.query.first() is None


def test_configuration_error_handled_safely(client):
    user_id, account = _create_investor(client.application)
    _login(client, user_id, account)

    with client.application.app_context():
        asset_id = _create_asset(client.application, user_id, status=AssetStatus.LISTED)

    mock_result = FundingResult(
        funded=False,
        asset_id=1,
        requested_amount=100000000,
        message="Financing pool configuration error",
    )
    with patch("investor.routes.prepare_and_fund", return_value=mock_result):
        response = client.post(
            f"/investor/assets/{asset_id}/fund",
            data={"amount": "100"},
        )
    assert response.status_code == 302
    with client.session_transaction() as sess:
        flashes = sess.get("_flashes", [])
    all_messages = " ".join(msg for _, msg in flashes)
    assert "RPC_URL" not in all_messages
    assert "PRIVATE_KEY" not in all_messages
    assert "Authorization" not in all_messages
    assert "Bearer" not in all_messages


def test_transaction_error_handled_safely(client):
    user_id, account = _create_investor(client.application)
    _login(client, user_id, account)

    with client.application.app_context():
        asset_id = _create_asset(client.application, user_id, status=AssetStatus.LISTED)

    mock_result = FundingResult(
        funded=False,
        asset_id=1,
        requested_amount=100000000,
        message="Funding transaction failed: Transaction reverted: 0xabc",
    )
    with patch("investor.routes.prepare_and_fund", return_value=mock_result):
        response = client.post(
            f"/investor/assets/{asset_id}/fund",
            data={"amount": "100"},
        )
    assert response.status_code == 302
    with client.session_transaction() as sess:
        flashes = sess.get("_flashes", [])
    all_messages = " ".join(msg for _, msg in flashes)
    assert "Funding transaction failed" in all_messages


def test_non_investor_role_forbidden(client):
    user_id, account = _create_investor(client.application)
    _login(client, user_id, account)

    with client.application.app_context():
        user = User.query.get(user_id)
        user.role = UserRole.BORROWER
        db.session.commit()
        asset_id = _create_asset(client.application, user_id, status=AssetStatus.LISTED)

    response = client.get(f"/investor/assets/{asset_id}")
    assert response.status_code == 403

    response = client.post(
        f"/investor/assets/{asset_id}/fund",
        data={"amount": "100"},
    )
    assert response.status_code == 403


def test_investor_cannot_fund_non_fundable_asset(client):
    user_id, account = _create_investor(client.application)
    _login(client, user_id, account)

    with client.application.app_context():
        asset_id = _create_asset(client.application, user_id, status=AssetStatus.FULLY_FUNDED)

    response = client.post(
        f"/investor/assets/{asset_id}/fund",
        data={"amount": "100"},
    )
    assert response.status_code == 302
    with client.session_transaction() as sess:
        flashes = sess.get("_flashes", [])
    assert any("not currently open for funding" in msg for _, msg in flashes)


def test_successful_funding_creates_investment(client):
    user_id, account = _create_investor(client.application)
    _login(client, user_id, account)

    with client.application.app_context():
        asset_id = _create_asset(client.application, user_id, status=AssetStatus.LISTED)

    mock_result = FundingResult(
        funded=True,
        asset_id=1,
        requested_amount=100000000,
        transaction_hash="0x" + "aa" * 32,
        block_number=12345,
        gas_used=21000,
        events={"AssetFunded": {"assetId": 1, "investor": "0x" + "b" * 40, "amount": 100, "logIndex": 0}},
        message="Funding transaction successful",
    )
    with patch("investor.routes.prepare_and_fund", return_value=mock_result):
        response = client.post(
            f"/investor/assets/{asset_id}/fund",
            data={"amount": "100"},
        )
    assert response.status_code == 302

    with client.application.app_context():
        investment = Investment.query.first()
        assert investment is not None
        assert investment.user_id == user_id
        assert investment.asset_id == asset_id
        assert investment.amount == Decimal("100")
        assert investment.tx_hash == "0x" + "aa" * 32
        assert investment.log_index == 0
        assert investment.status == InvestmentStatus.CONFIRMED


def test_successful_funding_creates_blockchain_transaction(client):
    user_id, account = _create_investor(client.application)
    _login(client, user_id, account)

    with client.application.app_context():
        asset_id = _create_asset(client.application, user_id, status=AssetStatus.LISTED)

    mock_result = FundingResult(
        funded=True,
        asset_id=1,
        requested_amount=100000000,
        transaction_hash="0x" + "bb" * 32,
        block_number=12345,
        gas_used=21000,
        events={"AssetFunded": {"assetId": 1, "investor": "0x" + "b" * 40, "amount": 100, "logIndex": 0}},
        message="Funding transaction successful",
    )
    with patch("investor.routes.prepare_and_fund", return_value=mock_result):
        response = client.post(
            f"/investor/assets/{asset_id}/fund",
            data={"amount": "100"},
        )
    assert response.status_code == 302

    with client.application.app_context():
        btx = BlockchainTransaction.query.first()
        assert btx is not None
        assert btx.tx_hash == "0x" + "bb" * 32
        assert btx.log_index == 0
        assert btx.tx_type == TransactionType.FUND
        assert btx.asset_id == asset_id
        assert btx.status == TransactionStatus.CONFIRMED
        assert btx.block_number == 12345
        assert btx.gas_used == 21000


def test_duplicate_investment_is_not_created(client):
    user_id, account = _create_investor(client.application)
    _login(client, user_id, account)

    with client.application.app_context():
        asset_id = _create_asset(client.application, user_id, status=AssetStatus.LISTED)

    mock_result = FundingResult(
        funded=True,
        asset_id=1,
        requested_amount=100000000,
        transaction_hash="0x" + "cc" * 32,
        block_number=12345,
        gas_used=21000,
        events={"AssetFunded": {"assetId": 1, "investor": "0x" + "b" * 40, "amount": 100, "logIndex": 0}},
        message="Funding transaction successful",
    )
    with patch("investor.routes.prepare_and_fund", return_value=mock_result):
        client.post(
            f"/investor/assets/{asset_id}/fund",
            data={"amount": "100"},
        )
        client.post(
            f"/investor/assets/{asset_id}/fund",
            data={"amount": "100"},
        )

    with client.application.app_context():
        investments = Investment.query.filter_by(tx_hash="0x" + "cc" * 32, log_index=0).all()
        assert len(investments) == 1

        btxs = BlockchainTransaction.query.filter_by(tx_hash="0x" + "cc" * 32, log_index=0).all()
        assert len(btxs) == 1


def test_missing_event_log_index_does_not_fabricate_persistence(client):
    user_id, account = _create_investor(client.application)
    _login(client, user_id, account)

    with client.application.app_context():
        asset_id = _create_asset(client.application, user_id, status=AssetStatus.LISTED)

    mock_result = FundingResult(
        funded=True,
        asset_id=1,
        requested_amount=100000000,
        transaction_hash="0x" + "dd" * 32,
        block_number=12345,
        gas_used=21000,
        events={},
        message="Funding transaction successful",
    )
    with patch("investor.routes.prepare_and_fund", return_value=mock_result):
        response = client.post(
            f"/investor/assets/{asset_id}/fund",
            data={"amount": "100"},
        )
    assert response.status_code == 302

    with client.application.app_context():
        assert Investment.query.first() is None
        assert BlockchainTransaction.query.first() is None


def test_failed_transaction_creates_no_investment_or_blockchain_tx(client):
    user_id, account = _create_investor(client.application)
    _login(client, user_id, account)

    with client.application.app_context():
        asset_id = _create_asset(client.application, user_id, status=AssetStatus.LISTED)

    mock_result = FundingResult(
        funded=False,
        asset_id=1,
        requested_amount=100000000,
        message="Funding transaction failed",
    )
    with patch("investor.routes.prepare_and_fund", return_value=mock_result):
        response = client.post(
            f"/investor/assets/{asset_id}/fund",
            data={"amount": "100"},
        )
    assert response.status_code == 302

    with client.application.app_context():
        assert Investment.query.first() is None
        assert BlockchainTransaction.query.first() is None
