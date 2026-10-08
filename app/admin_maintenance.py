"""Compact maintenance workspace, with authenticated AJAX actions."""
import sqlite3
import threading

from flask import Blueprint, current_app, jsonify, render_template, request, session

from .db import get_db
from .services import maintenance_service as maintenance


bp = Blueprint("maintenance", __name__, url_prefix="/admin/maintenance")


@bp.app_context_processor
def navigation_context():
    return {"maintenance_available": True}


@bp.before_request
def require_session():
    # The global admin guard also protects this blueprint.
    if not session.get("admin_user"):
        return jsonify(success=False, message="Veuillez vous reconnecter."), 401


@bp.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.before_app_request
def public_maintenance_gate():
    if not request.path.startswith("/api/"):
        return None
    mode = maintenance.read_state("mode", {})
    if mode.get("enabled") is True:
        response = jsonify(error="Le service est en maintenance. Merci de réessayer dans quelques instants.",
                           error_code="maintenance", maintenance=True)
        response.status_code = 503
        response.headers["Retry-After"] = "60"
        response.headers["Cache-Control"] = "no-store"
        return response


@bp.get("")
def page():
    return render_template("admin/maintenance.html", can_manage=maintenance.can_manage())


@bp.get("/snapshot")
def snapshot():
    return jsonify(success=True, snapshot=maintenance.summary())


@bp.post("/checks/<kind>")
def check(kind):
    if kind not in {"services", "integrity", "ai"}:
        return jsonify(success=False, message="Contrôle inconnu."), 404
    lock = current_app.extensions["maintenance_lock"]
    if not lock.acquire(blocking=False):
        return jsonify(success=False, message="Un contrôle est déjà en cours. Patientez quelques instants."), 409
    try:
        if kind == "services":
            maintenance.check_services()
            message = "Vérification des services terminée."
        elif kind == "integrity":
            maintenance.check_integrity()
            message = "Analyse de cohérence terminée."
        else:
            result = maintenance.test_ai()
            message = result["message"]
        return jsonify(success=True, message=message, snapshot=maintenance.summary())
    except (sqlite3.Error, OSError):
        return jsonify(success=False, message="Le contrôle n’a pas pu être terminé. Réessayez dans quelques instants."), 503
    finally:
        lock.release()


@bp.get("/temporary-files")
def temporary_files():
    try:
        return jsonify(success=True, **maintenance.temporary_inventory())
    except (OSError, ValueError):
        return jsonify(success=False, message="Le dossier temporaire ne peut pas être contrôlé."), 409


@bp.post("/actions/<action>")
def action(action):
    if not maintenance.can_manage():
        return jsonify(success=False, message="Cette action est réservée à la Direction."), 403
    if action not in {"cache", "cleanup", "mode"}:
        return jsonify(success=False, message="Action inconnue."), 404
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or payload.get("confirmed") is not True:
        return jsonify(success=False, message="Confirmez l’action avant de continuer."), 400
    if action == "mode" and type(payload.get("enabled")) is not bool:
        return jsonify(success=False, message="Choisissez un état de maintenance valide."), 400
    lock = current_app.extensions["maintenance_lock"]
    if not lock.acquire(blocking=False):
        return jsonify(success=False, message="Une opération est déjà en cours."), 409
    try:
        actor = session["admin_user"]
        if action == "cache":
            maintenance.clear_calculation_cache()
            message = "Cache de calcul invalidé. Les prochains calculs rechargeront les données."
        elif action == "cleanup":
            result = maintenance.clean_temporary_files()
            message = f"{result['removed']} fichier(s) temporaire(s) nettoyé(s), {result['skipped']} ignoré(s)."
        else:
            message = "Mode maintenance activé." if payload["enabled"] else "API publiques Flask remises en service."
        with get_db():
            if action == "mode":
                maintenance.write_state("mode", {"enabled": payload["enabled"], "updated_at": maintenance.now(), "actor": actor})
            maintenance.event_log(action, message, actor)
        return jsonify(success=True, message=message, snapshot=maintenance.summary())
    except (OSError, ValueError, sqlite3.Error):
        return jsonify(success=False, message="L’opération n’a pas pu être confirmée. Vérifiez l’état avant de réessayer."), 503
    finally:
        lock.release()


def init_app(app):
    app.extensions["maintenance_lock"] = threading.Lock()
    app.register_blueprint(bp)
