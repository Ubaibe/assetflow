import pytest
from decimal import Decimal
from datetime import date, datetime

from app import create_app
from database import db
from database.models import User, Wallet, Asset, InvoiceDocument, AIAnalysis
from database.enums import AssetStatus
from services.ai_extraction import InvoiceExtractionResult
from services.invoice_extraction_persistence import persist_extraction


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


def _create_asset(app):
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
        )
        db.session.add(asset)
        db.session.flush()

        document = InvoiceDocument(
            asset_id=asset.id,
            original_filename="test.pdf",
            stored_filename="stored.pdf",
            mime_type="application/pdf",
            file_size=100,
            file_hash="abc123",
        )
        db.session.add(document)
        db.session.commit()
        return asset.id


def test_persist_text_extraction_updates_asset_fields(app):
    asset_id = _create_asset(app)
    with app.app_context():
        result = InvoiceExtractionResult(
            invoice_number="INV-001",
            amount=Decimal("100.00"),
            currency="USD",
            issue_date=date(2024, 1, 15),
            due_date=date(2024, 2, 15),
            provider="mock",
            confidence=0.95,
        )
        persist_extraction(db.session, asset_id, result, "text")
        db.session.commit()

        asset = db.session.get(Asset, asset_id)
        assert asset.invoice_number == "INV-001"
        assert asset.face_value == Decimal("100.00")
        assert asset.currency == "USD"
        assert asset.issue_date == datetime(2024, 1, 15)
        assert asset.due_date == datetime(2024, 2, 15)


def test_persist_vision_extraction_updates_asset_fields(app):
    asset_id = _create_asset(app)
    with app.app_context():
        result = InvoiceExtractionResult(
            invoice_number="INV-002",
            amount=Decimal("200.00"),
            currency="EUR",
            issue_date=date(2024, 3, 1),
            due_date=date(2024, 4, 1),
            provider="agentrouter",
            confidence=0.88,
        )
        persist_extraction(db.session, asset_id, result, "vision")
        db.session.commit()

        asset = db.session.get(Asset, asset_id)
        assert asset.invoice_number == "INV-002"
        assert asset.face_value == Decimal("200.00")
        assert asset.currency == "EUR"


def test_ai_analysis_created_with_correct_metadata(app):
    asset_id = _create_asset(app)
    with app.app_context():
        result = InvoiceExtractionResult(
            invoice_number="INV-003",
            amount=Decimal("50.00"),
            currency="GBP",
            provider="mock",
            model="mock-model",
            confidence=0.92,
        )
        persist_extraction(db.session, asset_id, result, "text")
        db.session.commit()

        analysis = AIAnalysis.query.filter_by(asset_id=asset_id).first()
        assert analysis is not None
        assert analysis.provider == "mock"
        assert analysis.model == "mock-model"
        assert analysis.confidence == Decimal("0.92")
        assert analysis.extraction_output == "text"
        assert analysis.raw_result is not None
        assert "INV-003" in analysis.raw_result


def test_optional_fields_do_not_crash_persistence(app):
    asset_id = _create_asset(app)
    with app.app_context():
        result = InvoiceExtractionResult(
            invoice_number=None,
            amount=None,
            currency=None,
            issue_date=None,
            due_date=None,
            provider="mock",
            confidence=None,
        )
        persist_extraction(db.session, asset_id, result, "vision")
        db.session.commit()

        asset = db.session.get(Asset, asset_id)
        assert asset.invoice_number is None
        assert asset.face_value is None
        assert asset.currency == "USD"


def test_persistence_failure_does_not_destroy_asset_or_document(app):
    asset_id = _create_asset(app)
    with app.app_context():
        original_asset = db.session.get(Asset, asset_id)
        original_doc = InvoiceDocument.query.filter_by(asset_id=asset_id).first()

        with pytest.raises(ValueError):
            persist_extraction(db.session, 99999, InvoiceExtractionResult(), "text")

        asset = db.session.get(Asset, asset_id)
        doc = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        assert asset is not None
        assert doc is not None
        assert asset.id == original_asset.id
        assert doc.id == original_doc.id


def test_no_api_key_in_raw_result(app):
    asset_id = _create_asset(app)
    with app.app_context():
        result = InvoiceExtractionResult(
            invoice_number="INV-004",
            amount=Decimal("10.00"),
            provider="agentrouter",
            model="gpt-4o",
        )
        persist_extraction(db.session, asset_id, result, "text")
        db.session.commit()

        analysis = AIAnalysis.query.filter_by(asset_id=asset_id).first()
        assert analysis.raw_result is not None
        assert "AGENTROUTER_API_KEY" not in analysis.raw_result
        assert "Bearer" not in analysis.raw_result
        assert "Authorization" not in analysis.raw_result
