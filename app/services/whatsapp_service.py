"""WhatsApp gateway notifications for generated quotes."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

from ..db import (
    enqueue_whatsapp_message,
    list_company_settings,
    list_whatsapp_outbox,
    mark_whatsapp_outbox_failed,
    mark_whatsapp_outbox_sent,
)


logger = logging.getLogger(__name__)

WHATSAPP_GATEWAY_URL = os.getenv("WHATSAPP_GATEWAY_URL", "http://127.0.0.1:3001/send-message")
ADMIN_PHONE = os.getenv("ADMIN_WHATSAPP", "0684056613")
BASE_URL = os.getenv("APP_BASE_URL", "https://devis.heliantha.ma").rstrip("/")


def get_whatsapp_base_url(gateway_url: str | None = None) -> str:
    value = str(gateway_url or WHATSAPP_GATEWAY_URL or "http://127.0.0.1:3001").strip()
    if value.endswith("/send-message"):
        value = value[: -len("/send-message")]
    if value.endswith("/send-document"):
        value = value[: -len("/send-document")]
    return value.rstrip("/")


def send_whatsapp_raw(phone: str, message: str, gateway_url: str | None = None) -> bool:
    """Send a WhatsApp message through the local Baileys gateway."""

    phone = str(phone or "").strip()
    message = str(message or "").strip()
    if not phone or not message:
        return False
    try:
        resp = requests.post(
            (gateway_url or WHATSAPP_GATEWAY_URL),
            json={"phone": phone, "message": message},
            timeout=5,
        )
        data = resp.json()
        if data.get("success"):
            logger.info("WhatsApp sent successfully to %s", phone)
            return True
        logger.warning("WhatsApp send failed to %s: %s", phone, data.get("error"))
        return False
    except Exception as exc:  # pragma: no cover - defensive logging path
        logger.error("WhatsApp gateway connection error: %s", exc)
        return False


def send_whatsapp_document(
    phone: str,
    pdf_url: str,
    filename: str,
    caption: str = "",
    gateway_url: str | None = None,
) -> bool:
    """Send a PDF document through the local Baileys gateway."""

    phone = str(phone or "").strip()
    pdf_url = str(pdf_url or "").strip()
    filename = str(filename or "Devis_HeliAntha.pdf").strip() or "Devis_HeliAntha.pdf"
    caption = str(caption or "").strip()
    if not phone or not pdf_url:
        return False

    base = get_whatsapp_base_url(gateway_url)
    try:
        resp = requests.post(
            f"{base}/send-document",
            json={
                "phone": phone,
                "pdf_url": pdf_url,
                "filename": filename,
                "caption": caption,
            },
            timeout=15,
        )
        data = resp.json()
        if data.get("success"):
            logger.info("WhatsApp document sent successfully to %s", phone)
            return True
        logger.warning("WhatsApp document send failed to %s: %s", phone, data.get("error"))
        return False
    except Exception as exc:  # pragma: no cover - defensive logging path
        logger.error("WhatsApp document gateway connection error: %s", exc)
        return False


def get_gateway_status(gateway_url: str | None = None) -> dict[str, Any]:
    """Return the local WhatsApp gateway status, or an offline payload."""

    base = get_whatsapp_base_url(gateway_url)
    try:
        response = requests.get(f"{base}/status", timeout=3)
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Invalid gateway status payload")
        data.setdefault("connected", False)
        data.setdefault("phone", None)
        data.setdefault("has_qr", False)
        data["online"] = True
        return data
    except Exception:
        return {"connected": False, "phone": None, "has_qr": False, "online": False}


def get_gateway_qr(gateway_url: str | None = None) -> dict[str, Any]:
    """Return the gateway QR payload as base64 image data."""

    base = get_whatsapp_base_url(gateway_url)
    try:
        response = requests.get(f"{base}/qr", timeout=3)
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Invalid gateway QR payload")
        data.setdefault("connected", False)
        data.setdefault("qr", None)
        return data
    except Exception:
        return {"connected": False, "qr": None, "error": "Passerelle injoignable"}


def gateway_logout(gateway_url: str | None = None) -> bool:
    """Ask the gateway to logout/reset its WhatsApp session."""

    base = get_whatsapp_base_url(gateway_url)
    try:
        response = requests.post(f"{base}/logout", timeout=5)
        data = response.json()
        return bool(data.get("success"))
    except Exception:
        return False


def _absolute_url(base_url: str, path_or_url: str) -> str:
    value = str(path_or_url or "").strip()
    if value.startswith(("http://", "https://")):
        return value
    base = str(base_url or BASE_URL).strip().rstrip("/")
    if value.startswith("/"):
        return f"{base}{value}"
    return f"{base}/{value}"


def _project_label(value: str) -> str:
    raw = str(value or "").strip()
    normalized = raw.lower()
    if "pompage" in normalized:
        return "Pompage solaire"
    if "on-grid" in normalized or "ongrid" in normalized or "reduction facture" in normalized:
        return "Installation solaire raccordee reseau"
    if "batter" in normalized or "hybride" in normalized or "hybrid" in normalized:
        return "Systeme solaire avec batteries"
    return raw or "Projet solaire"


def _gateway_url_from_settings() -> str:
    try:
        settings = {row["key"]: row["value"] for row in list_company_settings()}
        return str(settings.get("whatsapp_gateway_url") or WHATSAPP_GATEWAY_URL).strip()
    except Exception:
        return WHATSAPP_GATEWAY_URL


def process_outbox(limit: int = 10, gateway_url: str | None = None) -> dict[str, int]:
    """Replay pending WhatsApp messages when the gateway is connected."""

    gateway = str(gateway_url or _gateway_url_from_settings() or WHATSAPP_GATEWAY_URL).strip()
    status = get_gateway_status(gateway)
    if status.get("connected") is not True:
        return {"processed": 0, "sent": 0, "failed": 0, "pending": len(list_whatsapp_outbox("PENDING", limit))}

    sent = 0
    failed = 0
    pending_items = list_whatsapp_outbox("PENDING", limit, newest=False)
    for item in pending_items:
        success = False
        error_message = ""
        try:
            if item.get("msg_type") == "document":
                success = send_whatsapp_document(
                    item.get("phone", ""),
                    item.get("pdf_url", ""),
                    item.get("filename", "") or "Devis_HeliAntha.pdf",
                    item.get("caption", ""),
                    gateway_url=gateway,
                )
            else:
                success = send_whatsapp_raw(
                    item.get("phone", ""),
                    item.get("caption", ""),
                    gateway_url=gateway,
                )
            if success:
                mark_whatsapp_outbox_sent(item["id"])
                sent += 1
            else:
                error_message = "Echec envoi passerelle"
                attempts = int(item.get("attempts") or 0) + 1
                mark_whatsapp_outbox_failed(item["id"], attempts, error_message)
                failed += 1
        except Exception as exc:  # pragma: no cover - defensive safety net
            attempts = int(item.get("attempts") or 0) + 1
            mark_whatsapp_outbox_failed(item["id"], attempts, str(exc))
            failed += 1
        time.sleep(0.5)

    return {"processed": len(pending_items), "sent": sent, "failed": failed, "pending": 0}


def notify_quote_created(quote_data: dict[str, Any]) -> None:
    """Notify the client and the administrator after a quote is generated."""

    client_phone = str(quote_data.get("client_phone") or "").strip()
    client_name = str(quote_data.get("client_name") or "Client").strip() or "Client"
    project_type = _project_label(str(quote_data.get("project_type") or "Projet solaire"))
    total_ttc = str(quote_data.get("total_ttc") or "-").strip() or "-"
    gateway_url = str(quote_data.get("whatsapp_gateway_url") or WHATSAPP_GATEWAY_URL).strip()
    admin_phone = str(quote_data.get("admin_whatsapp") or ADMIN_PHONE).strip()
    base_url = str(quote_data.get("app_base_url") or BASE_URL).strip().rstrip("/")
    pdf_url = str(quote_data.get("pdf_url") or "").strip()
    pdf_link = _absolute_url(base_url, pdf_url)

    client_msg = (
        f"Bonjour *{client_name}*,\n\n"
        f"Veuillez trouver votre devis HeliAntha en piece jointe.\n\n"
        f"*Projet :* {project_type}\n"
        f"*Montant :* {total_ttc}\n\n"
        f"HeliAntha\n"
        f"Leader de l'energie solaire au Maroc"
    )
    if client_phone:
        filename = str(quote_data.get("pdf_filename") or "Devis_HeliAntha.pdf").strip() or "Devis_HeliAntha.pdf"
        enqueue_whatsapp_message(
            client_phone,
            "document",
            pdf_link,
            filename,
            client_msg,
        )

    if admin_phone:
        admin_msg = (
            "*DEVIS HELIANTHA*\n\n"
            f"*Client :* {client_name}\n"
            f"*Telephone :* {client_phone or '-'}\n"
            f"*Ville :* {quote_data.get('city') or 'Non renseignee'}\n"
            f"*Projet :* {project_type}\n"
            f"*Montant :* {total_ttc}"
        )
        filename = str(quote_data.get("pdf_filename") or "Devis_HeliAntha.pdf").strip() or "Devis_HeliAntha.pdf"
        enqueue_whatsapp_message(
            admin_phone,
            "document",
            pdf_link,
            filename,
            admin_msg,
        )

    process_outbox(gateway_url=gateway_url)
