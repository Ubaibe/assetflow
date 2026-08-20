from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app
from flask_login import login_required, current_user
from decimal import Decimal, InvalidOperation
from database import db
from database.models import Asset, Investment, BlockchainTransaction
from database.enums import AssetStatus, UserRole, InvestmentStatus, TransactionType, TransactionStatus
from services.financing_funding import prepare_and_fund, FundingResult
from services.token_decimals import get_token_decimals, from_base_units, to_base_units, TokenDecimalError

bp = Blueprint("investor", __name__, url_prefix="/investor")


def _get_blockchain_config():
    return {
        "RPC_URL": current_app.config.get("RPC_URL"),
        "FINANCING_POOL_ADDRESS": current_app.config.get("FINANCING_POOL_ADDRESS"),
        "PRIVATE_KEY": current_app.config.get("PRIVATE_KEY"),
        "ASSET_REGISTRY_ADDRESS": current_app.config.get("ASSET_REGISTRY_ADDRESS"),
        "CHAIN_ID": current_app.config.get("CHAIN_ID"),
    }


def _get_on_chain_client():
    from services.financing_pool_client import FinancingPoolClient

    config = _get_blockchain_config()
    client = FinancingPoolClient(config)
    try:
        client.connect()
    except Exception:
        return None
    return client


def _to_token_display(wei_value, token_decimals=None):
    if wei_value is None:
        return None
    if token_decimals is None:
        token_decimals = get_token_decimals(current_app.config)
    return from_base_units(wei_value, token_decimals)


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


@bp.route("/dashboard")
@login_required
def dashboard():
    if str(current_user.role or "") != UserRole.INVESTOR.value:
        abort(403)

    assets = _get_fundable_assets()
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

    return render_template("investor/dashboard.html", assets=assets)


@bp.route("/assets/<int:asset_id>")
@login_required
def asset_detail(asset_id):
    if str(current_user.role or "") != UserRole.INVESTOR.value:
        abort(403)

    asset = Asset.query.get_or_404(asset_id)

    on_chain_total_funded = None
    on_chain_target = None
    on_chain_remaining = None
    on_chain_status = None
    on_chain_total_funded_display = None
    on_chain_target_display = None
    on_chain_remaining_display = None

    client = _get_on_chain_client()
    if client and asset.blockchain_asset_id is not None:
        on_chain_id = asset.blockchain_asset_id
        try:
            on_chain_status = client.get_asset_status(on_chain_id)
            state = client.get_funding_state(on_chain_id)
            target = client.get_financing_target(on_chain_id)
            on_chain_total_funded = state.total_funded or 0
            on_chain_target = target
            on_chain_remaining = max(0, target - on_chain_total_funded)
            on_chain_total_funded_display = _to_token_display(on_chain_total_funded)
            on_chain_target_display = _to_token_display(on_chain_target)
            on_chain_remaining_display = _to_token_display(on_chain_remaining)
        except Exception:
            pass

    return render_template(
        "investor/asset_detail.html",
        asset=asset,
        on_chain_total_funded=on_chain_total_funded,
        on_chain_target=on_chain_target,
        on_chain_remaining=on_chain_remaining,
        on_chain_status=on_chain_status,
        on_chain_total_funded_display=on_chain_total_funded_display,
        on_chain_target_display=on_chain_target_display,
        on_chain_remaining_display=on_chain_remaining_display,
        token_symbol=(current_app.config.get("PAYMENT_MODE") or "usdt").upper(),
        token_decimals=get_token_decimals(current_app.config),
    )


@bp.route("/assets/<int:asset_id>/fund", methods=["POST"])
@login_required
def fund_asset(asset_id):
    if str(current_user.role or "") != UserRole.INVESTOR.value:
        abort(403)

    asset = Asset.query.get_or_404(asset_id)

    if asset.blockchain_asset_id is None:
        flash("This asset has not yet been registered on the blockchain and cannot be funded.", "error")
        return redirect(url_for("investor.asset_detail", asset_id=asset_id))

    if asset.status not in (AssetStatus.LISTED, AssetStatus.PARTIALLY_FUNDED):
        flash("This asset is not currently open for funding.", "error")
        return redirect(url_for("investor.asset_detail", asset_id=asset_id))

    amount_raw = request.form.get("amount", "").strip()
    if not amount_raw:
        flash("Investment amount is required.", "error")
        return redirect(url_for("investor.asset_detail", asset_id=asset_id))

    try:
        amount_human = Decimal(amount_raw)
    except (InvalidOperation, ValueError):
        flash("Invalid amount.", "error")
        return redirect(url_for("investor.asset_detail", asset_id=asset_id))

    if amount_human <= 0:
        flash("Amount must be greater than zero.", "error")
        return redirect(url_for("investor.asset_detail", asset_id=asset_id))

    token_decimals = get_token_decimals(current_app.config)
    try:
        amount_wei = to_base_units(amount_human, token_decimals)
    except TokenDecimalError as exc:
        flash(str(exc), "error")
        return redirect(url_for("investor.asset_detail", asset_id=asset_id))

    config = _get_blockchain_config()
    on_chain_id = asset.blockchain_asset_id

    result = prepare_and_fund(on_chain_id, amount_wei, config)

    if result.funded:
        amount_human_display = from_base_units(result.requested_amount, token_decimals)
        tx_hash = result.transaction_hash
        log_index = None
        if result.events and "AssetFunded" in result.events:
            log_index = result.events["AssetFunded"].get("logIndex")

        if tx_hash and log_index is not None:
            existing_investment = Investment.query.filter_by(
                tx_hash=tx_hash, log_index=log_index
            ).first()
            if existing_investment is None:
                investment = Investment(
                    user_id=current_user.id,
                    asset_id=asset.id,
                    amount=amount_human_display,
                    tx_hash=tx_hash,
                    log_index=log_index,
                    status=InvestmentStatus.CONFIRMED,
                )
                db.session.add(investment)

                existing_tx = BlockchainTransaction.query.filter_by(
                    tx_hash=tx_hash, log_index=log_index
                ).first()
                if existing_tx is None:
                    blockchain_tx = BlockchainTransaction(
                        tx_hash=tx_hash,
                        log_index=log_index,
                        tx_type=TransactionType.FUND,
                        asset_id=asset.id,
                        status=TransactionStatus.CONFIRMED,
                        block_number=result.block_number,
                        gas_used=result.gas_used,
                    )
                    db.session.add(blockchain_tx)

                db.session.commit()

        flash(
            f"Investment submitted successfully! Transaction: {tx_hash}",
            "success",
        )
        return redirect(url_for("investor.asset_detail", asset_id=asset_id))

    flash(result.message or "Funding failed.", "error")
    return redirect(url_for("investor.asset_detail", asset_id=asset_id))
