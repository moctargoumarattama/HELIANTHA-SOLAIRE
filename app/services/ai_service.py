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

    def has_any(*tokens: str) -> bool:
        return any(token in normalized for token in tokens)

    greeting_words = {"bonjour", "salut", "salam", "hello", "bonsoir", "cc"}
    if words & greeting_words and len(normalized) <= 80:
        return {
            "role": "assistant",
            "content": (
                "Bonjour, je suis le conseiller HeliAntha. Je peux vous orienter rapidement : "
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
                "Vous pouvez joindre HeliAntha au 05 30 13 35 83 ou sur WhatsApp au +212 661-575128. "
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
        "messages": messages,
        "stream": False,
        "keep_alive": "10m",
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
        "messages": messages,
        "stream": True,
        "keep_alive": "10m",
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
