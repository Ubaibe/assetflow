import pytest
from eth_account import Account
from eth_utils import to_checksum_address

from app import create_app
from database import db
from database.models import User, Wallet
from database.enums import UserRole
from auth.services import create_challenge
from eth_account.messages import encode_defunct


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


@pytest.fixture(scope="session")
def test_account():
    return Account.create()


def _create_user(app, role, account):
    with app.app_context():
        user = User(role=role)
        db.session.add(user)
        db.session.flush()
        wallet = Wallet(
            user_id=user.id,
            address=to_checksum_address(account.address),
            chain_id=1,
        )
        db.session.add(wallet)
        db.session.commit()
        return user.id


def _login(client, user_id, account):
    with client.application.app_context():
        user = User.query.get(user_id)
        wallet = user.wallets[0]
        challenge = create_challenge(wallet.address)
        encoded = encode_defunct(text=challenge["message"])
        signature = account.sign_message(encoded).signature.hex()
        response = client.post(
            "/auth/verify",
            json={
                "wallet_address": wallet.address,
                "signature": signature,
                "challenge_id": challenge["challenge_id"],
            },
        )
        assert response.status_code == 200


def test_public_landing_page_returns_200(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"AssetFlow" in response.data


def test_landing_page_contains_auth_navigation_links(client):
    response = client.get("/")
    html = response.data.decode()
    assert "/auth/?next=/investor/dashboard" in html
    assert "/auth/?next=/borrower/dashboard" in html
    assert "https://scan.bohr.life" in html
    assert "https://github.com/Ubaibe/assetflow" in html


def test_protected_investor_route_returns_json_401_for_api(client):
    response = client.get("/investor/dashboard", headers={"Accept": "application/json"})
    assert response.status_code == 401
    assert b"Unauthorized" in response.data


def test_protected_borrower_route_returns_json_401_for_api(client):
    response = client.get("/borrower/dashboard", headers={"Accept": "application/json"})
    assert response.status_code == 401
    assert b"Unauthorized" in response.data


def test_unauthenticated_browser_redirects_to_login_for_investor(client):
    response = client.get(
        "/investor/dashboard",
        headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
    )
    assert response.status_code == 302
    assert "/auth/" in response.headers.get("Location", "")
    assert "next=" in response.headers.get("Location", "")


def test_unauthenticated_browser_redirects_to_login_for_borrower(client):
    response = client.get(
        "/borrower/dashboard",
        headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
    )
    assert response.status_code == 302
    assert "/auth/" in response.headers.get("Location", "")
    assert "next=" in response.headers.get("Location", "")


def test_login_page_renders_with_next_param(client):
    response = client.get("/auth/?next=/investor/dashboard")
    assert response.status_code == 200
    assert b"Connect Wallet" in response.data


def test_successful_authentication_preserves_destination(client, app, test_account):
    response = client.get(
        "/investor/dashboard",
        headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
    )
    assert response.status_code == 302
    location = response.headers.get("Location", "")
    assert "/auth/?next=" in location
    assert "/investor/dashboard" in location


def test_investor_role_forbidden_from_borrower_routes(client, app, test_account):
    user_id = _create_user(app, UserRole.INVESTOR, test_account)
    _login(client, user_id, test_account)
    response = client.get("/borrower/dashboard")
    assert response.status_code in (200, 403, 404)


def test_borrower_role_forbidden_from_investor_routes(client, app, test_account):
    user_id = _create_user(app, UserRole.BORROWER, test_account)
    _login(client, user_id, test_account)
    response = client.get("/investor/dashboard")
    assert response.status_code == 403


def test_unauthenticated_cannot_access_onboarding(client):
    response = client.get("/auth/onboarding")
    assert response.status_code == 401


def test_authenticated_user_with_no_role_can_access_onboarding(client, test_account):
    with client:
        wallet = to_checksum_address(test_account.address)
        challenge = client.post("/auth/challenge", json={"wallet_address": wallet}).get_json()
        encoded = encode_defunct(text=challenge["message"])
        signature = test_account.sign_message(encoded).signature.hex()
        client.post("/auth/verify", json={
            "wallet_address": wallet,
            "signature": signature,
            "challenge_id": challenge["challenge_id"],
        })
        response = client.get("/auth/onboarding")
        assert response.status_code == 200
        assert b"Welcome to AssetFlow" in response.data


def test_authenticated_investor_is_redirected_from_onboarding(client, app, test_account):
    user_id = _create_user(app, UserRole.INVESTOR, test_account)
    _login(client, user_id, test_account)
    response = client.get("/auth/onboarding")
    assert response.status_code == 302
    assert "/investor/dashboard" in response.headers.get("Location", "")


def test_authenticated_borrower_is_redirected_from_onboarding(client, app, test_account):
    user_id = _create_user(app, UserRole.BORROWER, test_account)
    _login(client, user_id, test_account)
    response = client.get("/auth/onboarding")
    assert response.status_code == 302
    assert "/borrower/dashboard" in response.headers.get("Location", "")


def test_onboarding_role_selection_persists_investor(client, test_account):
    with client:
        wallet = to_checksum_address(test_account.address)
        challenge = client.post("/auth/challenge", json={"wallet_address": wallet}).get_json()
        encoded = encode_defunct(text=challenge["message"])
        signature = test_account.sign_message(encoded).signature.hex()
        client.post("/auth/verify", json={
            "wallet_address": wallet,
            "signature": signature,
            "challenge_id": challenge["challenge_id"],
        })
        response = client.post("/auth/onboarding/role", json={"role": "investor"})
        assert response.status_code == 200
        assert response.get_json()["role"] == "investor"


def test_onboarding_role_selection_persists_borrower(client, test_account):
    with client:
        wallet = to_checksum_address(test_account.address)
        challenge = client.post("/auth/challenge", json={"wallet_address": wallet}).get_json()
        encoded = encode_defunct(text=challenge["message"])
        signature = test_account.sign_message(encoded).signature.hex()
        client.post("/auth/verify", json={
            "wallet_address": wallet,
            "signature": signature,
            "challenge_id": challenge["challenge_id"],
        })
        response = client.post("/auth/onboarding/role", json={"role": "borrower"})
        assert response.status_code == 200
        assert response.get_json()["role"] == "borrower"


def test_onboarding_rejects_invalid_role(client, test_account):
    with client:
        wallet = to_checksum_address(test_account.address)
        challenge = client.post("/auth/challenge", json={"wallet_address": wallet}).get_json()
        encoded = encode_defunct(text=challenge["message"])
        signature = test_account.sign_message(encoded).signature.hex()
        client.post("/auth/verify", json={
            "wallet_address": wallet,
            "signature": signature,
            "challenge_id": challenge["challenge_id"],
        })
        response = client.post("/auth/onboarding/role", json={"role": "hacker"})
        assert response.status_code == 400


def test_onboarding_rejects_unauthenticated_role_assignment(client):
    response = client.post("/auth/onboarding/role", json={"role": "investor"})
    assert response.status_code == 401


def test_onboarding_does_not_overwrite_existing_role(client, app, test_account):
    user_id = _create_user(app, UserRole.INVESTOR, test_account)
    _login(client, user_id, test_account)
    response = client.post("/auth/onboarding/role", json={"role": "borrower"})
    assert response.status_code == 409


def test_onboarding_preserves_next_safely(client, test_account):
    with client:
        wallet = to_checksum_address(test_account.address)
        challenge = client.post("/auth/challenge", json={"wallet_address": wallet}).get_json()
        encoded = encode_defunct(text=challenge["message"])
        signature = test_account.sign_message(encoded).signature.hex()
        client.post("/auth/verify", json={
            "wallet_address": wallet,
            "signature": signature,
            "challenge_id": challenge["challenge_id"],
        })
        response = client.post("/auth/onboarding/role", json={"role": "investor", "next": "/investor/dashboard"})
        assert response.status_code == 200
        assert response.get_json()["next"] == "/investor/dashboard"


def test_onboarding_rejects_external_next(client, test_account):
    with client:
        wallet = to_checksum_address(test_account.address)
        challenge = client.post("/auth/challenge", json={"wallet_address": wallet}).get_json()
        encoded = encode_defunct(text=challenge["message"])
        signature = test_account.sign_message(encoded).signature.hex()
        client.post("/auth/verify", json={
            "wallet_address": wallet,
            "signature": signature,
            "challenge_id": challenge["challenge_id"],
        })
        response = client.post("/auth/onboarding/role", json={"role": "investor", "next": "https://evil.com"})
        assert response.status_code == 200
        assert response.get_json()["next"] == "/investor/dashboard"

