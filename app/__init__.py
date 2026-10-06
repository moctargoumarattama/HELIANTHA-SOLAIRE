import os
import threading
import time

from flask import Flask


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
    app.config.from_mapping(
        SECRET_KEY="heliantha-smart-quote-dev",
        JSON_SORT_KEYS=False,
        DATABASE=os.path.join(app.instance_path, "heliantha.db"),
        ADMIN_PASSWORD=os.environ.get("HELIANTHA_ADMIN_PASSWORD", "heliantha2026"),
        TRUSTED_PROXY_HOPS=int(os.environ.get("TRUSTED_PROXY_HOPS", "0")),
    )
    if test_config:
        app.config.update(test_config)

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
    app.teardown_appcontext(close_db)
    os.makedirs(app.instance_path, exist_ok=True)
    with app.app_context():
        init_db()
    _start_whatsapp_outbox_worker(app)
    return app
