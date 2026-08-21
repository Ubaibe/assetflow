from flask import Blueprint, render_template, current_app
from flask_login import login_required, current_user
from decimal import Decimal
from database import db
from database.models import Asset, Investment
from database.enums import UserRole, AssetStatus, InvestmentStatus
from services.financing_pool_client import FinancingPoolClient
from services.token_decimals import get_token_decimals, from_base_units

bp = Blueprint("marketplace", __name__, url_prefix="/marketplace")


def _get_blockchain_config():
    return {
        "RPC_URL": current_app.config.get("RPC_URL"),
        "FINANCING_POOL_ADDRESS": current_app.config.get("FINANCING_POOL_ADDRESS"),
        "PRIVATE_KEY": current_app.config.get("PRIVATE_KEY"),
        "ASSET_REGISTRY_ADDRESS": current_app.config.get("ASSET_REGISTRY_ADDRESS"),
        "CHAIN_ID": current_app.config.get("CHAIN_ID"),
    }


def _get_on_chain_client():
    config = _get_blockchain_config()
    client = FinancingPoolClient(config)
    try:
        client.connect()
    except Exception:
        return None
    return client


def _enrich_asset_with_on_chain_state(asset, client):
    on_chain_id = asset.blockchain_asset_id
    if on_chain_id is None:
        asset.on_chain_total_funded = None
        asset.on_chain_target = None
        asset.on_chain_remaining = None
        asset.on_chain_exists = False
        return

    try:
        state = client.get_funding_state(on_chain_id)
        target = client.get_financing_target(on_chain_id)
        asset.on_chain_total_funded = state.total_funded or 0
        asset.on_chain_target = target
        asset.on_chain_remaining = max(0, target - (state.total_funded or 0))
        asset.on_chain_exists = state.exists
    except Exception:
        asset.on_chain_total_funded = None
        asset.on_chain_target = None
        asset.on_chain_remaining = None
        asset.on_chain_exists = False


def _get_fundable_assets():
    return (
        Asset.query.filter(
            Asset.status.in_(
                [
                    AssetStatus.LISTED,
                    AssetStatus.PARTIALLY_FUNDED,
                    AssetStatus.FULLY_FUNDED,
                ]
            )
        )
        .order_by(Asset.created_at.desc())
        .all()
    )


@bp.route("/", methods=["GET"])
@login_required
def marketplace():
    assets = _get_fundable_assets()
    
    asset_funded = {}
    for asset in assets:
        local_funded = Decimal("0")
        for investment in asset.investments:
            if investment.status == InvestmentStatus.CONFIRMED:
                local_funded += investment.amount
        asset_funded[asset.id] = local_funded

    client = _get_on_chain_client()
    if client:
        for asset in assets:
            _enrich_asset_with_on_chain_state(asset, client)
    else:
        for asset in assets:
            asset.on_chain_total_funded = None
            asset.on_chain_target = None
            asset.on_chain_remaining = None
            asset.on_chain_exists = False

    token_symbol = (current_app.config.get("PAYMENT_MODE") or "usdt").upper()
    token_decimals = get_token_decimals(current_app.config)

    return render_template(
        "marketplace.html",
        assets=assets,
        asset_funded=asset_funded,
        token_symbol=token_symbol,
        token_decimals=token_decimals,
    )
