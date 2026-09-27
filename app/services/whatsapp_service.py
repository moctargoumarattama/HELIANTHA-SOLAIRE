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
    pdf_link = f"{base_url}{pdf_url}" if pdf_url.startswith("/") else f"{base_url}/{pdf_url}"

    client_msg = (
        f"Bonjour *{client_name}*,\n\n"
        f"Merci d'avoir fait confiance a *HeliAntha* pour votre projet de *{project_type}*.\n\n"
        f"Votre estimation officielle est prete :\n"
        f"Montant estimatif : *{total_ttc}*\n\n"
        f"*Telechargez votre devis officiel (PDF) :*\n"
        f"{pdf_link}\n\n"
        f"Un ingenieur de notre equipe reste a votre disposition pour planifier une visite technique si vous le souhaitez.\n\n"
        f"_L'equipe HeliAntha Maroc_"
    )
    if client_phone:
        send_whatsapp_raw(client_phone, client_msg, gateway_url=gateway_url)

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
