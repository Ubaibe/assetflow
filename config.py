import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY") or "dev-secret-key-change-in-production"
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///assetflow.db")
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    FLASK_ENV = os.getenv("FLASK_ENV", "development")
    MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")

    AI_PROVIDER = os.getenv("AI_PROVIDER")
    AI_MODEL = os.getenv("AI_MODEL")
    AI_MODE = os.getenv("AI_MODE", "mock")
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    AGENTROUTER_API_KEY = os.getenv("AGENTROUTER_API_KEY")
    AGENTROUTER_BASE_URL = os.getenv("AGENTROUTER_BASE_URL", "https://api.agentrouter.com/v1")

    BLOCKCHAIN_MODE = os.getenv("BLOCKCHAIN_MODE", "mock")
    BOTCHAIN_NETWORK = os.getenv("BOTCHAIN_NETWORK")
    PAYMENT_MODE = os.getenv("PAYMENT_MODE", "usdt")
    USDT_DECIMALS = os.getenv("USDT_DECIMALS")
    DEPLOYER_ADDRESS = os.getenv("DEPLOYER_ADDRESS")
    PAYMENT_TOKEN_DECIMALS = int(os.getenv("PAYMENT_TOKEN_DECIMALS", "18"))

    BOT_CHAIN_RPC_URL = os.getenv("BOT_CHAIN_RPC_URL")
    BOT_CHAIN_CHAIN_ID = os.getenv("BOT_CHAIN_CHAIN_ID")
    BOT_CHAIN_NETWORK_NAME = os.getenv("BOT_CHAIN_NETWORK_NAME") or "BOT Chain"
    BOT_CHAIN_EXPLORER_URL = os.getenv("BOT_CHAIN_EXPLORER_URL")
    BOT_CHAIN_NATIVE_CURRENCY = os.getenv("BOT_CHAIN_NATIVE_CURRENCY") or "BOT"

    RPC_URL = os.getenv("RPC_URL") or BOT_CHAIN_RPC_URL
    _chain_id_env = os.getenv("CHAIN_ID") or BOT_CHAIN_CHAIN_ID
    CHAIN_ID = int(_chain_id_env) if _chain_id_env else None
    ASSET_REGISTRY_ADDRESS = os.getenv("ASSET_REGISTRY_ADDRESS") or None
    FINANCING_POOL_ADDRESS = os.getenv("FINANCING_POOL_ADDRESS") or None
    PAYMENT_TOKEN_ADDRESS = os.getenv("PAYMENT_TOKEN_ADDRESS") or None
    PRIVATE_KEY = os.getenv("PRIVATE_KEY") or None

    AUTH_NONCE_EXPIRY_SECONDS = int(os.getenv("AUTH_NONCE_EXPIRY_SECONDS", "300"))
    PORT = int(os.getenv("PORT", "5000"))
