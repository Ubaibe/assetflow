from flask import Flask, render_template, redirect, request, url_for
from flask_login import LoginManager, login_required
from database import db
from config import Config
from auth import bp as auth_bp
from borrower import bp as borrower_bp
from investor import bp as investor_bp
from marketplace.routes import bp as marketplace_bp


login_manager = LoginManager()
login_manager.login_view = "auth.login_page"


@login_manager.unauthorized_handler
def unauthorized():
    if request.accept_mimetypes.best_match(["application/json", "text/html"]) == "text/html":
        return redirect(url_for("auth.login_page", next=request.url))
    return {"error": "Unauthorized"}, 401


@login_manager.user_loader
def load_user(user_id):
    from database.models import User
    return User.query.get(int(user_id))


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    login_manager.init_app(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(borrower_bp)
    app.register_blueprint(investor_bp)
    app.register_blueprint(marketplace_bp)

    @app.route("/public")
    def public_route():
        return {"message": "Public"}

    @app.route("/")
    def index():
        return render_template("index.html")

    with app.app_context():
        db.create_all()

    return app
