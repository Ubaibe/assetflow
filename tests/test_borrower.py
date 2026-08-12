import hashlib
import io
import os
import tempfile
import pytest
from decimal import Decimal
from datetime import datetime, timedelta
from pathlib import Path
from werkzeug.datastructures import FileStorage

from app import create_app
from database import db
from database.models import User, Wallet, Asset, InvoiceDocument, BlockchainTransaction
from database.enums import AssetStatus
from database.state_machine import transition, InvalidStatusTransition


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    with tempfile.TemporaryDirectory() as tmpdir:
        app.config["UPLOAD_DIR"] = tmpdir
        with app.app_context():
            db.create_all()
        yield app
        with app.app_context():
            db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_headers():
    return {"Content-Type": "application/json"}


def _create_user(app, email="test@example.com"):
    with app.app_context():
        from eth_account import Account
        account = Account.create()
        user = User(email=email, password_hash=None, role=None)
        db.session.add(user)
        db.session.commit()

        wallet = Wallet(user_id=user.id, address=account.address, chain_id=1)
        db.session.add(wallet)
        db.session.commit()

        return user.id, account


def _login(client, user_id, account):
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

    with client.session_transaction() as sess:
        print(f"After _login({user_id}): _user_id={sess.get('_user_id')}")


def _make_file_storage(content: bytes, filename: str, content_type: str) -> FileStorage:
    return FileStorage(stream=io.BytesIO(content), filename=filename, content_type=content_type)


def _make_pdf_bytes(content: bytes = b"test pdf") -> bytes:
    return b"%PDF-1.4\n" + content


def _make_png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


def _make_jpeg_bytes() -> bytes:
    return b"\xff\xd8\xff\xe0" + b"\x00" * 100


def test_borrower_dashboard_requires_auth(client):
    response = client.get("/borrower/dashboard")
    assert response.status_code == 401


def test_authenticated_user_can_access_borrower_dashboard(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)
    response = client.get("/borrower/dashboard")
    assert response.status_code == 200
    assert b"Borrower Dashboard" in response.data


def test_upload_page_requires_auth(client):
    response = client.get("/borrower/assets/new")
    assert response.status_code == 401


def test_valid_pdf_upload_succeeds(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_pdf_bytes()
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }

    response = client.post(
        "/borrower/assets",
        data=data,
    )
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/borrower/assets/")

    with client.application.app_context():
        asset = Asset.query.first()
        assert asset is not None
        assert asset.user_id == user_id
        assert asset.status == AssetStatus.DRAFT
        assert len(asset.documents) == 1


