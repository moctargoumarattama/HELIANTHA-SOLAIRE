"""Local Ollama proxy helpers for the public HeliAntha assistant."""

from __future__ import annotations

import os
from typing import Any

import requests


OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "heliantha-ai")
ASSISTANT_FALLBACK_MESSAGE = (
    "Notre conseiller est actuellement tres sollicite. Vous pouvez lancer votre simulation "
    "directement via notre configurateur en ligne ou nous contacter par telephone."
)
MAX_MESSAGE_CHARS = 1000
MAX_MESSAGES = 12
ALLOWED_ROLES = {"system", "user", "assistant"}


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


def chat_with_ollama(messages: list[dict[str, str]]) -> dict[str, str]:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
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
