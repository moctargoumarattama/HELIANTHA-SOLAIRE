from __future__ import annotations

from .rules import contains_any, fuzzy_score, normalize


INTENT_KEYWORDS = {
    "greeting": ["bonjour", "salut", "bonsoir", "salam"],
    "thanks": ["merci", "choukran"],
    "restart": ["restart", "recommencer", "nouveau projet", "reprendre a zero"],
    "correct_information": ["finalement", "en fait", "je me suis trompe", "correction", "ce n est pas", "pas ", "desole c est"],
    "ask_price": ["prix", "cout", "combien", "budget", "devis"],
    "request_pdf": ["pdf", "telecharger", "pre devis", "pre-devis", "fiche"],
    "request_human": ["visite", "rappeler", "appelez", "commercial", "whatsapp", "humain", "quelqu un"],
    "request_visit": ["technicien", "venir sur place", "passer chez moi", "visite"],
    "ask_explanation": ["c est quoi", "explique", "pourquoi", "signifie", "dure combien", "combien de temps"],
    "ask_equipment": ["materiel", "equipement", "panneau", "onduleur", "batterie", "pompe", "borne", "variateur"],
    "request_quote": ["calculer", "lancer", "preparer", "estimation"],
    "change_project": ["je veux pas", "pas une pompe", "pas une borne", "finalement je veux"],
    "start_project": ["je veux", "j ai", "installer", "besoin", "projet"],
}


def detect_intents(message: str, examples: list[dict] | None = None) -> list[dict]:
    text = normalize(message)
    found: dict[str, int] = {}
    for intent, keywords in INTENT_KEYWORDS.items():
        for keyword in keywords:
            score = 100 if contains_any(text, [keyword]) else fuzzy_score(text, keyword)
            if score >= 84:
                found[intent] = max(found.get(intent, 0), score)

    for item in examples or []:
        intent = item.get("intent") or ""
        if not intent:
            continue
        score = max(
            fuzzy_score(text, item.get("example_text", "")),
            fuzzy_score(text, item.get("normalized_text", "")),
        )
        if score >= 84:
            found[intent] = max(found.get(intent, 0), score)

    if not found:
        return [{"intent": "give_information", "confidence": 55}]
    ordered = sorted(found.items(), key=lambda item: item[1], reverse=True)
    return [{"intent": intent, "confidence": confidence} for intent, confidence in ordered]


def detect_intent(message: str, examples: list[dict] | None = None) -> str:
    return detect_intents(message, examples=examples)[0]["intent"]
