from flask import Blueprint
from flask_login import login_required, current_user
from flask import render_template, request, redirect, url_for, flash, abort, current_app
from datetime import datetime
from pathlib import Path
from werkzeug.datastructures import FileStorage
from database import db
from database.models import Asset, InvoiceDocument
from database.state_machine import transition
from database.enums import AssetStatus, DocumentStatus
from services.document_processing import DocumentProcessor
from services.invoice_extraction_persistence import persist_extraction
from services.invoice_extraction_status import set_document_status
from services.invoice_pipeline import InvoicePipelineError, extract_invoice
from services.asset_registry_client import AssetRegistryClientError
from services.financing_submission import FinancingSubmissionResult, sanitize_message, submit_financing
from services.invoice_verification import verify_invoice_eligibility
from services.upload import validate_and_save_upload, UploadError


bp = Blueprint("borrower", __name__, url_prefix="/borrower")


def _get_user_wallet():
    if current_user.wallets:
        return current_user.wallets[0]
    return None


@bp.route("/dashboard")
@login_required
def dashboard():
    wallet = _get_user_wallet()
    assets = (
        Asset.query.filter_by(user_id=current_user.id)
        .order_by(Asset.created_at.desc())
        .all()
    )
    return render_template("borrower/dashboard.html", wallet=wallet, assets=assets)


@bp.route("/assets/new", methods=["GET"])
@login_required
def new_asset_form():
    return render_template("borrower/upload.html", max_upload_mb=current_app.config["MAX_UPLOAD_MB"])


