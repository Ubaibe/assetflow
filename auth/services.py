import uuid
from datetime import datetime, timedelta, timezone
from eth_account.messages import encode_defunct
from eth_account import Account
from eth_utils import to_checksum_address
from sqlalchemy.exc import IntegrityError
from database import db
from database.models import User, Wallet, Challenge


class AuthError(Exception):
    pass


def _normalize_address(address: str) -> str:
    try:
        return to_checksum_address(address)
    except Exception:
        raise AuthError("Malformed wallet address")


def _now() -> datetime:
    return datetime.utcnow()


def generate_challenge_message(wallet_address: str, nonce: str, issued_at: datetime, expires_at: datetime) -> str:
    return (
        f"AssetFlow Authentication\n"
        f"Wallet: {wallet_address}\n"
        f"Nonce: {nonce}\n"
        f"Issued: {issued_at.isoformat()}\n"
        f"Expires: {expires_at.isoformat()}"
    )


def create_challenge(wallet_address: str) -> dict:
    wallet_address = _normalize_address(wallet_address)
    nonce = uuid.uuid4().hex + uuid.uuid4().hex
    challenge_id = uuid.uuid4().hex
    issued_at = _now()
    expires_at = issued_at + timedelta(seconds=300)
    message = generate_challenge_message(wallet_address, nonce, issued_at, expires_at)

    challenge = Challenge(
        id=challenge_id,
        wallet_address=wallet_address,
        nonce=nonce,
        message=message,
        expires_at=expires_at,
    )
    db.session.add(challenge)
    db.session.commit()

    return {
        "challenge_id": challenge.id,
        "wallet_address": wallet_address,
        "message": message,
        "expires_at": expires_at.isoformat(),
    }


def verify_signature(wallet_address: str, signature: str, challenge_id: str) -> User:
    wallet_address = _normalize_address(wallet_address)
    challenge = Challenge.query.get(challenge_id)

    if not challenge:
        raise AuthError("Invalid challenge")

    if challenge.wallet_address != wallet_address:
        raise AuthError("Wallet address mismatch")

    if challenge.consumed_at is not None:
        raise AuthError("Challenge already consumed")

    now = _now()
    if now >= challenge.expires_at:
        raise AuthError("Challenge expired")

    try:
        encoded = encode_defunct(text=challenge.message)
        recovered = Account.recover_message(encoded, signature=signature)
    except Exception:
        raise AuthError("Malformed signature")

    if recovered.lower() != wallet_address.lower():
        raise AuthError("Invalid signature")

    challenge.consumed_at = now

    wallet = Wallet.query.filter_by(address=wallet_address).first()
    if wallet:
        user = User.query.get(wallet.user_id)
    else:
        user = User()
        db.session.add(user)
        db.session.flush()

        wallet = Wallet(user_id=user.id, address=wallet_address)
        db.session.add(wallet)

    db.session.commit()
    return user
