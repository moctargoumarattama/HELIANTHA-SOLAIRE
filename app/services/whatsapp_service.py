"""WhatsApp gateway notifications for generated quotes."""

from __future__ import annotations

import logging
import os
from typing import Any

import requests


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


def notify_quote_created(quote_data: dict[str, Any]) -> None:
    """Notify the client and the administrator after a quote is generated."""

    client_phone = str(quote_data.get("client_phone") or "").strip()
    client_name = str(quote_data.get("client_name") or "Client").strip() or "Client"
    project_type = str(quote_data.get("project_type") or "Projet Solaire").strip() or "Projet Solaire"
    total_ttc = str(quote_data.get("total_ttc") or "-").strip() or "-"
    gateway_url = str(quote_data.get("whatsapp_gateway_url") or WHATSAPP_GATEWAY_URL).strip()
    admin_phone = str(quote_data.get("admin_whatsapp") or ADMIN_PHONE).strip()
    base_url = str(quote_data.get("app_base_url") or BASE_URL).strip().rstrip("/")
    pdf_url = str(quote_data.get("pdf_url") or "").strip()
    pdf_link = _absolute_url(base_url, pdf_url)

    client_msg = (
        f"Bonjour *{client_name}*,\n\n"
        f"Merci d'avoir fait confiance a *HeliAntha* pour votre projet de *{project_type}*.\n\n"
        f"Votre estimation officielle est prete :\n"
        f"Montant estimatif : *{total_ttc}*\n\n"
        f"Un ingenieur de notre equipe reste a votre disposition pour planifier une visite technique si vous le souhaitez.\n\n"
        f"_L'equipe HeliAntha Maroc_"
    )
    if client_phone:
        filename = str(quote_data.get("pdf_filename") or "Devis_HeliAntha.pdf").strip() or "Devis_HeliAntha.pdf"
        sent_document = send_whatsapp_document(
            client_phone,
            pdf_link,
            filename,
            client_msg,
            gateway_url=gateway_url,
        )
        if not sent_document:
            fallback_msg = (
                f"{client_msg}\n\n"
                f"*Lien de secours pour telecharger votre devis officiel (PDF) :*\n"
                f"{pdf_link}"
            )
            send_whatsapp_raw(client_phone, fallback_msg, gateway_url=gateway_url)

    if admin_phone:
        admin_msg = (
            "*NOUVEAU DEVIS GENERE SUR LE SITE !*\n\n"
            f"*Client :* {client_name}\n"
            f"*Telephone :* {client_phone or '-'}\n"
            f"*Ville :* {quote_data.get('city') or 'Non renseignee'}\n"
            f"*Projet :* {project_type}\n"
            f"*Montant :* {total_ttc}\n"
            f"*Lien Devis :* {pdf_link}"
        )
        send_whatsapp_raw(admin_phone, admin_msg, gateway_url=gateway_url)
