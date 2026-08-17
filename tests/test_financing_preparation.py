from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app import create_app
from database import db
from database.models import User, Wallet, Asset, InvoiceDocument
from database.enums import AssetStatus, DocumentStatus
from services.financing_preparation import FinancingPreparationResult, prepare_financing
from services.invoice_verification import InvoiceVerificationResult


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
            asset_hash="a" * 64,
            status=AssetStatus.DRAFT,
            invoice_number="INV-001",
            face_value=Decimal("100.00"),
            financing_target=Decimal("80.00"),
            currency="USD",
            issue_date=datetime(2099, 1, 15),
            due_date=datetime(2099, 2, 15),
            risk_score=50,
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
            file_hash="a" * 64,
            processing_status=DocumentStatus.EXTRACTED,
        )
        db.session.add(document)
        db.session.commit()
        return asset.id


def test_eligible_invoice_produces_valid_preparation_result(app):
    asset_id = _create_asset(app)
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        result = prepare_financing(asset, document)
    assert result.eligible is True
    assert result.asset_id == asset_id
    assert result.invoice_number == "INV-001"
    assert result.face_value == Decimal("100.00")
    assert result.currency == "USD"
    assert result.issue_date == datetime(2099, 1, 15)
    assert result.due_date == datetime(2099, 2, 15)
    assert result.asset_hash == "a" * 64
    assert result.financing_target == Decimal("80.00")
    assert result.payload is not None
    assert result.payload["assetHash"] == "a" * 64
    assert result.payload["faceValue"] == 100000000000000000000
    assert result.payload["financingTarget"] == 80000000000000000000
    assert result.payload["maturityTimestamp"] == 4074793200
    assert result.payload["riskScore"] == 50


def test_ineligible_invoice_produces_failed_checks(app):
    asset_id = _create_asset(app, invoice_number=None)
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        result = prepare_financing(asset, document)
    assert result.eligible is False
    assert "invoice_number" in result.failed_checks
    assert result.payload is None
    assert result.message is not None


def test_missing_required_fields(app):
    asset_id = _create_asset(
        app,
        invoice_number=None,
        face_value=None,
        currency="",
        issue_date=None,
        due_date=None,
    )
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        result = prepare_financing(asset, document)
    assert result.eligible is False
    assert len(result.failed_checks) >= 5


def test_invalid_face_value(app):
    asset_id = _create_asset(app, face_value=Decimal("0.00"))
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        result = prepare_financing(asset, document)
    assert result.eligible is False
    assert "face_value" in result.failed_checks


def test_invalid_dates(app):
    asset_id = _create_asset(app, issue_date=datetime(2099, 2, 15), due_date=datetime(2099, 1, 15))
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        result = prepare_financing(asset, document)
    assert result.eligible is False
    assert "date_order" in result.failed_checks


def test_expired_invoice(app):
    past_due = datetime.utcnow() - timedelta(days=1)
    asset_id = _create_asset(app, due_date=past_due)
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        result = prepare_financing(asset, document, today=datetime.utcnow())
    assert result.eligible is False
    assert "not_past_due" in result.failed_checks


def test_wrong_asset_status(app):
    asset_id = _create_asset(app)
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        asset.status = AssetStatus.EXTRACTED
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        db.session.commit()
        result = prepare_financing(asset, document)
    assert result.eligible is False
    assert "asset_state" in result.failed_checks


def test_deterministic_hash_behavior(app):
    asset_id = _create_asset(app)
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        result = prepare_financing(asset, document)
    assert result.asset_hash == asset.asset_hash
    assert result.payload["assetHash"] == asset.asset_hash
    assert result.payload["assetHashBytes32"] == "0x" + "a" * 64


def test_monetary_unit_conversion(app):
    asset_id = _create_asset(app, face_value=Decimal("0.01"), financing_target=Decimal("0.50"))
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        result = prepare_financing(asset, document)
    assert result.eligible is True
    assert result.payload["faceValue"] == 10000000000000000
    assert result.payload["financingTarget"] == 500000000000000000


def test_monetary_unit_conversion_with_6_decimals(app):
    asset_id = _create_asset(app, face_value=Decimal("50.00"), financing_target=Decimal("80.00"))
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        result = prepare_financing(asset, document, token_decimals=6)
    assert result.eligible is True
    assert result.payload["faceValue"] == 50000000
    assert result.payload["financingTarget"] == 80000000


def test_monetary_unit_conversion_with_6_decimals_small_amount(app):
    asset_id = _create_asset(app, face_value=Decimal("0.01"), financing_target=Decimal("0.02"))
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        result = prepare_financing(asset, document, token_decimals=6)
    assert result.eligible is True
    assert result.payload["faceValue"] == 10000
    assert result.payload["financingTarget"] == 20000


def test_monetary_unit_conversion_with_6_decimals_rejects_excess_precision(app):
    asset_id = _create_asset(app, face_value=Decimal("0.000001"), financing_target=Decimal("0.000002"))
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        result = prepare_financing(asset, document, token_decimals=6)
    assert result.eligible is False
    assert "face_value" in result.failed_checks or "financing_target" in result.failed_checks


def test_no_blockchain_calls(app):
    asset_id = _create_asset(app)
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        result = prepare_financing(asset, document)
    assert result.eligible is True
    assert result.payload is not None


def test_asset_remains_draft(app):
    asset_id = _create_asset(app)
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        prepare_financing(asset, document)
        db.session.commit()
        refreshed = db.session.get(Asset, asset_id)
    assert refreshed.status == AssetStatus.DRAFT


def test_originator_address_in_payload(app):
    asset_id = _create_asset(app)
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        result = prepare_financing(asset, document, originator_address="0x" + "b" * 40)
    assert result.eligible is True
    assert result.payload["originator"] == "0x" + "b" * 40


def test_preparation_does_not_mutate_asset(app):
    asset_id = _create_asset(app)
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        document = InvoiceDocument.query.filter_by(asset_id=asset_id).first()
        original_status = asset.status
        prepare_financing(asset, document)
        assert asset.status == original_status
