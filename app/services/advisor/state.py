from __future__ import annotations

from copy import deepcopy
from uuid import uuid4


def default_state() -> dict:
    return {
        "session_id": uuid4().hex,
        "project_type": None,
        "project_confidence": 0,
        "current_intent": None,
        "last_question_id": None,
        "pending_question_id": None,
        "suspended_question_id": None,
        "wizard_step": None,
        "collected_data": {},
        "missing_data": [],
        "answered_fields": [],
        "current_topic": "",
        "previous_topic": "",
        "clarification_count": 0,
        "conversation_stack": [],
        "question_counts": {},
        "last_fallback_key": "",
        "active_offer": "",
        "quote_id": None,
        "quote_reference": None,
    }


def merge_state(saved: dict | None, incoming: dict | None = None) -> dict:
    state = default_state()
    if saved:
        state.update(saved)
    if incoming:
        state.update({key: value for key, value in incoming.items() if value is not None})
    state["collected_data"] = {
        **((saved or {}).get("collected_data") or {}),
        **((incoming or {}).get("collected_data") or {}),
    }
    state["answered_fields"] = list(dict.fromkeys([
        *(((saved or {}).get("answered_fields")) or []),
        *(((incoming or {}).get("answered_fields")) or []),
        *(state["collected_data"].keys()),
    ]))
    state["conversation_stack"] = list((incoming or {}).get("conversation_stack") or (saved or {}).get("conversation_stack") or [])
    state["question_counts"] = {
        **((saved or {}).get("question_counts") or {}),
        **((incoming or {}).get("question_counts") or {}),
    }
    return state


def public_state(state: dict) -> dict:
    clean = deepcopy(state)
    clean.pop("history", None)
    return clean