def test_valid_png_upload_succeeds(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    png_bytes = _make_png_bytes()
    data = {
        "invoice": _make_file_storage(png_bytes, "invoice.png", "image/png"),
    }

    response = client.post(
        "/borrower/assets",
        data=data,
    )
    assert response.status_code == 302


def test_valid_jpeg_upload_succeeds(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    jpeg_bytes = _make_jpeg_bytes()
    data = {
        "invoice": _make_file_storage(jpeg_bytes, "invoice.jpg", "image/jpeg"),
    }

    response = client.post(
        "/borrower/assets",
        data=data,
    )
    assert response.status_code == 302


def test_unsupported_extension_rejected(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    data = {
        "invoice": _make_file_storage(b"hello", "invoice.txt", "text/plain"),
    }
    response = client.post(
        "/borrower/assets",
        data=data,
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/borrower/assets/new"
    with client.session_transaction() as sess:
        flashes = sess.get("_flashes", [])
    assert any("Unsupported file extension" in msg for _, msg in flashes)


def test_mime_mismatch_rejected(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_pdf_bytes()
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "image/png"),
    }
    response = client.post(
        "/borrower/assets",
        data=data,
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/borrower/assets/new"
    with client.session_transaction() as sess:
        flashes = sess.get("_flashes", [])
    assert any("MIME type mismatch" in msg for _, msg in flashes)


def test_magic_byte_mismatch_rejected(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    data = {
        "invoice": _make_file_storage(b"hello world", "invoice.pdf", "application/pdf"),
    }
    response = client.post(
        "/borrower/assets",
        data=data,
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/borrower/assets/new"
    with client.session_transaction() as sess:
        flashes = sess.get("_flashes", [])
    assert any("File content does not match declared type" in msg for _, msg in flashes)


def test_oversized_upload_rejected(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    client.application.config["MAX_UPLOAD_MB"] = 1
    large_content = b"%PDF-1.4\n" + b"A" * (2 * 1024 * 1024)
    data = {
        "invoice": _make_file_storage(large_content, "big.pdf", "application/pdf"),
    }
    response = client.post(
        "/borrower/assets",
        data=data,
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/borrower/assets/new"
    with client.session_transaction() as sess:
        flashes = sess.get("_flashes", [])
    assert any("exceeds maximum size" in msg for _, msg in flashes)


def test_uploaded_file_receives_server_generated_filename(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_pdf_bytes()
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    client.post(
        "/borrower/assets",
        data=data,
    )

    with client.application.app_context():
        doc = InvoiceDocument.query.first()
        assert doc is not None
        assert doc.stored_filename != "invoice.pdf"
        assert doc.stored_filename.endswith(".pdf")
        assert len(doc.stored_filename) > 30


def test_original_filename_stored_safely(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_pdf_bytes()
    data = {
        "invoice": _make_file_storage(pdf_bytes, "my-invoice.pdf", "application/pdf"),
    }
    client.post(
        "/borrower/assets",
        data=data,
    )

    with client.application.app_context():
        doc = InvoiceDocument.query.first()
        assert doc is not None
        assert doc.original_filename == "my-invoice.pdf"


def test_upload_stored_outside_static(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_pdf_bytes()
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    client.post(
        "/borrower/assets",
        data=data,
    )

    with client.application.app_context():
        doc = InvoiceDocument.query.first()
        assert doc is not None
        upload_dir = Path(client.application.config["UPLOAD_DIR"])
        file_path = upload_dir / doc.stored_filename
        assert file_path.exists()
        assert str(file_path).startswith(str(upload_dir))


def test_asset_associated_with_authenticated_user(client):
    user_id, account = _create_user(client.application, email="owner@example.com")
    _login(client, user_id, account)

    pdf_bytes = _make_pdf_bytes()
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    client.post(
        "/borrower/assets",
        data=data,
    )

    with client.application.app_context():
        asset = Asset.query.first()
        assert asset is not None
        assert asset.user_id == user_id
        assert asset.borrower.id == user_id


def test_invoice_document_associated_with_correct_asset(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_pdf_bytes()
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    client.post(
        "/borrower/assets",
        data=data,
    )

    with client.application.app_context():
        asset = Asset.query.first()
        doc = InvoiceDocument.query.first()
        assert asset is not None
        assert doc is not None
        assert doc.asset_id == asset.id
        assert doc.asset.asset_hash == asset.asset_hash


def test_sha256_hash_calculated_from_actual_bytes(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    content = b"unique test content for hashing"
    pdf_bytes = b"%PDF-1.4\n" + content
    data = {
        "invoice": _make_file_storage(pdf_bytes, "hash.pdf", "application/pdf"),
    }
    client.post(
        "/borrower/assets",
        data=data,
    )

    with client.application.app_context():
        doc = InvoiceDocument.query.first()
        assert doc is not None
        expected_hash = hashlib.sha256(pdf_bytes).hexdigest()
        assert doc.file_hash == expected_hash


def test_same_file_uploaded_twice_rejected(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_pdf_bytes()
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }

    response1 = client.post(
        "/borrower/assets",
        data=data,
    )
    assert response1.status_code == 302

    pdf_bytes = _make_pdf_bytes()
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    response2 = client.post(
        "/borrower/assets",
        data=data,
    )
    assert response2.status_code == 302
    assert response2.headers["Location"] == "/borrower/assets/new"
    with client.session_transaction() as sess:
        flashes = sess.get("_flashes", [])
    assert any("already been uploaded" in msg for _, msg in flashes)


def test_another_users_asset_cannot_be_accessed(client):
    user1_id, account1 = _create_user(client.application, email="user1@example.com")
    user2_id, account2 = _create_user(client.application, email="user2@example.com")

    _login(client, user1_id, account1)

    pdf_bytes = _make_pdf_bytes()
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    client.post(
        "/borrower/assets",
        data=data,
    )

    with client.application.app_context():
        asset = Asset.query.first()
        asset_id = asset.id

    client2 = client.application.test_client()
    _login(client2, user2_id, account2)
    response = client2.get(f"/borrower/assets/{asset_id}")
    assert response.status_code == 404


def test_another_users_document_cannot_be_downloaded(client):
    user1_id, account1 = _create_user(client.application, email="user1@example.com")
    user2_id, account2 = _create_user(client.application, email="user2@example.com")

    _login(client, user1_id, account1)

    pdf_bytes = _make_pdf_bytes()
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    client.post(
        "/borrower/assets",
        data=data,
    )

    with client.application.app_context():
        asset = Asset.query.first()
        asset_id = asset.id

    client2 = client.application.test_client()
    _login(client2, user2_id, account2)
    response = client2.get(f"/borrower/assets/{asset_id}/document")
    assert response.status_code == 404


def test_upload_failure_does_not_leave_orphaned_file(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    from unittest.mock import patch
    from services.upload import UploadError

    def failing_save(*args, **kwargs):
        raise UploadError("Simulated save failure")

    with patch("borrower.routes.validate_and_save_upload", side_effect=failing_save):
        pdf_bytes = _make_pdf_bytes()
        data = {
            "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
        }
        response = client.post(
            "/borrower/assets",
            data=data,
        )
        assert response.status_code == 302
        assert response.headers["Location"] == "/borrower/assets/new"
        with client.session_transaction() as sess:
            flashes = sess.get("_flashes", [])
        assert any("Simulated save failure" in msg for _, msg in flashes)

    with client.application.app_context():
        upload_dir = Path(client.application.config["UPLOAD_DIR"])
        files = list(upload_dir.glob("*"))
        assert len(files) == 0


def test_upload_does_not_create_blockchain_transaction(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_pdf_bytes()
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    client.post(
        "/borrower/assets",
        data=data,
    )

    with client.application.app_context():
        txs = BlockchainTransaction.query.all()
        assert len(txs) == 0


def test_asset_remains_in_initial_offchain_state(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_pdf_bytes()
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    client.post(
        "/borrower/assets",
        data=data,
    )

    with client.application.app_context():
        asset = Asset.query.first()
        assert asset is not None
        assert asset.status == AssetStatus.DRAFT
        assert asset.asset_hash is not None
        assert asset.id is not None
