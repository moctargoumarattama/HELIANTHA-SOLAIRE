"""Local Ollama proxy helpers for the public HeliAntha assistant."""

from __future__ import annotations

import os
import json
import re
import unicodedata
from typing import Any

import requests


OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "heliantha-ai")
ASSISTANT_FALLBACK_MESSAGE = (
    "Notre conseiller est actuellement tres sollicite. Vous pouvez lancer votre simulation "
    "directement via notre configurateur en ligne ou nous contacter par telephone."
)
MAX_MESSAGE_CHARS = 1000
MAX_MESSAGES = 8
ALLOWED_ROLES = {"system", "user", "assistant"}
DEVIS_DATA_RE = re.compile(r"<<<DEVIS_DATA:\s*(\{.*?\})\s*>>>", re.DOTALL)
OLLAMA_OPTIONS = {
    "temperature": 0.35,
    "num_predict": 220,
}
DEFAULT_COMPANY_PROFILE = {
    "company_name": "HELIANTHA",
    "city": "",
    "address": "Maroc",
    "phone": "",
    "whatsapp": "",
    "email": "",
}


def _clean_company_value(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _load_company_settings() -> dict[str, str]:
    try:
        from ..db import list_company_settings

        rows = list_company_settings()
    except Exception:
        rows = []
    return {
        str(row.get("key") or "").strip().lower(): _clean_company_value(row.get("value"))
        for row in rows
        if str(row.get("key") or "").strip()
    }


def company_profile_from_settings() -> dict[str, str]:
    settings = _load_company_settings()

    def pick(*keys: str, default: str = "") -> str:
        for key in keys:
            value = settings.get(key)
            if value:
                return value
        return default

    profile = dict(DEFAULT_COMPANY_PROFILE)
    profile.update(
        {
            "company_name": pick("company_name", "company", "name", "nom_entreprise", default=profile["company_name"]),
            "city": pick("city", "company_city", "ville", "ville_entreprise"),
            "address": pick("address", "company_address", "adresse", "adresse_entreprise", default=profile["address"]),
            "phone": pick("phone", "telephone", "tel", "company_phone"),
            "whatsapp": pick("whatsapp", "whatsapp_phone", "company_whatsapp"),
            "email": pick("email", "contact_email", "company_email"),
        }
    )
    return profile


def _unique_join(parts: list[str]) -> str:
    clean: list[str] = []
    seen = set()
    for part in parts:
        normalized = _normalize_text(part)
        if not part or normalized in seen:
            continue
        clean.append(part)
        seen.add(normalized)
    return ", ".join(clean)


def _join_channels(items: list[str]) -> str:
    if not items:
        return "via les coordonnees renseignees dans l'administration"
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} ou {items[1]}"
    return ", ".join(items[:-1]) + f" ou {items[-1]}"


def company_contact_channels(profile: dict[str, str] | None = None) -> str:
    profile = profile or company_profile_from_settings()
    channels = []
    if profile.get("phone"):
        channels.append(f"par telephone au {profile['phone']}")
    if profile.get("whatsapp"):
        channels.append(f"sur WhatsApp au {profile['whatsapp']}")
    if profile.get("email"):
        channels.append(f"par email a {profile['email']}")
    return _join_channels(channels)


def build_assistant_system_prompt(profile: dict[str, str] | None = None) -> str:
    profile = profile or company_profile_from_settings()
    company_name = profile.get("company_name") or DEFAULT_COMPANY_PROFILE["company_name"]
    location = _unique_join([profile.get("city", ""), profile.get("address", "")])
    intro = f"Tu es l'assistant de {company_name}, societe specialisee en energie solaire"
    if location:
        intro += f" situee a {location}"
    intro += "."

    return " ".join(
        [
            intro,
            f"Contacts officiels: {company_contact_channels(profile)}.",
            "Tu reponds en francais, clairement et avec un ton professionnel.",
            "Tu aides sur le pompage solaire, l'autoconsommation on-grid et le solaire hybride avec batteries.",
            "Pour un devis, collecte le type de projet, la ville du client, son nom, son telephone et les donnees techniques utiles.",
            "Quand toutes les donnees sont disponibles, ajoute le marqueur <<<DEVIS_DATA:{...}>>> avec un JSON compact compatible avec le configurateur.",
            "Ne donne pas de prix invente: les montants finaux viennent du calculateur officiel.",
        ]
    )


