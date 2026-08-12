import pytest
from decimal import Decimal
from datetime import datetime, timedelta
from app import create_app
from database import db
from database.models import (
    User,
    Wallet,
    Asset,
    InvoiceDocument,
    Investment,
    Repayment,
    BlockchainTransaction,
    AuditLog,
)
from database.enums import UserRole, AssetStatus, InvestmentStatus, TransactionStatus, TransactionType
from database.state_machine import transition, InvalidStatusTransition


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


def test_application_factory_creation(app):
    assert app is not None
    assert app.config["SECRET_KEY"] is not None


def test_database_initialization(app):
    with app.app_context():
        assert db.engine is not None


def test_user_creation(app):
    with app.app_context():
        user = User(
            email="test@example.com",
            password_hash="hashed",
            role=UserRole.BORROWER,
        )
        db.session.add(user)
        db.session.commit()
        assert user.id is not None
        assert user.email == "test@example.com"
        assert user.is_active is True


def test_unique_email_enforcement(app):
    with app.app_context():
        user1 = User(
            email="unique@example.com",
            password_hash="hashed1",
            role=UserRole.BORROWER,
        )
        user2 = User(
            email="unique@example.com",
            password_hash="hashed2",
            role=UserRole.INVESTOR,
        )
        db.session.add(user1)
        db.session.add(user2)
        with pytest.raises(Exception):
            db.session.commit()


def test_wallet_relationship(app):
    with app.app_context():
        user = User(
            email="wallet@example.com",
            password_hash="hashed",
            role=UserRole.INVESTOR,
        )
        db.session.add(user)
        db.session.commit()

        wallet = Wallet(
            user_id=user.id,
            address="0x1234567890abcdef1234567890abcdef12345678",
            chain_id=1,
        )
        db.session.add(wallet)
        db.session.commit()

        assert wallet.user.email == "wallet@example.com"
        assert len(user.wallets) == 1


def test_asset_creation(app):
    with app.app_context():
        user = User(
            email="asset@example.com",
            password_hash="hashed",
            role=UserRole.BORROWER,
        )
        db.session.add(user)
        db.session.commit()

        asset = Asset(
            user_id=user.id,
            asset_hash="abc123",
            invoice_number="INV-001",
            face_value=Decimal("1000.00"),
            financing_target=Decimal("800.00"),
            currency="USD",
            issue_date=datetime.utcnow(),
            due_date=datetime.utcnow() + timedelta(days=30),
            risk_score=75,
            risk_grade="B",
        )
        db.session.add(asset)
        db.session.commit()

        assert asset.id is not None
        assert asset.borrower.email == "asset@example.com"
        assert asset.status == AssetStatus.DRAFT


def test_unique_asset_hash_enforcement(app):
    with app.app_context():
        user = User(
            email="assethash@example.com",
            password_hash="hashed",
            role=UserRole.BORROWER,
        )
        db.session.add(user)
        db.session.commit()

        asset1 = Asset(
            user_id=user.id,
            asset_hash="duplicate_hash",
            face_value=Decimal("1000.00"),
            financing_target=Decimal("800.00"),
        )
        asset2 = Asset(
            user_id=user.id,
            asset_hash="duplicate_hash",
            face_value=Decimal("500.00"),
            financing_target=Decimal("400.00"),
        )
        db.session.add(asset1)
        db.session.add(asset2)
        with pytest.raises(Exception):
            db.session.commit()


def test_invoice_document_relationship(app):
    with app.app_context():
        user = User(
            email="invoice@example.com",
            password_hash="hashed",
            role=UserRole.BORROWER,
        )
        db.session.add(user)
        db.session.commit()

        asset = Asset(
            user_id=user.id,
            asset_hash="inv_hash",
            face_value=Decimal("1000.00"),
            financing_target=Decimal("800.00"),
        )
        db.session.add(asset)
        db.session.commit()

        doc = InvoiceDocument(
            asset_id=asset.id,
            original_filename="invoice.pdf",
            stored_filename="inv_hash.pdf",
            mime_type="application/pdf",
            file_size=1024,
            file_hash="abc",
        )
        db.session.add(doc)
        db.session.commit()

        assert doc.asset.asset_hash == "inv_hash"
        assert len(asset.documents) == 1


def test_investment_relationship(app):
    with app.app_context():
        borrower = User(
            email="borrower@example.com",
            password_hash="hashed",
            role=UserRole.BORROWER,
        )
        investor = User(
            email="investor@example.com",
            password_hash="hashed",
            role=UserRole.INVESTOR,
        )
        db.session.add_all([borrower, investor])
        db.session.commit()

        asset = Asset(
            user_id=borrower.id,
            asset_hash="invest_hash",
            face_value=Decimal("1000.00"),
            financing_target=Decimal("800.00"),
        )
        db.session.add(asset)
        db.session.commit()

        investment = Investment(
            user_id=investor.id,
            asset_id=asset.id,
            amount=Decimal("200.00"),
            tx_hash="0xtx1",
            log_index=0,
            status=InvestmentStatus.CONFIRMED,
        )
        db.session.add(investment)
        db.session.commit()

        assert investment.investor.email == "investor@example.com"
        assert investment.asset.asset_hash == "invest_hash"
        assert len(asset.investments) == 1


