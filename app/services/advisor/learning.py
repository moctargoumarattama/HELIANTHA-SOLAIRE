from __future__ import annotations

from .rules import fuzzy_score, is_unknown_answer, normalize


IGNORED_UNKNOWNS = {"bonjour", "salut", "merci", "ok", "oui", "non", "au revoir"}


def unknown_reason(
    message: str,
    state: dict,
    *,
    low_confidence: bool = False,
    ambiguous_project: bool = False,
    no_faq: bool = False,
    repeated_clarification: bool = False,
) -> str:
    if repeated_clarification:
        return "Conversation bloquee apres plusieurs clarifications"
    if ambiguous_project:
        return "Projet ambigu"
    if no_faq:
        return "Question frequente sans reponse fiable"
    if low_confidence:
        return "Compréhension insuffisante"
    if not state.get("project_type"):
        return "Projet non reconnu"
    if state.get("last_question_id"):
        return "Reponse non comprise pour la question courante"
    return "Aucune regle fiable"


def should_queue_unknown(
    message: str,
    state: dict,
    intents: list[dict] | None = None,
    *,
    ambiguous_project: bool = False,
    faq_found: bool = False,
    low_confidence: bool = False,
    fallback: bool = False,
) -> str | None:
    text = normalize(message)
    if not text or text in IGNORED_UNKNOWNS:
        return None
    if is_unknown_answer(text):
        return None
    if ambiguous_project:
        return unknown_reason(message, state, ambiguous_project=True)
    if intents and intents[0]["intent"] == "unknown":
        return unknown_reason(message, state, low_confidence=True)
    if low_confidence:
        return unknown_reason(message, state, low_confidence=True)
    if intents and intents[0]["intent"] in {"ask_explanation", "ask_equipment", "ask_price"} and not faq_found:
        return unknown_reason(message, state, no_faq=True)
    if state.get("clarification_count", 0) >= 2:
        return unknown_reason(message, state, repeated_clarification=True)
    if fallback:
        return unknown_reason(message, state)
    return None


def similar_occurrence_count(target: dict, rows: list[dict]) -> int:
    baseline = normalize(target.get("normalized_message") or target.get("original_message") or "")
    if not baseline:
        return 1
    total = 0
    for row in rows:
        candidate = normalize(row.get("normalized_message") or row.get("original_message") or "")
        if not candidate:
            continue
        if candidate == baseline or fuzzy_score(candidate, baseline) >= 86:
            total += 1
    return max(total, 1)
