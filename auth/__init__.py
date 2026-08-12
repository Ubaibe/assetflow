from flask import Blueprint
from .routes import init_routes

bp = Blueprint("auth", __name__, url_prefix="/auth")
init_routes(bp)