@bp.route("/assets", methods=["POST"])
@login_required
def create_asset():
    if "invoice" not in request.files:
        flash("No file uploaded", "error")
        return redirect(url_for("borrower.new_asset_form"))

    file_storage = request.files["invoice"]
    if not file_storage:
        flash("No file selected", "error")
        return redirect(url_for("borrower.new_asset_form"))

    try:
        destination, original_filename, file_size, file_hash = validate_and_save_upload(file_storage)
    except UploadError as e:
        flash(str(e), "error")
        return redirect(url_for("borrower.new_asset_form"))

    try:
        existing = Asset.query.filter_by(asset_hash=file_hash, user_id=current_user.id).first()
        if existing:
            if destination.exists():
                destination.unlink(missing_ok=True)
            flash("This file has already been uploaded.", "error")
            return redirect(url_for("borrower.new_asset_form"))

        asset = Asset(
            user_id=current_user.id,
            asset_hash=file_hash,
            status=AssetStatus.DRAFT,
        )
        db.session.add(asset)
        db.session.flush()

        document = InvoiceDocument(
            asset_id=asset.id,
            original_filename=original_filename,
            stored_filename=destination.name,
            mime_type=file_storage.content_type or "application/octet-stream",
            file_size=file_size,
            file_hash=file_hash,
        )
        db.session.add(document)
        db.session.commit()

        processor = DocumentProcessor()
        doc_result = None
        try:
            with open(destination, "rb") as stream:
                doc_result = processor.process(
                    stream,
                    original_filename,
                    file_storage.content_type or "application/octet-stream",
                    current_app.config["MAX_UPLOAD_MB"] * 1024 * 1024,
                )
            document.processing_mode = doc_result.processing_mode
            set_document_status(db.session, document, DocumentStatus.PROCESSED)
            db.session.commit()
        except Exception:
            db.session.rollback()
            set_document_status(db.session, document, DocumentStatus.PROCESSING_FAILED)
            db.session.add(document)
            db.session.commit()

        extraction_result = None
        if doc_result is not None:
            try:
                ai_config = {
                    "AI_PROVIDER": current_app.config.get("AI_PROVIDER"),
                    "AI_MODE": current_app.config.get("AI_MODE"),
                    "AI_MODEL": current_app.config.get("AI_MODEL"),
                    "AGENTROUTER_API_KEY": current_app.config.get("AGENTROUTER_API_KEY"),
                    "AGENTROUTER_BASE_URL": current_app.config.get("AGENTROUTER_BASE_URL"),
                }
                with open(destination, "rb") as stream:
                    extraction_result = extract_invoice(
                        ai_config,
                        stream,
                        original_filename,
                        file_storage.content_type or "application/octet-stream",
                        current_app.config["MAX_UPLOAD_MB"] * 1024 * 1024,
                    )
            except InvoicePipelineError:
                set_document_status(db.session, document, DocumentStatus.EXTRACTION_FAILED)
                db.session.add(document)
                db.session.commit()

        extraction_persisted = False
        if extraction_result is not None:
            try:
                persist_extraction(db.session, asset.id, extraction_result, doc_result.processing_mode)
                set_document_status(db.session, document, DocumentStatus.EXTRACTED)
                db.session.commit()
                extraction_persisted = True
            except Exception:
                db.session.rollback()
                try:
                    set_document_status(db.session, document, DocumentStatus.EXTRACTION_FAILED)
                    db.session.add(document)
                    db.session.commit()
                except Exception:
                    db.session.rollback()

        verification = None
        if extraction_persisted:
            try:
                verification = verify_invoice_eligibility(
                    asset,
                    document,
                    today=datetime.utcnow().date(),
                )
            except Exception:
                pass

        submission = None
        if verification is not None and verification.eligible:
            wallet = _get_user_wallet()
            if not wallet:
                flash("Invoice is eligible for financing, but blockchain submission requires a connected wallet.", "warning")
            else:
                originator_address = wallet.address
                blockchain_config = {
                    "RPC_URL": current_app.config.get("RPC_URL"),
                    "ASSET_REGISTRY_ADDRESS": current_app.config.get("ASSET_REGISTRY_ADDRESS"),
                    "PRIVATE_KEY": current_app.config.get("PRIVATE_KEY"),
                    "CHAIN_ID": current_app.config.get("CHAIN_ID"),
                }
                try:
                    submission = submit_financing(
                        asset,
                        document,
                        today=datetime.utcnow(),
                        originator_address=originator_address,
                        config=blockchain_config,
                    )
                except AssetRegistryClientError:
                    submission = FinancingSubmissionResult(
                        submitted=False,
                        eligible=True,
                        message="AssetRegistry client error",
                    )

        if verification is not None and not verification.eligible:
            flash(
                f"Invoice uploaded successfully but is not eligible for financing: {verification.message}",
                "warning",
            )
        elif submission is not None and submission.submitted:
            if asset.blockchain_asset_id is None and submission.asset_id is not None:
                asset.blockchain_asset_id = submission.asset_id
                db.session.commit()
            flash("Invoice uploaded successfully and financing has been submitted to the blockchain", "success")
        elif submission is not None and not submission.submitted:
            flash(
                f"Invoice is eligible for financing but blockchain submission failed: {sanitize_message(submission.message)}",
                "warning",
            )
        elif verification is not None and verification.eligible:
            flash("Invoice uploaded successfully and is eligible for financing", "success")
        else:
            flash("Invoice uploaded successfully", "success")

        return redirect(url_for("borrower.asset_detail", asset_id=asset.id))
    except Exception:
        db.session.rollback()
        if destination.exists():
            destination.unlink(missing_ok=True)
        flash("Failed to save asset. Please try again.", "error")
        return redirect(url_for("borrower.new_asset_form"))


@bp.route("/assets/<int:asset_id>")
@login_required
def asset_detail(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    if asset.user_id != current_user.id:
        abort(404)

    document = (
        InvoiceDocument.query.filter_by(asset_id=asset.id)
        .order_by(InvoiceDocument.created_at.desc())
        .first()
    )
    return render_template("borrower/asset_detail.html", asset=asset, document=document)


@bp.route("/assets/<int:asset_id>/document")
@login_required
def download_document(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    if asset.user_id != current_user.id:
        abort(404)

    document = (
        InvoiceDocument.query.filter_by(asset_id=asset.id)
        .order_by(InvoiceDocument.created_at.desc())
        .first()
    )
    if not document:
        abort(404)

    upload_dir = Path(current_app.config["UPLOAD_DIR"])
    file_path = upload_dir / document.stored_filename
    if not file_path.exists():
        abort(404)

    from flask import send_file
    return send_file(
        file_path,
        mimetype=document.mime_type,
        as_attachment=False,
        download_name=document.original_filename,
    )
