from enum import Enum


class UserRole(str, Enum):
    BORROWER = "borrower"
    INVESTOR = "investor"
    ADMIN = "admin"


class AssetStatus(str, Enum):
    DRAFT = "draft"
    EXTRACTED = "extracted"
    UNDERWRITTEN = "underwritten"
    LISTED = "listed"
    PARTIALLY_FUNDED = "partially_funded"
    FULLY_FUNDED = "fully_funded"
    REPAID = "repaid"
    SETTLED = "settled"
    DEFAULTED = "defaulted"
    CANCELLED = "cancelled"


class InvestmentStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class TransactionStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class TransactionType(str, Enum):
    FUND = "fund"
    REPAY = "repay"
    CLAIM = "claim"
    OTHER = "other"
