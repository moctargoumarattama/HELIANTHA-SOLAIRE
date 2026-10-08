import os
import threading
import time

from flask import Flask, request
from flask_wtf.csrf import CSRFProtect, generate_csrf
from dotenv import load_dotenv


load_dotenv()
csrf = CSRFProtect()


_whatsapp_worker_started = False


def _start_whatsapp_outbox_worker(app):
    global _whatsapp_worker_started
    if _whatsapp_worker_started or app.config.get("TESTING"):
        return
    _whatsapp_worker_started = True

    def worker():
        while True:
            time.sleep(60)
            try:
                with app.app_context():
                    from .services.whatsapp_service import process_outbox

                    process_outbox()
            except Exception:
                app.logger.exception("WhatsApp outbox worker failed")

    threading.Thread(target=worker, name="whatsapp-outbox-worker", daemon=True).start()


def create_app(test_config=None):
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    configured_secret = os.environ.get("SECRET_KEY")
    app.config.from_mapping(
        SECRET_KEY=configured_secret,
        WTF_CSRF_ENABLED=True,
        WTF_CSRF_CHECK_DEFAULT=False,
        JSON_SORT_KEYS=False,
        MOBILE_API_BASE_URL=os.environ.get("MOBILE_API_BASE_URL", "").strip() or "http://127.0.0.1:8011",
        DATABASE=os.path.join(app.instance_path, "heliantha.db"),
        ADMIN_PASSWORD=os.environ.get("HELIANTHA_ADMIN_PASSWORD", "heliantha2026"),
        TRUSTED_PROXY_HOPS=int(os.environ.get("TRUSTED_PROXY_HOPS", "0")),
    )
    if test_config:
        app.config.update(test_config)
    if app.config.get("TESTING") and not (test_config and "WTF_CSRF_ENABLED" in test_config):
        app.config["WTF_CSRF_ENABLED"] = False

    if not app.config.get("SECRET_KEY"):
        if app.config.get("TESTING"):
            app.config["SECRET_KEY"] = "test-secret-key-heliantha"
        else:
            raise RuntimeError(
                "CRITIQUE : La variable SECRET_KEY n'est pas définie dans l'environnement / .env"
            )

    # CSRF is deliberately checked only for the server-rendered administration.
    # JSON API clients and webhooks authenticate through their own mechanisms.
    csrf.init_app(app)

    @app.context_processor
    def _csrf_template_helpers():
        return {
            "csrf_token": lambda: (
                generate_csrf() if app.config.get("WTF_CSRF_ENABLED") else ""
            )
        }
    app.jinja_env.globals["csrf_token"] = lambda: (
        generate_csrf() if app.config.get("WTF_CSRF_ENABLED") else ""
    )

    @app.before_request
    def _protect_admin_csrf():
        if (
            app.config.get("WTF_CSRF_ENABLED")
            and request.path.startswith("/admin")
            and request.method in {"POST", "PUT", "PATCH", "DELETE"}
        ):
            csrf.protect()

    if app.config["TRUSTED_PROXY_HOPS"] > 0:
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(
            app.wsgi_app, x_for=app.config["TRUSTED_PROXY_HOPS"],
            x_proto=0, x_host=0, x_port=0, x_prefix=0,
        )

    from .services.anti_abuse import AssistantQuota, PhoneCooldown

    app.extensions["assistant_quota"] = AssistantQuota()
    app.extensions["whatsapp_cooldown"] = PhoneCooldown()
    app.extensions["whatsapp_outbox_lock"] = threading.Lock()

    from .routes import bp
    from .db import close_db, init_db

    app.register_blueprint(bp)
    from .admin_maintenance import init_app as init_maintenance
    init_maintenance(app)
    app.teardown_appcontext(close_db)
    os.makedirs(app.instance_path, exist_ok=True)
    with app.app_context():
        init_db()
    _start_whatsapp_outbox_worker(app)
    return app
