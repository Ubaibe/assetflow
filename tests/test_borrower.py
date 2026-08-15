import hashlib
import io
import os
import tempfile
import pytest
from decimal import Decimal
from datetime import datetime, date, timedelta
from pathlib import Path
from unittest.mock import patch
from werkzeug.datastructures import FileStorage

from app import create_app
from database import db
from database.models import User, Wallet, Asset, InvoiceDocument, BlockchainTransaction, AIAnalysis
from database.enums import AssetStatus, DocumentStatus
from database.state_machine import transition, InvalidStatusTransition
from services.document_processing import DocumentProcessingResult
from services.invoice_pipeline import InvoicePipelineError, extract_invoice
from services.ai_extraction import InvoiceExtractionResult
from services.invoice_verification import InvoiceVerificationResult
from services.financing_submission import FinancingSubmissionResult, submit_financing


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
    from PIL import Image
    buf = io.BytesIO()
    image = Image.new("RGB", (10, 10), color="red")
    image.save(buf, format="PNG")
    return buf.getvalue()


def _make_jpeg_bytes() -> bytes:
    return b"\xff\xd8\xff\xe0" + b"\x00" * 100


def _make_empty_pdf() -> bytes:
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


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


def _make_minimal_pdf_with_text(text: str = "Invoice #123") -> bytes:
    text_bytes = text.encode("utf-8")
    stream_len = len(text_bytes) + 20

    header = b"%PDF-1.4\n"
    obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    obj2 = b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    obj3 = (
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>\n"
        b"endobj\n"
    )
    obj4 = (
        b"4 0 obj\n"
        b"<< /Length " + str(stream_len).encode() + b" >>\nstream\n"
        b"BT\n/F1 12 Tf\n10 180 Td\n(" + text_bytes + b") Tj\nET\n"
        b"endstream\nendobj\n"
    )
    obj5 = b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"

    body = obj1 + obj2 + obj3 + obj4 + obj5
    xref_offset = len(header) + len(body)
    xref = b"xref\n0 6\n0000000000 65535 f \n"

    off1 = len(header)
    off2 = off1 + len(obj1)
    off3 = off2 + len(obj2)
    off4 = off3 + len(obj3)
    off5 = off4 + len(obj4)

    xref += f"{off1:010d} 00000 n \n".encode()
    xref += f"{off2:010d} 00000 n \n".encode()
    xref += f"{off3:010d} 00000 n \n".encode()
    xref += f"{off4:010d} 00000 n \n".encode()
    xref += f"{off5:010d} 00000 n \n".encode()

    trailer = b"trailer\n<< /Size 6 /Root 1 0 R >>\n"
    startxref = b"startxref\n" + str(xref_offset).encode() + b"\n"
    eof = b"%%EOF\n"

    return header + body + xref + trailer + startxref + eof