def test_repayment_relationship(app):
    with app.app_context():
        borrower = User(
            email="repay_borrower@example.com",
            password_hash="hashed",
            role=UserRole.BORROWER,
        )
        db.session.add(borrower)
        db.session.commit()

        asset = Asset(
            user_id=borrower.id,
            asset_hash="repay_hash",
            face_value=Decimal("1000.00"),
            financing_target=Decimal("800.00"),
        )
        db.session.add(asset)
        db.session.commit()

        repayment = Repayment(
            asset_id=asset.id,
            user_id=borrower.id,
            amount=Decimal("500.00"),
            tx_hash="0xtx2",
            log_index=0,
        )
        db.session.add(repayment)
        db.session.commit()

        assert repayment.asset.asset_hash == "repay_hash"
        assert repayment.payer.email == "repay_borrower@example.com"
        assert len(asset.repayments) == 1


def test_blockchain_transaction_composite_uniqueness(app):
    with app.app_context():
        tx1 = BlockchainTransaction(
            tx_hash="0xtx3",
            log_index=0,
            tx_type=TransactionType.FUND,
            asset_id=1,
            status=TransactionStatus.CONFIRMED,
        )
        tx2 = BlockchainTransaction(
            tx_hash="0xtx3",
            log_index=0,
            tx_type=TransactionType.FUND,
            asset_id=1,
            status=TransactionStatus.CONFIRMED,
        )
        db.session.add(tx1)
        db.session.add(tx2)
        with pytest.raises(Exception):
            db.session.commit()


def test_audit_log_creation(app):
    with app.app_context():
        user = User(
            email="audit@example.com",
            password_hash="hashed",
            role=UserRole.ADMIN,
        )
        db.session.add(user)
        db.session.commit()

        log = AuditLog(
            user_id=user.id,
            action="create_asset",
            entity_type="asset",
            entity_id=1,
            log_metadata='{"status": "draft"}',
        )
        db.session.add(log)
        db.session.commit()

        assert log.user.email == "audit@example.com"
        assert log.action == "create_asset"


def test_valid_lifecycle_transitions(app):
    with app.app_context():
        user = User(
            email="lifecycle@example.com",
            password_hash="hashed",
            role=UserRole.BORROWER,
        )
        db.session.add(user)
        db.session.commit()

        asset = Asset(
            user_id=user.id,
            asset_hash="lifecycle_hash",
            face_value=Decimal("1000.00"),
            financing_target=Decimal("800.00"),
        )
        db.session.add(asset)
        db.session.commit()

        assert asset.status == AssetStatus.DRAFT

        transition(asset, AssetStatus.EXTRACTED)
        assert asset.status == AssetStatus.EXTRACTED

        transition(asset, AssetStatus.UNDERWRITTEN)
        assert asset.status == AssetStatus.UNDERWRITTEN

        transition(asset, AssetStatus.LISTED)
        assert asset.status == AssetStatus.LISTED

        transition(asset, AssetStatus.PARTIALLY_FUNDED)
        assert asset.status == AssetStatus.PARTIALLY_FUNDED

        transition(asset, AssetStatus.FULLY_FUNDED)
        assert asset.status == AssetStatus.FULLY_FUNDED

        transition(asset, AssetStatus.REPAID)
        assert asset.status == AssetStatus.REPAID

        transition(asset, AssetStatus.SETTLED)
        assert asset.status == AssetStatus.SETTLED


def test_invalid_lifecycle_transitions(app):
    with app.app_context():
        user = User(
            email="invalid@example.com",
            password_hash="hashed",
            role=UserRole.BORROWER,
        )
        db.session.add(user)
        db.session.commit()

        asset = Asset(
            user_id=user.id,
            asset_hash="invalid_hash",
            face_value=Decimal("1000.00"),
            financing_target=Decimal("800.00"),
        )
        db.session.add(asset)
        db.session.commit()

        with pytest.raises(InvalidStatusTransition):
            transition(asset, AssetStatus.REPAID)

        with pytest.raises(InvalidStatusTransition):
            transition(asset, AssetStatus.LISTED)
        with pytest.raises(InvalidStatusTransition):
            transition(asset, AssetStatus.DRAFT)


def test_numeric_monetary_fields_are_not_floats(app):
    with app.app_context():
        user = User(
            email="numeric@example.com",
            password_hash="hashed",
            role=UserRole.BORROWER,
        )
        db.session.add(user)
        db.session.commit()

        asset = Asset(
            user_id=user.id,
            asset_hash="numeric_hash",
            face_value=Decimal("1000.00"),
            financing_target=Decimal("800.00"),
        )
        db.session.add(asset)
        db.session.commit()

        assert isinstance(asset.face_value, Decimal)
        assert isinstance(asset.financing_target, Decimal)
        assert asset.face_value == Decimal("1000.00")
        assert asset.financing_target == Decimal("800.00")
