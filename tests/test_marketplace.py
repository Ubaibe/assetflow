import pytest
from decimal import Decimal
from app import create_app
from database import db
from database.models import User, Wallet, Asset, Investment
from database.enums import UserRole, AssetStatus, InvestmentStatus


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def _create_user(app, email="test@example.com", role=None):
    from eth_account import Account
    account = Account.create()
    user = User(email=email, password_hash=None, role=role)
    db.session.add(user)
    db.session.commit()

    wallet = Wallet(user_id=user.id, address=account.address, chain_id=1)
    db.session.add(wallet)
    db.session.commit()

    return user.id, account


def _login(client, user_id, account):
    from auth.services import create_challenge
    from eth_account.messages import encode_defunct

    user = User.query.get(user_id)
    wallet = user.wallets[0]
    challenge = create_challenge(wallet.address)
    encoded = encode_defunct(text=challenge["message"])
    signature = account.sign_message(encoded).signature.hex()

    response = client.post("/auth/verify", json={
        "wallet_address": wallet.address,
        "signature": signature,
        "challenge_id": challenge["challenge_id"],
    })
    assert response.status_code == 200


def test_unauthenticated_marketplace_redirects_to_auth(client):
    response = client.get(
        "/marketplace/",
        headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
    )
    assert response.status_code == 302
    assert "/auth/" in response.headers["Location"]


def test_authenticated_investor_can_access_marketplace(client):
    user_id, account = _create_user(client.application, email="investor@test.com", role=UserRole.INVESTOR)
    _login(client, user_id, account)

    response = client.get("/marketplace/")
    assert response.status_code == 200
    assert b"Marketplace" in response.data


def test_authenticated_borrower_can_access_marketplace(client):
    user_id, account = _create_user(client.application, email="borrower@test.com", role=UserRole.BORROWER)
    _login(client, user_id, account)

    response = client.get("/marketplace/")
    assert response.status_code == 200
    assert b"Marketplace" in response.data


def test_marketplace_uses_real_database_assets(client):
    investor_id, investor_account = _create_user(
        client.application, email="investor@test.com", role=UserRole.INVESTOR
    )
    _login(client, investor_id, investor_account)

    with client.application.app_context():
        asset = Asset(
            user_id=investor_id,
            asset_hash="0x" + "a" * 64,
            status=AssetStatus.LISTED,
            invoice_number="INV-001",
            face_value=Decimal("1000.00"),
            financing_target=Decimal("5000.00"),
            currency="USD",
        )
        db.session.add(asset)
        db.session.commit()
        asset_id = asset.id

    response = client.get("/marketplace/")
    assert response.status_code == 200
    html = response.data.decode()
    assert f"Asset #{asset_id}" in html
    assert "INV-001" in html


def test_marketplace_displays_target_funded_remaining(client):
    investor_id, investor_account = _create_user(
        client.application, email="investor@test.com", role=UserRole.INVESTOR
    )
    _login(client, investor_id, investor_account)

    with client.application.app_context():
        asset = Asset(
            user_id=investor_id,
            asset_hash="0x" + "b" * 64,
            status=AssetStatus.PARTIALLY_FUNDED,
            invoice_number="INV-002",
            face_value=Decimal("2000.00"),
            financing_target=Decimal("10000.00"),
            currency="USD",
        )
        db.session.add(asset)
        db.session.flush()

        investment = Investment(
            user_id=investor_id,
            asset_id=asset.id,
            amount=Decimal("3500.00"),
            tx_hash="0x" + "c" * 64,
            log_index=0,
            status=InvestmentStatus.CONFIRMED,
        )
        db.session.add(investment)
        db.session.commit()

    response = client.get("/marketplace/")
    assert response.status_code == 200
    html = response.data.decode()

    assert "Target Amount" in html
    assert "10,000" in html or "10000" in html
    assert "Funded" in html
    assert "3,500" in html or "3500" in html
    assert "Remaining" in html
    assert "6,500" in html or "6500" in html
    assert "35.0% funded" in html or "35% funded" in html


def test_marketplace_borrower_cannot_fund(client):
    borrower_id, borrower_account = _create_user(
        client.application, email="borrower@test.com", role=UserRole.BORROWER
    )
    _login(client, borrower_id, borrower_account)

    with client.application.app_context():
        asset = Asset(
            user_id=borrower_id,
            asset_hash="0x" + "d" * 64,
            status=AssetStatus.LISTED,
            invoice_number="INV-003",
            face_value=Decimal("1000.00"),
            financing_target=Decimal("5000.00"),
            currency="USD",
        )
        db.session.add(asset)
        db.session.commit()
        asset_id = asset.id

    response = client.get("/marketplace/")
    assert response.status_code == 200
    html = response.data.decode()
    assert f"Asset #{asset_id}" in html

    response = client.post(f"/investor/assets/{asset_id}/fund", data={"amount": "100"})
    assert response.status_code == 403


def test_marketplace_progress_clamped_at_100(client):
    investor_id, investor_account = _create_user(
        client.application, email="investor2@test.com", role=UserRole.INVESTOR
    )
    _login(client, investor_id, investor_account)

    with client.application.app_context():
        asset = Asset(
            user_id=investor_id,
            asset_hash="0x" + "e" * 64,
            status=AssetStatus.FULLY_FUNDED,
            invoice_number="INV-004",
            face_value=Decimal("1000.00"),
            financing_target=Decimal("5000.00"),
            currency="USD",
        )
        db.session.add(asset)
        db.session.flush()

        investment = Investment(
            user_id=investor_id,
            asset_id=asset.id,
            amount=Decimal("5000.00"),
            tx_hash="0x" + "f" * 64,
            log_index=0,
            status=InvestmentStatus.CONFIRMED,
        )
        db.session.add(investment)
        db.session.commit()

    response = client.get("/marketplace/")
    assert response.status_code == 200
    html = response.data.decode()
    assert "100.0% funded" in html or "100% funded" in html


def test_marketplace_shows_empty_state_when_no_assets(client):
    investor_id, investor_account = _create_user(
        client.application, email="investor3@test.com", role=UserRole.INVESTOR
    )
    _login(client, investor_id, investor_account)

    response = client.get("/marketplace/")
    assert response.status_code == 200
    html = response.data.decode()
    assert "No financing opportunities available right now" in html
