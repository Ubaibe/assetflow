from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app import create_app
from database import db
from database.models import User, Wallet, Asset, InvoiceDocument
from database.enums import AssetStatus, DocumentStatus
from services.invoice_verification import InvoiceVerificationResult, verify_invoice_eligibility


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


def _create_asset(app, **overrides):
    with app.app_context():
        from eth_account import Account
        account = Account.create()
        user = User(email="test@example.com", password_hash=None, role=None)
        db.session.add(user)
        db.session.commit()

        asset = Asset(
            user_id=user.id,
            asset_hash="abc123",
            status=AssetStatus.DRAFT,
            invoice_number="INV-001",
            face_value=Decimal("100.00"),
            currency="USD",
            issue_date=datetime(2099, 1, 15),
            due_date=datetime(2099, 2, 15),
        )
        for key, value in overrides.items():
            setattr(asset, key, value)
        db.session.add(asset)
        db.session.flush()

        document = InvoiceDocument(
            asset_id=asset.id,
            original_filename="test.pdf",
            stored_filename="stored.pdf",
            mime_type="application/pdf",
            file_size=100,
            file_hash="abc123",
            processing_status=DocumentStatus.EXTRACTED,
        )
        db.session.add(document)
        db.session.commit()
        return asset.id


def test_fully_valid_invoice_is_eligible(app):
    asset_id = _create_asset(app)
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        result = verify_invoice_eligibility(asset, document)
    assert result.eligible is True
    assert all(result.checks.values())
    assert result.reasons == []


def test_extraction_not_complete_is_not_eligible(app):
    asset_id = _create_asset(app, invoice_number=None)
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        asset.invoice_number = "INV-001"
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        document.processing_status = DocumentStatus.EXTRACTION_FAILED
        db.session.commit()
        result = verify_invoice_eligibility(asset, document)
    assert result.eligible is False
    assert result.checks["extraction_complete"] is False
    assert any("extraction is not complete" in reason for reason in result.reasons)


def test_missing_invoice_number_is_not_eligible(app):
    asset_id = _create_asset(app, invoice_number=None)
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        result = verify_invoice_eligibility(asset, document)
    assert result.eligible is False
    assert result.checks["invoice_number"] is False
    assert any("Invoice number is missing" in reason for reason in result.reasons)


def test_zero_face_value_is_not_eligible(app):
    asset_id = _create_asset(app, face_value=Decimal("0.00"))
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        result = verify_invoice_eligibility(asset, document)
    assert result.eligible is False
    assert result.checks["face_value"] is False
    assert any("greater than zero" in reason for reason in result.reasons)


def test_negative_face_value_is_not_eligible(app):
    asset_id = _create_asset(app, face_value=Decimal("-10.00"))
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        result = verify_invoice_eligibility(asset, document)
    assert result.eligible is False
    assert result.checks["face_value"] is False
    assert any("greater than zero" in reason for reason in result.reasons)


def test_missing_currency_is_not_eligible(app):
    asset_id = _create_asset(app, currency="")
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        result = verify_invoice_eligibility(asset, document)
    assert result.eligible is False
    assert result.checks["currency"] is False
    assert any("valid 3-letter code" in reason for reason in result.reasons)


def test_missing_issue_date_is_not_eligible(app):
    asset_id = _create_asset(app, issue_date=None)
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        result = verify_invoice_eligibility(asset, document)
    assert result.eligible is False
    assert result.checks["issue_date"] is False
    assert any("Issue date is missing" in reason for reason in result.reasons)


def test_missing_due_date_is_not_eligible(app):
    asset_id = _create_asset(app, due_date=None)
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        result = verify_invoice_eligibility(asset, document)
    assert result.eligible is False
    assert result.checks["due_date"] is False
    assert any("Due date is missing" in reason for reason in result.reasons)


def test_due_date_before_issue_date_is_not_eligible(app):
    asset_id = _create_asset(app, issue_date=datetime(2024, 2, 15), due_date=datetime(2024, 1, 15))
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        result = verify_invoice_eligibility(asset, document)
    assert result.eligible is False
    assert result.checks["date_order"] is False
    assert any("Due date must be later than issue date" in reason for reason in result.reasons)


