from flask import Flask
from flask_login import LoginManager, login_required
from database import db
from config import Config
from auth import bp as auth_bp
from borrower import bp as borrower_bp
from investor import bp as investor_bp


login_manager = LoginManager()


@login_manager.unauthorized_handler
def unauthorized():
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

    @app.route("/public")
    def public_route():
        return {"message": "Public"}

    with app.app_context():
        db.create_all()

    return app
