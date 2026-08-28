from __future__ import annotations

from .rules import fuzzy_score, normalize


DEFAULT_KNOWLEDGE = [
    {
        "category": "inverter",
        "title": "Onduleur",
        "question": "C'est quoi un onduleur ?",
        "answer": "L'onduleur transforme l'energie des panneaux pour qu'elle soit utilisable par votre installation.",
        "keywords": "onduleur courant alternatif convertisseur",
    },
    {
        "category": "battery",
        "title": "Batteries",
        "question": "Les batteries durent combien ?",
        "answer": "La duree depend du modele, de l'usage et de la profondeur de decharge. HeliAntha choisit une solution adaptee a votre besoin.",
        "keywords": "batterie batteries duree autonomie stockage",
    },
    {
        "category": "pumping",
        "title": "HMT",
        "question": "C'est quoi la HMT ?",
        "answer": "La HMT est la hauteur totale que la pompe doit vaincre entre le forage, le reservoir et les pertes du circuit.",
        "keywords": "hmt hauteur profondeur forage pompe pertes",
    },
    {
        "category": "pumping",
        "title": "Plaque signaletique",
        "question": "Je n'ai plus la plaque signaletique de la pompe.",
        "answer": "Ce n'est pas bloquant. Si vous avez une photo de la pompe, sa puissance ou sa tension, HeliAntha peut deja vous orienter.",
        "keywords": "plaque signaletique etiquette pompe photo moteur",
    },
    {
        "category": "quote",
        "title": "Prix",
        "question": "Quand puis-je avoir un prix ?",
        "answer": "Le prix apparait apres l'estimation. Il vient du moteur HeliAntha et du catalogue, pas du Conseiller.",
        "keywords": "prix devis budget estimation combien coute",
    },
    {
        "category": "general",
        "title": "Consommation",
        "question": "Je ne connais pas ma consommation.",
        "answer": "Vous pouvez donner votre facture moyenne ou vos appareils principaux. HeliAntha affinera ensuite l'etude.",
        "keywords": "consommation facture kwh maison appareils",
    },
]

KNOWLEDGE_PRIORITY = {
    "pumping": ["pumping", "drive", "general", "quote"],
    "offgrid": ["battery", "inverter", "general", "quote"],
    "hybrid": ["battery", "inverter", "general", "quote"],
    "ongrid": ["inverter", "general", "quote"],
    "thermal": ["thermal", "general", "quote"],
    "ev": ["ev", "general", "quote"],
}


def search_knowledge(message: str, project: str | None, rows: list[dict] | None = None) -> dict | None:
    text = normalize(message)
    priorities = KNOWLEDGE_PRIORITY.get(project or "", ["general", "quote"])
    best = None

    for item in rows or DEFAULT_KNOWLEDGE:
        category = str(item.get("category") or "general")
        haystack = normalize(" ".join([
            item.get("title", ""),
            item.get("question", ""),
            item.get("keywords", ""),
            category,
        ]))
        if not haystack:
            continue
        score = fuzzy_score(text, haystack)
        keyword_hits = 0
        for token in haystack.split():
            if len(token) >= 4:
                score = max(score, fuzzy_score(text, token))
                if token in text:
                    keyword_hits += 1
        score += keyword_hits * 8
        if normalize(item.get("question", "")) and fuzzy_score(text, item.get("question", "")) >= 80:
            score += 18
        if project and category == project:
            score += 12
        elif category in priorities:
            score += max(2, 10 - priorities.index(category) * 2)
        elif category == "general":
            score += 2
        if not best or score > best["score"]:
            best = {"score": score, "item": item}

    if best and best["score"] >= 72:
        return best["item"]
    return None
