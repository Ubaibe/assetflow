import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///assetflow.db")
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    FLASK_ENV = os.getenv("FLASK_ENV", "development")
    MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")

    AI_PROVIDER = os.getenv("AI_PROVIDER")
    AI_MODEL = os.getenv("AI_MODEL")
    AI_MODE = os.getenv("AI_MODE", "mock")

    BLOCKCHAIN_MODE = os.getenv("BLOCKCHAIN_MODE", "mock")
    BOTCHAIN_NETWORK = os.getenv("BOTCHAIN_NETWORK")
    PAYMENT_MODE = os.getenv("PAYMENT_MODE", "usdt")
    USDT_DECIMALS = os.getenv("USDT_DECIMALS")
    DEPLOYER_ADDRESS = os.getenv("DEPLOYER_ADDRESS")
