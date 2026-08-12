import uuid
from datetime import datetime, timedelta, timezone

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import to_checksum_address

from app import create_app
from database import db
from database.models import User, Wallet, Challenge
from auth.services import create_challenge, verify_signature, AuthError, _normalize_address


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


def test_challenge_generation(app, test_account):
    with app.app_context():
        wallet = to_checksum_address(test_account.address)
        result = create_challenge(wallet)
        assert "challenge_id" in result
        assert result["wallet_address"] == wallet
        assert "message" in result
        assert "expires_at" in result


def test_challenge_contains_nonce(app, test_account):
    with app.app_context():
        wallet = to_checksum_address(test_account.address)
        result = create_challenge(wallet)
        assert "Nonce:" in result["message"]


def test_challenge_tied_to_wallet(app, test_account):
    with app.app_context():
        wallet = to_checksum_address(test_account.address)
        result = create_challenge(wallet)
        challenge = Challenge.query.get(result["challenge_id"])
        assert challenge is not None
        assert challenge.wallet_address == wallet


def test_challenge_expires_correctly(app, test_account):
    with app.app_context():
        wallet = to_checksum_address(test_account.address)
        result = create_challenge(wallet)
        expires_at = datetime.fromisoformat(result["expires_at"])
        assert expires_at > datetime.utcnow()
        assert expires_at <= datetime.utcnow() + timedelta(seconds=310)


def test_successful_signature_verification(app, test_account):
    with app.test_request_context():
        wallet = to_checksum_address(test_account.address)
        challenge = create_challenge(wallet)
        encoded = encode_defunct(text=challenge["message"])
        signature = test_account.sign_message(encoded).signature.hex()

        user = verify_signature(wallet, signature, challenge["challenge_id"])
        assert user is not None
        assert user.wallets[0].address == wallet


def test_invalid_signature_rejection(app, test_account):
    with app.test_request_context():
        wallet = to_checksum_address(test_account.address)
        challenge = create_challenge(wallet)

        with pytest.raises(AuthError, match="Invalid signature"):
            verify_signature(wallet, "0x" + "ab" * 65, challenge["challenge_id"])


def test_wrong_wallet_rejection(app, test_account):
    with app.test_request_context():
        attacker = Account.create()
        victim_wallet = to_checksum_address(test_account.address)
        challenge = create_challenge(victim_wallet)

        encoded = encode_defunct(text=challenge["message"])
        signature = attacker.sign_message(encoded).signature.hex()

        with pytest.raises(AuthError, match="Invalid signature"):
            verify_signature(victim_wallet, signature, challenge["challenge_id"])


def test_expired_challenge_rejection(app, test_account):
    with app.app_context():
        wallet = to_checksum_address(test_account.address)
        result = create_challenge(wallet)
        challenge = Challenge.query.get(result["challenge_id"])
        challenge.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()

        with app.test_request_context():
            with pytest.raises(AuthError, match="Challenge expired"):
                verify_signature(wallet, "0x00", challenge.id)


def test_replayed_challenge_rejection(app, test_account):
    with app.test_request_context():
        wallet = to_checksum_address(test_account.address)
        challenge = create_challenge(wallet)
        encoded = encode_defunct(text=challenge["message"])
        signature = test_account.sign_message(encoded).signature.hex()

        verify_signature(wallet, signature, challenge["challenge_id"])

        with pytest.raises(AuthError, match="Challenge already consumed"):
            verify_signature(wallet, signature, challenge["challenge_id"])


def test_malformed_wallet_address_rejection(app):
    with app.app_context():
        with pytest.raises(AuthError, match="Malformed wallet address"):
            create_challenge("not-a-valid-address")


def test_malformed_signature_rejection(app, test_account):
    with app.test_request_context():
        wallet = to_checksum_address(test_account.address)
        challenge = create_challenge(wallet)

        with pytest.raises(AuthError, match="Malformed signature"):
            verify_signature(wallet, "invalid-signature", challenge["challenge_id"])


def test_successful_auth_creates_user(app, test_account):
    with app.test_request_context():
        wallet = to_checksum_address(test_account.address)
        challenge = create_challenge(wallet)
        encoded = encode_defunct(text=challenge["message"])
        signature = test_account.sign_message(encoded).signature.hex()

        user = verify_signature(wallet, signature, challenge["challenge_id"])
        assert user.id is not None
        assert user.wallets[0].address == wallet


def test_wallet_associated_with_user(app, test_account):
    with app.test_request_context():
        wallet = to_checksum_address(test_account.address)
        challenge = create_challenge(wallet)
        encoded = encode_defunct(text=challenge["message"])
        signature = test_account.sign_message(encoded).signature.hex()

        user = verify_signature(wallet, signature, challenge["challenge_id"])
        assert len(user.wallets) == 1
        assert user.wallets[0].address == wallet


def test_existing_user_no_duplicate(app, test_account):
    with app.test_request_context():
        wallet = to_checksum_address(test_account.address)
        challenge1 = create_challenge(wallet)
        encoded1 = encode_defunct(text=challenge1["message"])
        sig1 = test_account.sign_message(encoded1).signature.hex()
        user1 = verify_signature(wallet, sig1, challenge1["challenge_id"])

        challenge2 = create_challenge(wallet)
        encoded2 = encode_defunct(text=challenge2["message"])
        sig2 = test_account.sign_message(encoded2).signature.hex()
        user2 = verify_signature(wallet, sig2, challenge2["challenge_id"])

        assert user1.id == user2.id
        assert len(user2.wallets) == 1


def test_flask_login_session_established(client, test_account):
    with client:
        wallet = to_checksum_address(test_account.address)
        challenge = client.post("/auth/challenge", json={"wallet_address": wallet}).get_json()
        encoded = encode_defunct(text=challenge["message"])
        signature = test_account.sign_message(encoded).signature.hex()

        response = client.post("/auth/verify", json={
            "wallet_address": wallet,
            "signature": signature,
            "challenge_id": challenge["challenge_id"],
        })
        assert response.status_code == 200
        assert response.get_json()["authenticated"] is True


def test_logout_clears_session(client, test_account):
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

        response = client.post("/auth/logout")
        assert response.status_code == 200
        assert response.get_json()["authenticated"] is False


def test_unauthenticated_cannot_access_protected_route(client):
    response = client.get("/borrower/dashboard")
    assert response.status_code == 401


def test_authenticated_user_can_access_borrower_route(client, test_account):
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

        response = client.get("/borrower/dashboard")
        assert response.status_code == 200


def test_authenticated_user_can_access_investor_route(client, test_account):
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

        response = client.get("/investor/dashboard")
        assert response.status_code == 200


def test_challenge_endpoint_missing_wallet(client):
    response = client.post("/auth/challenge", json={})
    assert response.status_code == 400
    assert response.get_json()["error"] == "wallet_address is required"


def test_verify_endpoint_missing_fields(client):
    response = client.post("/auth/verify", json={})
    assert response.status_code == 400
    assert "wallet_address, signature, and challenge_id are required" in response.get_json()["error"]


def test_verify_invalid_challenge_id(client, test_account):
    with client:
        wallet = to_checksum_address(test_account.address)
        response = client.post("/auth/verify", json={
            "wallet_address": wallet,
            "signature": "0x" + "ab" * 65,
            "challenge_id": "nonexistent",
        })
        assert response.status_code == 401
