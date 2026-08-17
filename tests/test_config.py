import pytest
from app import create_app
from config import Config
import importlib


def test_bot_chain_config_fields_exist():
    assert hasattr(Config, "BOT_CHAIN_RPC_URL")
    assert hasattr(Config, "BOT_CHAIN_CHAIN_ID")
    assert hasattr(Config, "BOT_CHAIN_NETWORK_NAME")
    assert hasattr(Config, "BOT_CHAIN_EXPLORER_URL")
    assert hasattr(Config, "BOT_CHAIN_NATIVE_CURRENCY")


def test_bot_chain_defaults_are_safe(monkeypatch):
    monkeypatch.setenv("BOT_CHAIN_NETWORK_NAME", "")
    import config as config_module
    importlib.reload(config_module)
    assert config_module.Config.BOT_CHAIN_NATIVE_CURRENCY == "BOT"
    assert config_module.Config.BOT_CHAIN_NETWORK_NAME == "BOT Chain"


def test_legacy_rpc_url_is_used_when_set(monkeypatch):
    monkeypatch.setenv("RPC_URL", "http://localhost:8545")
    monkeypatch.setenv("BOT_CHAIN_RPC_URL", "")
    import config as config_module
    importlib.reload(config_module)
    assert config_module.Config.RPC_URL == "http://localhost:8545"


def test_bot_chain_rpc_url_falls_back_when_legacy_missing(monkeypatch):
    monkeypatch.setenv("RPC_URL", "")
    monkeypatch.setenv("BOT_CHAIN_RPC_URL", "https://rpc.bot.com")
    monkeypatch.setenv("BOT_CHAIN_CHAIN_ID", "99999")
    import config as config_module
    importlib.reload(config_module)
    assert config_module.Config.RPC_URL == "https://rpc.bot.com"


def test_chain_id_falls_back_to_bot_chain(monkeypatch):
    monkeypatch.setenv("CHAIN_ID", "")
    monkeypatch.setenv("BOT_CHAIN_CHAIN_ID", "99999")
    import config as config_module
    importlib.reload(config_module)
    assert config_module.Config.CHAIN_ID == 99999


def test_legacy_chain_id_takes_precedence_over_bot_chain(monkeypatch):
    monkeypatch.setenv("CHAIN_ID", "31337")
    monkeypatch.setenv("BOT_CHAIN_CHAIN_ID", "99999")
    import config as config_module
    importlib.reload(config_module)
    assert config_module.Config.CHAIN_ID == 31337


def test_private_key_is_not_exposed_in_config(monkeypatch):
    monkeypatch.setenv("PRIVATE_KEY", "")
    import config as config_module
    importlib.reload(config_module)
    assert config_module.Config.PRIVATE_KEY is None


def test_missing_bot_chain_config_does_not_break_app_creation():
    import os
    for key in ["BOT_CHAIN_RPC_URL", "BOT_CHAIN_CHAIN_ID", "ASSET_REGISTRY_ADDRESS", "FINANCING_POOL_ADDRESS"]:
        os.environ.pop(key, None)
    app = create_app()
    assert app is not None


def test_contract_addresses_are_optional(monkeypatch):
    monkeypatch.setenv("ASSET_REGISTRY_ADDRESS", "")
    monkeypatch.setenv("FINANCING_POOL_ADDRESS", "")
    monkeypatch.setenv("PAYMENT_TOKEN_ADDRESS", "")
    import config as config_module
    importlib.reload(config_module)
    assert config_module.Config.ASSET_REGISTRY_ADDRESS is None
    assert config_module.Config.FINANCING_POOL_ADDRESS is None
    assert config_module.Config.PAYMENT_TOKEN_ADDRESS is None