def messages_with_system_prompt(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    conversation = [message for message in messages if message.get("role") != "system"]
    return [{"role": "system", "content": build_assistant_system_prompt()}, *conversation]


def sanitize_messages(raw_messages: Any) -> list[dict[str, str]]:
    if not isinstance(raw_messages, list) or not raw_messages:
        raise ValueError("messages must be a non-empty list")

    sanitized: list[dict[str, str]] = []
    for item in raw_messages[-MAX_MESSAGES:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role not in ALLOWED_ROLES or not content:
            continue
        if role == "user":
            content = content[:MAX_MESSAGE_CHARS]
        else:
            content = content[:MAX_MESSAGE_CHARS * 2]
        sanitized.append({"role": role, "content": content})

    if not sanitized:
        raise ValueError("messages must contain at least one valid message")
    return sanitized


def fallback_response() -> dict[str, str]:
    return {"role": "assistant", "content": ASSISTANT_FALLBACK_MESSAGE}


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return text.lower()


def _latest_user_content(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "").strip()
    return ""


def quick_assistant_response(messages: list[dict[str, str]]) -> dict[str, str] | None:
    """Return only high-confidence local answers; None always means delegate to Ollama."""

    latest = _latest_user_content(messages)
    if not latest:
        return None
    normalized = _normalize_text(latest)
    words = set(re.findall(r"[a-z0-9+]+", normalized))
    user_count = sum(1 for message in messages if message.get("role") == "user")
    has_digits = bool(re.search(r"\d", normalized))
    company = company_profile_from_settings()
    company_name = company.get("company_name") or DEFAULT_COMPANY_PROFILE["company_name"]

    def has_any(*tokens: str) -> bool:
        return any(token in normalized for token in tokens)

    greeting_words = {"bonjour", "salut", "salam", "hello", "bonsoir", "cc"}
    if words & greeting_words and len(normalized) <= 80:
        return {
            "role": "assistant",
            "content": (
                f"Bonjour, je suis le conseiller {company_name}. Je peux vous orienter rapidement : "
                "pompage solaire, reduction de facture, site isole, batteries ou recharge electrique. "
                "Quel projet souhaitez-vous estimer ?"
            ),
        }

    if has_any("pompage", "pompe", "forage", "irrigation", "debit", "hmt") and not has_digits:
        return {
            "role": "assistant",
            "content": (
                "Pour le pompage solaire, il me faut surtout le debit souhaite en m3/h, la profondeur "
                "ou HMT, la ville et si une pompe existe deja. Avec ces elements, je peux vous orienter "
                "vers l'estimation pompage."
            ),
        }

    hybrid_quote_intent = has_any(
        "stockage",
        "batterie",
        "batteries",
        "solaire hybride",
        "solution hybride",
        "devis hybride",
        "installation hybride",
        "avec batterie",
        "avec batteries",
    )
    if hybrid_quote_intent and not has_digits:
        return {
            "role": "assistant",
            "content": (
                "Pour une solution solaire hybride avec stockage lithium, indiquez votre consommation mensuelle en kWh, "
                "votre ville, votre nom et votre telephone. Le dimensionnement sera prepare en 220V monophase."
            ),
        }

    if has_any("facture", "consommation", "electricite", "on-grid", "ongrid", "kwh", "economie") and not has_digits:
        return {
            "role": "assistant",
            "content": (
                "Pour reduire votre facture d'electricite, indiquez votre consommation mensuelle en kWh, "
                "votre type de compteur numerique ou mecanique, votre branchement mono ou tri, votre ville et votre telephone. Ensuite le configurateur "
                "peut preparer une estimation solaire raccordee reseau."
            ),
        }

    if has_any("devis", "prix", "tarif", "cout", "estimation", "pdf") and not has_digits and user_count <= 1:
        return {
            "role": "assistant",
            "content": (
                "Pour preparer un devis clair, envoyez le type de projet, votre ville, votre nom et votre "
                "telephone. Si c'est du pompage, ajoutez debit et HMT. Si c'est une facture, ajoutez la "
                "consommation mensuelle en kWh."
            ),
        }

    if has_any("contact", "whatsapp", "telephone", "tel", "appeler", "numero"):
        return {
            "role": "assistant",
            "content": (
                f"Vous pouvez joindre {company_name} {company_contact_channels(company)}. "
                "Si vous voulez, indiquez votre projet et votre ville, je vous oriente avant l'appel."
            ),
        }

    if has_any("ville", "localisation", "adresse"):
        return {
            "role": "assistant",
            "content": (
                "La ville sert a adapter l'estimation et la visite technique. Envoyez simplement votre ville "
                "ou commune, puis le type de projet a estimer."
            ),
        }

    return None


def extract_quote_request(content: str) -> tuple[str, dict[str, Any] | None]:
    text = str(content or "")
    match = DEVIS_DATA_RE.search(text)
    if not match:
        return text.strip(), None
    cleaned = DEVIS_DATA_RE.sub("", text).strip()
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return cleaned, None
    return cleaned, payload if isinstance(payload, dict) else None


def chat_with_ollama(messages: list[dict[str, str]]) -> dict[str, str]:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages_with_system_prompt(messages),
        "stream": False,
        "keep_alive": -1,
        "options": OLLAMA_OPTIONS,
    }
    try:
        response = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=45)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return fallback_response()
    except ValueError:
        return fallback_response()

    message = data.get("message") if isinstance(data, dict) else None
    content = str((message or {}).get("content") or "").strip()
    if not content:
        return fallback_response()
    return {"role": "assistant", "content": content}


def stream_ollama_chat(messages: list[dict[str, str]]):
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages_with_system_prompt(messages),
        "stream": True,
        "keep_alive": -1,
        "options": OLLAMA_OPTIONS,
    }
    try:
        with requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=45, stream=True) as response:
            response.raise_for_status()
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = data.get("message") if isinstance(data, dict) else None
                content = str((message or {}).get("content") or "")
                if content:
                    yield content
    except requests.RequestException:
        yield ASSISTANT_FALLBACK_MESSAGE
    except ValueError:
        yield ASSISTANT_FALLBACK_MESSAGE