def test_text_pdf_upload_sets_processing_mode_text(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC\nTotal: $100.00")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302

    with client.application.app_context():
        doc = InvoiceDocument.query.first()
        assert doc is not None
        assert doc.processing_mode == "text"


def test_image_upload_sets_processing_mode_vision(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    png_bytes = _make_png_bytes()
    data = {
        "invoice": _make_file_storage(png_bytes, "invoice.png", "image/png"),
    }
    response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302

    with client.application.app_context():
        doc = InvoiceDocument.query.first()
        assert doc is not None
        assert doc.processing_mode == "vision"


def test_scanned_pdf_upload_sets_processing_mode_vision(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    scanned_pdf = _make_empty_pdf()
    data = {
        "invoice": _make_file_storage(scanned_pdf, "scanned.pdf", "application/pdf"),
    }
    response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302

    with client.application.app_context():
        doc = InvoiceDocument.query.first()
        assert doc is not None
        assert doc.processing_mode == "vision"


def test_document_processor_failure_does_not_break_upload(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_pdf_bytes()
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    with patch("borrower.routes.DocumentProcessor") as mock_processor:
        mock_processor.return_value.process.side_effect = Exception("Processor crashed")
        response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302

    with client.application.app_context():
        asset = Asset.query.first()
        assert asset is not None
        assert asset.status == AssetStatus.DRAFT
        doc = InvoiceDocument.query.first()
        assert doc is not None
        assert doc.processing_mode is None


def test_document_processor_is_called_during_upload(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_pdf_bytes()
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    with patch("borrower.routes.DocumentProcessor") as mock_processor_cls:
        mock_result = DocumentProcessingResult(
            document_type="pdf",
            processing_mode="text",
            extracted_text="Invoice text",
            original_mime_type="application/pdf",
        )
        mock_processor_cls.return_value.process.return_value = mock_result
        client.post("/borrower/assets", data=data)
    mock_processor_cls.assert_called_once()


def test_successful_upload_invokes_invoice_pipeline(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC\nTotal: $100.00")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = InvoiceExtractionResult(invoice_number="INV-001")
        response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302
    mock_extract.assert_called_once()


def test_text_document_path_invokes_pipeline(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC\nTotal: $100.00")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = InvoiceExtractionResult(invoice_number="INV-001")
        client.post("/borrower/assets", data=data)
    assert mock_extract.called
    with client.application.app_context():
        doc = InvoiceDocument.query.first()
        assert doc is not None
        assert doc.processing_mode == "text"


def test_vision_document_path_invokes_pipeline(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    png_bytes = _make_png_bytes()
    data = {
        "invoice": _make_file_storage(png_bytes, "invoice.png", "image/png"),
    }
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = InvoiceExtractionResult(invoice_number="INV-001")
        client.post("/borrower/assets", data=data)
    assert mock_extract.called
    with client.application.app_context():
        doc = InvoiceDocument.query.first()
        assert doc is not None
        assert doc.processing_mode == "vision"


def test_ai_pipeline_failure_does_not_fail_upload(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.side_effect = InvoicePipelineError("AI extraction failed")
        response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302

    with client.application.app_context():
        asset = Asset.query.first()
        assert asset is not None
        assert asset.status == AssetStatus.DRAFT
        doc = InvoiceDocument.query.first()
        assert doc is not None
        assert doc.processing_mode == "text"


def test_asset_remains_in_draft_after_ai_failure(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.side_effect = InvoicePipelineError("AI extraction failed")
        client.post("/borrower/assets", data=data)

    with client.application.app_context():
        asset = Asset.query.first()
        assert asset is not None
        assert asset.status == AssetStatus.DRAFT


def test_document_remains_persisted_after_ai_failure(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.side_effect = InvoicePipelineError("AI extraction failed")
        client.post("/borrower/assets", data=data)

    with client.application.app_context():
        doc = InvoiceDocument.query.first()
        assert doc is not None
        assert doc.original_filename == "invoice.pdf"


def test_no_api_key_leakage_in_response(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.side_effect = InvoicePipelineError(
            "AI extraction failed: AgentRouter API request failed: ConnectionError('Connection error') with AGENTROUTER_API_KEY=super-secret-key"
        )
        response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302
    with client.session_transaction() as sess:
        flashes = sess.get("_flashes", [])
    all_flash_messages = " ".join(msg for _, msg in flashes)
    assert "super-secret-key" not in all_flash_messages


def test_successful_text_extraction_persists_asset_fields(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC\nTotal: $100.00")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    mock_result = InvoiceExtractionResult(
        invoice_number="INV-001",
        amount=Decimal("100.00"),
        currency="USD",
        issue_date=date(2024, 1, 15),
        due_date=date(2024, 2, 15),
        provider="mock",
        confidence=0.95,
    )
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = mock_result
        response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302

    with client.application.app_context():
        asset = Asset.query.first()
        assert asset is not None
        assert asset.invoice_number == "INV-001"
        assert asset.face_value == Decimal("100.00")
        assert asset.currency == "USD"


def test_successful_vision_extraction_persists_asset_fields(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    png_bytes = _make_png_bytes()
    data = {
        "invoice": _make_file_storage(png_bytes, "invoice.png", "image/png"),
    }
    mock_result = InvoiceExtractionResult(
        invoice_number="INV-002",
        amount=Decimal("200.00"),
        currency="EUR",
        provider="mock",
        confidence=0.88,
    )
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = mock_result
        response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302

    with client.application.app_context():
        asset = Asset.query.first()
        assert asset is not None
        assert asset.invoice_number == "INV-002"
        assert asset.face_value == Decimal("200.00")
        assert asset.currency == "EUR"


def test_ai_analysis_created_on_successful_extraction(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    mock_result = InvoiceExtractionResult(
        invoice_number="INV-003",
        provider="mock",
        model="mock-model",
        confidence=0.92,
    )
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = mock_result
        client.post("/borrower/assets", data=data)

    with client.application.app_context():
        analysis = AIAnalysis.query.filter_by(asset_id=Asset.query.first().id).first()
        assert analysis is not None
        assert analysis.provider == "mock"
        assert analysis.model == "mock-model"
        assert analysis.confidence == Decimal("0.92")
        assert analysis.extraction_output == "text"


def test_optional_extraction_fields_do_not_crash_persistence(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    mock_result = InvoiceExtractionResult(
        provider="mock",
        confidence=None,
    )
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = mock_result
        response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302

    with client.application.app_context():
        analysis = AIAnalysis.query.filter_by(asset_id=Asset.query.first().id).first()
        assert analysis is not None
        assert analysis.confidence is None


def test_persistence_failure_does_not_destroy_upload(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    mock_result = InvoiceExtractionResult(invoice_number="INV-004")
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = mock_result
        with patch("borrower.routes.persist_extraction") as mock_persist:
            mock_persist.side_effect = Exception("DB error")
            response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302

    with client.application.app_context():
        asset = Asset.query.first()
        assert asset is not None
        assert asset.status == AssetStatus.DRAFT
        doc = InvoiceDocument.query.first()
        assert doc is not None
        assert doc.original_filename == "invoice.pdf"
        assert AIAnalysis.query.filter_by(asset_id=asset.id).first() is None


def test_no_api_key_persisted(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    mock_result = InvoiceExtractionResult(
        invoice_number="INV-005",
        provider="agentrouter",
    )
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = mock_result
        client.post("/borrower/assets", data=data)

    with client.application.app_context():
        analysis = AIAnalysis.query.filter_by(asset_id=Asset.query.first().id).first()
        assert analysis is not None
        assert "AGENTROUTER_API_KEY" not in (analysis.raw_result or "")
        assert "Bearer" not in (analysis.raw_result or "")
        assert "Authorization" not in (analysis.raw_result or "")


def test_successful_text_extraction_sets_status_extracted(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC\nTotal: $100.00")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    mock_result = InvoiceExtractionResult(
        invoice_number="INV-001",
        amount=Decimal("100.00"),
        currency="USD",
        provider="mock",
        confidence=0.95,
    )
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = mock_result
        response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302

    with client.application.app_context():
        doc = InvoiceDocument.query.first()
        assert doc is not None
        assert doc.processing_status == DocumentStatus.EXTRACTED
        assert doc.processing_mode == "text"


def test_successful_vision_extraction_sets_status_extracted(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    png_bytes = _make_png_bytes()
    data = {
        "invoice": _make_file_storage(png_bytes, "invoice.png", "image/png"),
    }
    mock_result = InvoiceExtractionResult(
        invoice_number="INV-002",
        provider="mock",
        confidence=0.88,
    )
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = mock_result
        response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302

    with client.application.app_context():
        doc = InvoiceDocument.query.first()
        assert doc is not None
        assert doc.processing_status == DocumentStatus.EXTRACTED
        assert doc.processing_mode == "vision"


def test_document_processing_failure_sets_status_processing_failed(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_pdf_bytes()
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    with patch("borrower.routes.DocumentProcessor") as mock_processor_cls:
        mock_processor_cls.return_value.process.side_effect = Exception("Processor crashed")
        response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302

    with client.application.app_context():
        asset = Asset.query.first()
        assert asset is not None
        assert asset.status == AssetStatus.DRAFT
        doc = InvoiceDocument.query.first()
        assert doc is not None
        assert doc.processing_status == DocumentStatus.PROCESSING_FAILED
        assert doc.processing_mode is None
        assert AIAnalysis.query.filter_by(asset_id=asset.id).first() is None


def test_ai_extraction_failure_sets_status_extraction_failed(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.side_effect = InvoicePipelineError("AI extraction failed")
        response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302

    with client.application.app_context():
        asset = Asset.query.first()
        assert asset is not None
        assert asset.status == AssetStatus.DRAFT
        doc = InvoiceDocument.query.first()
        assert doc is not None
        assert doc.processing_status == DocumentStatus.EXTRACTION_FAILED
        assert doc.processing_mode == "text"
        assert AIAnalysis.query.filter_by(asset_id=asset.id).first() is None


def test_persistence_failure_sets_status_extraction_failed(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    mock_result = InvoiceExtractionResult(invoice_number="INV-006")
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = mock_result
        with patch("borrower.routes.persist_extraction") as mock_persist:
            mock_persist.side_effect = Exception("DB error")
            response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302

    with client.application.app_context():
        asset = Asset.query.first()
        assert asset is not None
        assert asset.status == AssetStatus.DRAFT
        doc = InvoiceDocument.query.first()
        assert doc is not None
        assert doc.processing_status == DocumentStatus.EXTRACTION_FAILED
        assert AIAnalysis.query.filter_by(asset_id=asset.id).first() is None


def test_verification_runs_after_successful_extraction(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC\nTotal: $100.00")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    mock_result = InvoiceExtractionResult(
        invoice_number="INV-001",
        amount=Decimal("100.00"),
        currency="USD",
        issue_date=date(2099, 1, 15),
        due_date=date(2099, 2, 15),
        provider="mock",
        confidence=0.95,
    )
    mock_verification = InvoiceVerificationResult(eligible=True)
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = mock_result
        with patch("borrower.routes.verify_invoice_eligibility") as mock_verify:
            mock_verify.return_value = mock_verification
            response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302
    mock_verify.assert_called_once()


def test_verification_does_not_run_after_extraction_failure(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.side_effect = InvoicePipelineError("AI extraction failed")
        with patch("borrower.routes.verify_invoice_eligibility") as mock_verify:
            response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302
    mock_verify.assert_not_called()


def test_verification_failure_leaves_asset_in_draft(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC\nTotal: $100.00")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    mock_result = InvoiceExtractionResult(
        invoice_number="INV-001",
        amount=Decimal("100.00"),
        currency="USD",
        provider="mock",
        confidence=0.95,
    )
    mock_verification = InvoiceVerificationResult(
        eligible=False,
        failed_checks=["face_value"],
        checks={"face_value": False},
        reasons=["Invoice face value must be greater than zero"],
        message="Invoice is not eligible: Invoice face value must be greater than zero",
    )
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = mock_result
        with patch("borrower.routes.verify_invoice_eligibility") as mock_verify:
            mock_verify.return_value = mock_verification
            response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302

    with client.application.app_context():
        asset = Asset.query.first()
        assert asset is not None
        assert asset.status == AssetStatus.DRAFT
        doc = InvoiceDocument.query.first()
        assert doc is not None
        assert doc.processing_status == DocumentStatus.EXTRACTED


def test_verification_success_leaves_asset_in_draft(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC\nTotal: $100.00")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    mock_result = InvoiceExtractionResult(
        invoice_number="INV-001",
        amount=Decimal("100.00"),
        currency="USD",
        issue_date=date(2099, 1, 15),
        due_date=date(2099, 2, 15),
        provider="mock",
        confidence=0.95,
    )
    mock_verification = InvoiceVerificationResult(eligible=True)
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = mock_result
        with patch("borrower.routes.verify_invoice_eligibility") as mock_verify:
            mock_verify.return_value = mock_verification
            response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302

    with client.application.app_context():
        asset = Asset.query.first()
        assert asset is not None
        assert asset.status == AssetStatus.DRAFT


def test_verification_uses_controlled_today(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC\nTotal: $100.00")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    mock_result = InvoiceExtractionResult(
        invoice_number="INV-001",
        amount=Decimal("100.00"),
        currency="USD",
        provider="mock",
        confidence=0.95,
    )

    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = mock_result
        with patch("borrower.routes.datetime") as mock_datetime:
            mock_datetime.utcnow.return_value = datetime(2099, 1, 1)
            with patch("borrower.routes.verify_invoice_eligibility") as mock_verify:
                mock_verification = InvoiceVerificationResult(eligible=True)
                mock_verify.return_value = mock_verification
                response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302
    mock_verify.assert_called_once()
    _, kwargs = mock_verify.call_args
    assert kwargs["today"] == date(2099, 1, 1)


def test_eligible_invoice_reaches_financing_submission(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC\nTotal: $100.00")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    mock_result = InvoiceExtractionResult(
        invoice_number="INV-001",
        amount=Decimal("100.00"),
        currency="USD",
        issue_date=date(2099, 1, 15),
        due_date=date(2099, 2, 15),
        provider="mock",
        confidence=0.95,
    )
    mock_verification = InvoiceVerificationResult(eligible=True)
    mock_submission = FinancingSubmissionResult(
        submitted=True,
        eligible=True,
        transaction_hash="0x" + "c" * 64,
        asset_id=42,
        block_number=12345,
        gas_used=21000,
        message="Asset created successfully",
    )
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = mock_result
        with patch("borrower.routes.verify_invoice_eligibility") as mock_verify:
            mock_verify.return_value = mock_verification
            with patch("borrower.routes.submit_financing") as mock_submit:
                mock_submit.return_value = mock_submission
                response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302
    mock_submit.assert_called_once()


def test_ineligible_invoice_does_not_submit(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC\nTotal: $100.00")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    mock_result = InvoiceExtractionResult(
        invoice_number="INV-001",
        amount=Decimal("100.00"),
        currency="USD",
        provider="mock",
        confidence=0.95,
    )
    mock_verification = InvoiceVerificationResult(
        eligible=False,
        failed_checks=["invoice_number"],
        reasons=["Invoice number is missing"],
    )
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = mock_result
        with patch("borrower.routes.verify_invoice_eligibility") as mock_verify:
            mock_verify.return_value = mock_verification
            with patch("borrower.routes.submit_financing") as mock_submit:
                response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302
    mock_submit.assert_not_called()


def test_extraction_failure_does_not_submit(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.side_effect = InvoicePipelineError("AI extraction failed")
        with patch("borrower.routes.submit_financing") as mock_submit:
            response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302
    mock_submit.assert_not_called()


def test_persistence_failure_does_not_submit(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC\nTotal: $100.00")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    mock_result = InvoiceExtractionResult(
        invoice_number="INV-001",
        amount=Decimal("100.00"),
        currency="USD",
        provider="mock",
        confidence=0.95,
    )
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = mock_result
        with patch("borrower.routes.persist_extraction") as mock_persist:
            mock_persist.side_effect = Exception("DB error")
            with patch("borrower.routes.submit_financing") as mock_submit:
                response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302
    mock_submit.assert_not_called()


def test_verification_failure_does_not_submit(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC\nTotal: $100.00")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    mock_result = InvoiceExtractionResult(
        invoice_number="INV-001",
        amount=Decimal("100.00"),
        currency="USD",
        provider="mock",
        confidence=0.95,
    )
    mock_verification = InvoiceVerificationResult(
        eligible=False,
        failed_checks=["face_value"],
        reasons=["Invoice face value must be greater than zero"],
    )
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = mock_result
        with patch("borrower.routes.verify_invoice_eligibility") as mock_verify:
            mock_verify.return_value = mock_verification
            with patch("borrower.routes.submit_financing") as mock_submit:
                response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302
    mock_submit.assert_not_called()


def test_blockchain_disabled_does_not_make_rpc_call(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC\nTotal: $100.00")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    mock_result = InvoiceExtractionResult(
        invoice_number="INV-001",
        amount=Decimal("100.00"),
        currency="USD",
        issue_date=date(2099, 1, 15),
        due_date=date(2099, 2, 15),
        provider="mock",
        confidence=0.95,
    )
    mock_verification = InvoiceVerificationResult(eligible=True)
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = mock_result
        with patch("borrower.routes.verify_invoice_eligibility") as mock_verify:
            mock_verify.return_value = mock_verification
            with patch("borrower.routes.submit_financing") as mock_submit:
                mock_submit.return_value = FinancingSubmissionResult(
                    submitted=False,
                    eligible=True,
                    message="Financing is eligible but blockchain submission is disabled",
                )
                response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302
    mock_submit.assert_called_once()
    _, kwargs = mock_submit.call_args
    assert kwargs["config"]["RPC_URL"] is None
    assert kwargs["config"]["ASSET_REGISTRY_ADDRESS"] is None


def test_successful_mocked_submission(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC\nTotal: $100.00")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    mock_result = InvoiceExtractionResult(
        invoice_number="INV-001",
        amount=Decimal("100.00"),
        currency="USD",
        issue_date=date(2099, 1, 15),
        due_date=date(2099, 2, 15),
        provider="mock",
        confidence=0.95,
    )
    mock_verification = InvoiceVerificationResult(eligible=True)
    mock_submission = FinancingSubmissionResult(
        submitted=True,
        eligible=True,
        transaction_hash="0x" + "c" * 64,
        asset_id=42,
        block_number=12345,
        gas_used=21000,
        message="Asset created successfully",
    )
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = mock_result
        with patch("borrower.routes.verify_invoice_eligibility") as mock_verify:
            mock_verify.return_value = mock_verification
            with patch("borrower.routes.submit_financing") as mock_submit:
                mock_submit.return_value = mock_submission
                response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302
    with client.session_transaction() as sess:
        flashes = sess.get("_flashes", [])
    all_flash_messages = " ".join(msg for _, msg in flashes)
    assert "financing has been submitted" in all_flash_messages


def test_failed_mocked_submission_leaves_upload_durable(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC\nTotal: $100.00")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    mock_result = InvoiceExtractionResult(
        invoice_number="INV-001",
        amount=Decimal("100.00"),
        currency="USD",
        issue_date=date(2099, 1, 15),
        due_date=date(2099, 2, 15),
        provider="mock",
        confidence=0.95,
    )
    mock_verification = InvoiceVerificationResult(eligible=True)
    mock_submission = FinancingSubmissionResult(
        submitted=False,
        eligible=True,
        message="Transaction reverted: 0xabc",
    )
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = mock_result
        with patch("borrower.routes.verify_invoice_eligibility") as mock_verify:
            mock_verify.return_value = mock_verification
            with patch("borrower.routes.submit_financing") as mock_submit:
                mock_submit.return_value = mock_submission
                response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302

    with client.application.app_context():
        asset = Asset.query.first()
        assert asset is not None
        assert asset.status == AssetStatus.DRAFT
        doc = InvoiceDocument.query.first()
        assert doc is not None
        assert doc.original_filename == "invoice.pdf"


def test_no_secret_leakage_in_borrower_response(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC\nTotal: $100.00")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    mock_result = InvoiceExtractionResult(
        invoice_number="INV-001",
        amount=Decimal("100.00"),
        currency="USD",
        issue_date=date(2099, 1, 15),
        due_date=date(2099, 2, 15),
        provider="mock",
        confidence=0.95,
    )
    mock_verification = InvoiceVerificationResult(eligible=True)
    mock_submission = FinancingSubmissionResult(
        submitted=False,
        eligible=True,
        message="AssetRegistry configuration error: PRIVATE_KEY is required: 0xsuper-secret-key",
    )
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = mock_result
        with patch("borrower.routes.verify_invoice_eligibility") as mock_verify:
            mock_verify.return_value = mock_verification
            with patch("borrower.routes.submit_financing") as mock_submit:
                mock_submit.return_value = mock_submission
                response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302
    with client.session_transaction() as sess:
        flashes = sess.get("_flashes", [])
    all_flash_messages = " ".join(msg for _, msg in flashes)
    assert "super-secret-key" not in all_flash_messages
    assert "PRIVATE_KEY" not in all_flash_messages


def test_asset_remains_draft_after_failed_submission(client):
    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice ABC\nTotal: $100.00")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    mock_result = InvoiceExtractionResult(
        invoice_number="INV-001",
        amount=Decimal("100.00"),
        currency="USD",
        issue_date=date(2099, 1, 15),
        due_date=date(2099, 2, 15),
        provider="mock",
        confidence=0.95,
    )
    mock_verification = InvoiceVerificationResult(eligible=True)
    mock_submission = FinancingSubmissionResult(
        submitted=False,
        eligible=True,
        message="Transaction reverted",
    )
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = mock_result
        with patch("borrower.routes.verify_invoice_eligibility") as mock_verify:
            mock_verify.return_value = mock_verification
            with patch("borrower.routes.submit_financing") as mock_submit:
                mock_submit.return_value = mock_submission
                client.post("/borrower/assets", data=data)

    with client.application.app_context():
        asset = Asset.query.first()
        assert asset is not None
        assert asset.status == AssetStatus.DRAFT
