from flask import Blueprint
from flask_login import login_required, current_user
from flask import render_template, request, redirect, url_for, flash, abort, current_app
from pathlib import Path
from werkzeug.datastructures import FileStorage
from database import db
from database.models import Asset, InvoiceDocument
from database.state_machine import transition
from database.enums import AssetStatus
from services.document_processing import DocumentProcessor
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
        try:
            with open(destination, "rb") as stream:
                doc_result = processor.process(
                    stream,
                    original_filename,
                    file_storage.content_type or "application/octet-stream",
                    current_app.config["MAX_UPLOAD_MB"] * 1024 * 1024,
                )
            document.processing_mode = doc_result.processing_mode
            db.session.commit()
        except Exception:
            db.session.rollback()

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
