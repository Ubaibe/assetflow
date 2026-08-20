from datetime import datetime, timedelta
from flask import jsonify, request, render_template, session, current_app, redirect, url_for
from flask_login import login_required, login_user, logout_user, current_user
from .services import create_challenge, verify_signature, AuthError
from database import db
from database.enums import UserRole


def init_routes(bp):
    @bp.route("/", methods=["GET"])
    def login_page():
        next_url = request.args.get("next", "/")
        chain_id = current_app.config.get("CHAIN_ID")
        return render_template("auth/login.html", next_url=next_url, chain_id=chain_id)

    @bp.route("/onboarding")
    @login_required
    def onboarding():
        next_url = request.args.get("next", "")
        if current_user.role == UserRole.INVESTOR:
            return redirect(url_for("investor.dashboard"))
        if current_user.role == UserRole.BORROWER:
            return redirect(url_for("borrower.dashboard"))
        safe_next = _safe_next(next_url) or "/"
        return render_template("auth/onboarding.html", next_url=safe_next)

    @bp.route("/onboarding/role", methods=["POST"])
    @login_required
    def set_onboarding_role():
        if current_user.role is not None:
            return jsonify({"error": "Role already assigned"}), 409

        data = request.get_json(silent=True) or {}
        raw_role = data.get("role")
        next_url = _safe_next(data.get("next") or request.args.get("next", ""))

        if raw_role is None:
            return jsonify({"error": "role is required"}), 400

        try:
            role = UserRole(raw_role)
        except ValueError:
            return jsonify({"error": "Invalid role"}), 400

        current_user.role = role
        db.session.commit()

        if role == UserRole.INVESTOR:
            return jsonify({"authenticated": True, "role": "investor", "next": next_url or url_for("investor.dashboard")}), 200
        return jsonify({"authenticated": True, "role": "borrower", "next": next_url or url_for("borrower.dashboard")}), 200

    @bp.route("/challenge", methods=["POST"])
    def challenge():
        data = request.get_json(silent=True) or {}
        wallet_address = data.get("wallet_address")
        if not wallet_address:
            return jsonify({"error": "wallet_address is required"}), 400

        try:
            result = create_challenge(wallet_address)
            return jsonify(result), 201
        except AuthError as e:
            return jsonify({"error": str(e)}), 400

    @bp.route("/verify", methods=["POST"])
    def verify():
        data = request.get_json(silent=True) or {}
        wallet_address = data.get("wallet_address")
        signature = data.get("signature")
        challenge_id = data.get("challenge_id")

        if not wallet_address or not signature or not challenge_id:
            return jsonify({"error": "wallet_address, signature, and challenge_id are required"}), 400

        try:
            user = verify_signature(wallet_address, signature, challenge_id)
            login_user(user)
            role = user.role.value if hasattr(user.role, "value") and user.role else (user.role or None)
            return jsonify({
                "authenticated": True,
                "user_id": user.id,
                "wallet_address": wallet_address,
                "role": role,
            }), 200
        except AuthError as e:
            return jsonify({"error": str(e)}), 401

    @bp.route("/logout", methods=["POST"])
    def logout():
        logout_user()
        return jsonify({"authenticated": False}), 200


def _safe_next(next_url):
    if not next_url:
        return None
    if next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return None
