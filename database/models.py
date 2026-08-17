from flask_login import UserMixin
from sqlalchemy import String, Numeric, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from decimal import Decimal
from database import db
from database.enums import UserRole, AssetStatus, InvestmentStatus, TransactionStatus, TransactionType, DocumentStatus


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

    wallets: Mapped[list["Wallet"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    assets: Mapped[list["Asset"]] = relationship(back_populates="borrower", foreign_keys="Asset.user_id")
    investments: Mapped[list["Investment"]] = relationship(back_populates="investor")
    repayments: Mapped[list["Repayment"]] = relationship(back_populates="payer")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="user")


class Wallet(db.Model):
    __tablename__ = "wallets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    address: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    chain_id: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="wallets")


class Asset(db.Model):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    asset_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    blockchain_asset_id: Mapped[int | None] = mapped_column(nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    face_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    financing_target: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    issue_date: Mapped[datetime | None] = mapped_column(nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(nullable=True)
    status: Mapped[AssetStatus] = mapped_column(String(50), default=AssetStatus.DRAFT)
    risk_score: Mapped[int | None] = mapped_column(nullable=True)
    risk_grade: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

    borrower: Mapped["User"] = relationship(back_populates="assets", foreign_keys=[user_id])
    documents: Mapped[list["InvoiceDocument"]] = relationship(back_populates="asset", cascade="all, delete-orphan")
    ai_analyses: Mapped[list["AIAnalysis"]] = relationship(back_populates="asset", cascade="all, delete-orphan")
    risk_assessments: Mapped[list["RiskAssessment"]] = relationship(back_populates="asset", cascade="all, delete-orphan")
    investments: Mapped[list["Investment"]] = relationship(back_populates="asset", cascade="all, delete-orphan")
    repayments: Mapped[list["Repayment"]] = relationship(back_populates="asset", cascade="all, delete-orphan")
    blockchain_transactions: Mapped[list["BlockchainTransaction"]] = relationship(back_populates="asset", cascade="all, delete-orphan")


class InvoiceDocument(db.Model):
    __tablename__ = "invoice_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(nullable=False)
    file_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    processing_status: Mapped[DocumentStatus] = mapped_column(String(50), default=DocumentStatus.UPLOADED)
    processing_mode: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    asset: Mapped["Asset"] = relationship(back_populates="documents")


class AIAnalysis(db.Model):
    __tablename__ = "ai_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False)
    extraction_output: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    raw_result: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    asset: Mapped["Asset"] = relationship(back_populates="ai_analyses")


class RiskAssessment(db.Model):
    __tablename__ = "risk_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False)
    score: Mapped[int] = mapped_column(nullable=False)
    grade: Mapped[str] = mapped_column(String(10), nullable=False)
    probability: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    recommended_financing: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    recommended_apr: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    factors: Mapped[str | None] = mapped_column(String(255), nullable=True)
    explanation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    asset: Mapped["Asset"] = relationship(back_populates="risk_assessments")


class Investment(db.Model):
    __tablename__ = "investments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    tx_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    log_index: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[InvestmentStatus] = mapped_column(String(50), default=InvestmentStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

    investor: Mapped["User"] = relationship(back_populates="investments")
    asset: Mapped["Asset"] = relationship(back_populates="investments")

    __table_args__ = (
        UniqueConstraint("tx_hash", "log_index", name="uq_investment_tx_log"),
    )


class Repayment(db.Model):
    __tablename__ = "repayments"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    tx_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    log_index: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    asset: Mapped["Asset"] = relationship(back_populates="repayments")
    payer: Mapped["User | None"] = relationship(back_populates="repayments", foreign_keys=[user_id])

    __table_args__ = (
        UniqueConstraint("tx_hash", "log_index", name="uq_repayment_tx_log"),
    )


class BlockchainTransaction(db.Model):
    __tablename__ = "blockchain_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    tx_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    log_index: Mapped[int] = mapped_column(nullable=False)
    tx_type: Mapped[TransactionType] = mapped_column(String(50), default=TransactionType.OTHER)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    status: Mapped[TransactionStatus] = mapped_column(String(50), default=TransactionStatus.PENDING)
    block_number: Mapped[int | None] = mapped_column(nullable=True)
    gas_used: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

    asset: Mapped["Asset | None"] = relationship(back_populates="blockchain_transactions")

    __table_args__ = (
        UniqueConstraint("tx_hash", "log_index", name="uq_blockchain_tx_log"),
    )


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(nullable=True)
    log_metadata: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    user: Mapped["User | None"] = relationship(back_populates="audit_logs")

    __table_args__ = (
        Index("idx_audit_logs_entity", "entity_type", "entity_id"),
    )


class Challenge(db.Model):
    __tablename__ = "challenges"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    wallet_address: Mapped[str] = mapped_column(String(255), nullable=False)
    nonce: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
