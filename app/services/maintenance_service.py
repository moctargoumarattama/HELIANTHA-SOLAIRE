"""Bounded, on-demand administration diagnostics; no business data repairs."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import socket
import stat
import time

import requests
from flask import current_app, has_app_context

from ..db import get_db, invalidate_calculation_context


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def deployment_context():
    """Use this server's actual configuration, never the browser's Host header."""
    from .ai_service import OLLAMA_HOST, OLLAMA_MODEL
    from .whatsapp_service import _gateway_url_from_settings, get_whatsapp_base_url
    host = socket.gethostname()
    targets = {
        "mobile": str(current_app.config.get("MOBILE_API_BASE_URL") or "http://127.0.0.1:8011").strip().rstrip("/"),
        "ollama": OLLAMA_HOST,
        "model": OLLAMA_MODEL,
        "whatsapp": get_whatsapp_base_url(_gateway_url_from_settings()),
    }
    identity = {"host": host, "database": str(Path(current_app.config["DATABASE"]).resolve()), **targets}
    signature = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return {"host": host, "id": signature, "targets": targets}


def read_state(key, default=None):
    row = get_db().execute("SELECT value FROM maintenance_state WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except (ValueError, TypeError):
        return default


def write_state(key, value):
    get_db().execute(
        "INSERT INTO maintenance_state(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value, ensure_ascii=False)),
    )


def save_check(key, value):
    value = {**value, "deployment_id": deployment_context()["id"]}
    with get_db():
        write_state(key, value)
    return value


def record_ai_observation(success, started, source="assistant"):
    """Record only timing and a safe incident label, never prompts or errors."""
    if not has_app_context():
        return
    event = {"at": now(), "duration_ms": round((time.perf_counter()-started)*1000),
             "success": bool(success), "source": source}
    if not success:
        event["message"] = "Le modèle n’a pas fourni de réponse exploitable."
    try:
        event["deployment_id"] = deployment_context()["id"]
        with get_db():
            write_state("ai_last_run", event)
            write_state("ai_last_success" if success else "ai_last_incident", event)
    except (sqlite3.Error, OSError):
        # Telemetry must never interrupt chat or streaming.
        current_app.logger.warning("Assistant monitoring could not be recorded")


def can_manage():
    from flask import session
    user = get_db().execute(
        "SELECT 1 FROM users WHERE username=? AND active=1 AND role='Direction'",
        (session.get("admin_user", ""),),
    ).fetchone()
    return user is not None


def event_log(action, message, actor):
    get_db().execute(
        "INSERT INTO maintenance_events(action, message, actor, created_at) VALUES (?, ?, ?, ?)",
        (action, message, actor, now()),
    )


def summary():
    from .ai_service import OLLAMA_MODEL
    deployment = deployment_context()

    def observation(key):
        value = read_state(key)
        if not isinstance(value, dict) or value.get("deployment_id") != deployment["id"]:
            return None
        return {k: v for k, v in value.items() if k != "deployment_id"}

    return {
        "deployment": {"host": deployment["host"]},
        "services": observation("services"), "integrity": observation("integrity"),
        "mode": read_state("mode", {"enabled": False}),
        "ai": {"model": OLLAMA_MODEL, "last_run": observation("ai_last_run"),
               "last_success": observation("ai_last_success"), "last_incident": observation("ai_last_incident")},
        "events": [dict(r) for r in get_db().execute(
            "SELECT action, message, actor, created_at FROM maintenance_events ORDER BY id DESC LIMIT 10")],
        "can_manage": can_manage(),
    }


def _probe(key, label, url, validate):
    started = time.perf_counter()
    state, detail = "error", "Connexion indisponible."
    try:
        response = requests.get(url, timeout=(2, 4), allow_redirects=False)
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("Unexpected status")
        state, detail = validate(response.json())
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        pass
    return {"key": key, "label": label, "status": state, "detail": detail,
            "duration_ms": round((time.perf_counter()-started)*1000)}


def check_services():
    targets = deployment_context()["targets"]
    db = get_db()
    started = time.perf_counter()
    items = [{"key": "flask", "label": "Site Flask", "status": "ok", "detail": "Serveur disponible.", "duration_ms": None}]
    try:
        db.execute("SELECT 1 FROM products LIMIT 1").fetchone()
        items.append({"key": "sqlite", "label": "Base SQLite", "status": "ok", "detail": "Lecture disponible.",
                      "duration_ms": round((time.perf_counter()-started)*1000)})
    except sqlite3.Error:
        items.append({"key": "sqlite", "label": "Base SQLite", "status": "error", "detail": "Lecture indisponible.", "duration_ms": None})
    gateway = targets["whatsapp"]
    mobile = targets["mobile"]

    def mobile_status(data):
        good = isinstance(data, dict) and data.get("success") is True and isinstance(data.get("data"), dict) and data["data"].get("status") == "ok"
        return ("ok", "API disponible.") if good else ("error", "Réponse de santé non reconnue.")

    def ollama_status(data):
        names = {m.get("name") for m in data.get("models", []) if isinstance(m, dict)}
        found = targets["model"] in names or targets["model"] + ":latest" in names
        return ("ok", "Modèle installé : " + targets["model"]) if found else ("warning", "Serveur disponible, modèle configuré absent.")

    def whatsapp_status(data):
        if data.get("connected") is True:
            return "ok", "Session WhatsApp connectée."
        return "warning", "Passerelle disponible, session à reconnecter."

    # No request-controlled URL and no automatic redirect to another service.
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(_probe, "ollama", "Ollama", targets["ollama"] + "/api/tags", ollama_status),
                   pool.submit(_probe, "whatsapp", "WhatsApp", gateway + "/status", whatsapp_status)]
        if mobile:
            futures.insert(0, pool.submit(_probe, "mobile", "API mobile", mobile + "/health", mobile_status))
        else:
            items.append({"key": "mobile", "label": "API mobile", "status": "unknown", "detail": "Adresse de supervision à configurer.", "duration_ms": None})
        items.extend(f.result() for f in futures)
    return save_check("services", {"items": items, "checked_at": now()})


def test_ai():
    from .ai_service import OLLAMA_HOST, OLLAMA_MODEL
    started = time.perf_counter()
    success = False
    try:
        response = requests.post(OLLAMA_HOST + "/api/chat", json={
            "model": OLLAMA_MODEL, "messages": [{"role": "user", "content": "Réponds uniquement : OK."}],
            "stream": False, "keep_alive": -1, "options": {"temperature": 0, "num_predict": 16},
        }, timeout=(2, 20), allow_redirects=False)
        response.raise_for_status()
        data = response.json()
        success = isinstance(data, dict) and isinstance(data.get("message"), dict) and bool(str(data["message"].get("content") or "").strip())
    except (requests.RequestException, ValueError, TypeError):
        pass
    record_ai_observation(success, started, source="test")
    return {"success": success, "message": "Le modèle a répondu au test." if success else "Le modèle ne répond pas pour le moment."}


def check_integrity():
    db = get_db()
    groups = []
    for key, title, where in (
        ("prices", "Produits actifs sans prix valide", "active=1 AND (sale_price IS NULL OR typeof(sale_price) NOT IN ('integer','real') OR sale_price<=0)"),
        ("power", "Panneaux actifs sans puissance valide", "active=1 AND category='panels' AND (power_w IS NULL OR typeof(power_w) NOT IN ('integer','real') OR power_w<50 OR power_w>1500)"),
    ):
        count = db.execute(f"SELECT COUNT(*) FROM products WHERE {where}").fetchone()[0]
        rows = db.execute(f"SELECT id, reference FROM products WHERE {where} ORDER BY id LIMIT 20").fetchall()
        groups.append({"key": key, "title": title, "count": count, "items": [{"label": r["reference"], "detail": "Produit n° " + str(r["id"])} for r in rows]})
    duplicates = "SELECT lower(trim(reference)) AS reference, COUNT(*) AS n FROM products GROUP BY lower(trim(reference)) HAVING COUNT(*)>1"
    count = db.execute("SELECT COUNT(*) FROM (" + duplicates + ")").fetchone()[0]
    rows = db.execute(duplicates + " ORDER BY reference LIMIT 20").fetchall()
    groups.append({"key": "duplicates", "title": "Références dupliquées (espaces et casse ignorés)", "count": count,
                   "items": [{"label": r["reference"], "detail": str(r["n"]) + " produits"} for r in rows]})
    problems, checked = [], 0
    invalid = 0

    def amount(value):
        value = Decimal(str(value))
        if not value.is_finite() or value < 0:
            raise ValueError("Invalid amount")
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    cursor = db.execute("SELECT quote_number, amount_ht, amount_ttc, financial_breakdown_json, result_json FROM quote_requests ORDER BY id DESC")
    for row in cursor:
        checked += 1
        issue = None
        try:
            financial = json.loads(row["financial_breakdown_json"] or "null")
            if not isinstance(financial, dict) or not financial:
                result = json.loads(row["result_json"] or "{}")
                financial = result.get("financial_breakdown", {})
            ht, vat, ttc = (amount(financial[k]) for k in ("total_ht", "vat", "total_ttc"))
            if ht + vat != ttc:
                issue = "Le total HT + TVA ne correspond pas au TTC."
            elif any(row[k] is not None and amount(row[k]) != expected for k, expected in (("amount_ht", ht), ("amount_ttc", ttc))):
                issue = "Les totaux enregistrés divergent du détail financier."
        except (ValueError, TypeError, KeyError, AttributeError, InvalidOperation):
            issue = "Totaux incomplets ou invalides : vérification nécessaire."
        if issue:
            invalid += 1
            if len(problems) < 20:
                problems.append({"label": row["quote_number"], "detail": issue})
    groups.append({"key": "quotes", "title": "Devis à vérifier", "count": invalid, "items": problems})
    return save_check("integrity", {"groups": groups, "count": sum(g["count"] for g in groups), "quotes_checked": checked,
                                    "products_checked": db.execute("SELECT COUNT(*) FROM products").fetchone()[0], "checked_at": now()})


def _temporary_files():
    """Only direct, old scratch files; never traverse links or delete documents."""
    instance = Path(current_app.instance_path).resolve()
    folder = instance / "tmp"
    if not folder.exists():
        return []
    folder_stat = folder.lstat()
    if folder.is_symlink() or getattr(folder_stat, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT or folder.resolve().parent != instance:
        raise ValueError("Le dossier temporaire doit être un dossier local de l’application.")
    candidates = []
    cutoff = time.time() - 86400
    with os.scandir(folder) as entries:
        for entry in entries:
            if len(candidates) >= 500:
                break
            if not entry.is_file(follow_symlinks=False) or Path(entry.name).suffix.lower() not in {".tmp", ".part", ".temp"}:
                continue
            info = entry.stat(follow_symlinks=False)
            if info.st_mtime >= cutoff or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                continue
            file = Path(entry.path)
            if file.resolve().parent == folder.resolve():
                candidates.append((file, info.st_size))
    return candidates


def temporary_inventory():
    files = _temporary_files()
    return {"count": len(files), "bytes": sum(size for _, size in files), "limit": 500}


def clean_temporary_files():
    removed, freed, skipped = 0, 0, 0
    for file, size in _temporary_files():
        try:
            # Recheck after inventory, before a non-recursive unlink.
            info = file.lstat()
            expected_parent = Path(current_app.instance_path).resolve() / "tmp"
            if file.resolve().parent != expected_parent or not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT or info.st_mtime >= time.time()-86400:
                skipped += 1
                continue
            file.unlink()
            removed += 1
            freed += size
        except OSError:
            skipped += 1
    return {"removed": removed, "bytes": freed, "skipped": skipped}


def clear_calculation_cache():
    invalidate_calculation_context()
