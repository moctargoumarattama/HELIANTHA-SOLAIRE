import os

from flask import Flask


def create_app(test_config=None):
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.from_mapping(
        SECRET_KEY="heliantha-smart-quote-dev",
        JSON_SORT_KEYS=False,
        DATABASE=os.path.join(app.instance_path, "heliantha.db"),
        ADMIN_PASSWORD=os.environ.get("HELIANTHA_ADMIN_PASSWORD", "heliantha2026"),
    )
    if test_config:
        app.config.update(test_config)

    from .routes import bp
    from .db import close_db, init_db

    app.register_blueprint(bp)
    app.teardown_appcontext(close_db)
    os.makedirs(app.instance_path, exist_ok=True)
    with app.app_context():
        init_db()
    return app
