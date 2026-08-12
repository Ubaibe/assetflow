from datetime import datetime, timedelta
from flask import jsonify, request
from flask_login import login_user, logout_user
from .services import create_challenge, verify_signature, AuthError


def init_routes(bp):
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
            return jsonify({
                "authenticated": True,
                "user_id": user.id,
                "wallet_address": wallet_address,
            }), 200
        except AuthError as e:
            return jsonify({"error": str(e)}), 401

    @bp.route("/logout", methods=["POST"])
    def logout():
        logout_user()
        return jsonify({"authenticated": False}), 200