def test_due_date_equal_to_issue_date_is_not_eligible(app):
    asset_id = _create_asset(app, issue_date=datetime(2024, 1, 15), due_date=datetime(2024, 1, 15))
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        result = verify_invoice_eligibility(asset, document)
    assert result.eligible is False
    assert result.checks["date_order"] is False
    assert any("Due date must be later than issue date" in reason for reason in result.reasons)


def test_past_due_invoice_is_not_eligible(app):
    past_due = date.today() - timedelta(days=1)
    asset_id = _create_asset(app, due_date=datetime.combine(past_due, datetime.min.time()))
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        result = verify_invoice_eligibility(asset, document, today=date.today())
    assert result.eligible is False
    assert result.checks["not_past_due"] is False
    assert any("past due" in reason for reason in result.reasons)


def test_wrong_asset_state_is_not_eligible(app):
    asset_id = _create_asset(app)
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        asset.status = AssetStatus.EXTRACTED
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        db.session.commit()
        result = verify_invoice_eligibility(asset, document)
    assert result.eligible is False
    assert result.checks["asset_state"] is False
    assert any("DRAFT state" in reason for reason in result.reasons)


def test_multiple_failures_return_all_reasons(app):
    asset_id = _create_asset(
        app,
        invoice_number=None,
        face_value=Decimal("0.00"),
        currency="",
        issue_date=None,
        due_date=None,
    )
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        result = verify_invoice_eligibility(asset, document)
    assert result.eligible is False
    assert not result.checks["invoice_number"]
    assert not result.checks["face_value"]
    assert not result.checks["currency"]
    assert not result.checks["issue_date"]
    assert not result.checks["due_date"]
    assert len(result.reasons) >= 5


def test_valid_invoice_with_controlled_today_is_deterministic(app):
    asset_id = _create_asset(app)
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        future_date = date(2099, 1, 1)
        result = verify_invoice_eligibility(asset, document, today=future_date)
    assert result.eligible is True
    assert result.checks["not_past_due"] is True


def test_verification_does_not_mutate_asset_or_document(app):
    asset_id = _create_asset(app)
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        original_status = asset.status
        original_processing_status = document.processing_status
        verify_invoice_eligibility(asset, document)
        assert asset.status == original_status
        assert document.processing_status == original_processing_status


def test_borrower_upload_with_valid_extraction_can_be_verified(client):
    from unittest.mock import patch
    from services.ai_extraction import InvoiceExtractionResult

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
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = mock_result
        response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302

    with client.application.app_context():
        asset = Asset.query.first()
        document = InvoiceDocument.query.filter_by(asset_id=asset.id).first()
        result = verify_invoice_eligibility(asset, document, today=date(2099, 1, 1))
    assert result.eligible is True


def test_borrower_upload_with_invalid_extraction_does_not_break_upload(client):
    from unittest.mock import patch
    from services.ai_extraction import InvoiceExtractionResult

    user_id, account = _create_user(client.application)
    _login(client, user_id, account)

    pdf_bytes = _make_minimal_pdf_with_text("Invoice")
    data = {
        "invoice": _make_file_storage(pdf_bytes, "invoice.pdf", "application/pdf"),
    }
    mock_result = InvoiceExtractionResult(
        invoice_number=None,
        amount=Decimal("0.00"),
        provider="mock",
    )
    with patch("borrower.routes.extract_invoice") as mock_extract:
        mock_extract.return_value = mock_result
        response = client.post("/borrower/assets", data=data)
    assert response.status_code == 302

    with client.application.app_context():
        asset = Asset.query.first()
        document = InvoiceDocument.query.filter_by(asset_id=asset.id).first()
        assert asset is not None
        assert document is not None
        result = verify_invoice_eligibility(asset, document)
        assert result.eligible is False
        assert asset.status == AssetStatus.DRAFT


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


def _make_file_storage(content: bytes, filename: str, content_type: str):
    from werkzeug.datastructures import FileStorage
    import io
    return FileStorage(stream=io.BytesIO(content), filename=filename, content_type=content_type)


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
