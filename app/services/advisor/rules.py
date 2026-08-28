from __future__ import annotations

from difflib import SequenceMatcher
import re
import unicodedata

try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover - optional dependency fallback
    fuzz = None

try:
    from unidecode import unidecode
except Exception:  # pragma: no cover - optional dependency fallback
    unidecode = None


PROJECT_LABELS_PUBLIC = {
    "pumping": "Pompage solaire",
    "offgrid": "Site sans reseau",
    "ongrid": "Reduire ma consommation",
    "hybrid": "Solaire avec batteries",
    "thermal": "Chauffage solaire",
    "ev": "Recharge electrique",
}

PROJECT_KEYWORDS = {
    "pumping": [
        "pompe", "pompage", "forage", "puits", "irrigation", "irriguer",
        "eau", "reservoir", "debit", "hmt", "goutte a goutte",
    ],
    "offgrid": [
        "off grid", "off-grid", "sans reseau", "site isole", "site autonome",
        "pas de reseau", "hors reseau", "ferme sans electricite", "maison sans electricite",
    ],
    "ongrid": [
        "reduire facture", "facture electrique", "consommation", "autoconsommation",
        "panneaux maison", "entreprise solaire", "raccorde reseau", "on grid", "on-grid",
        "panneaux", "solaire maison",
    ],
    "hybrid": [
        "hybride", "batterie", "batteries", "coupure", "coupures", "secours",
        "continuite", "stockage", "reseau et batterie", "ca coupe", "courant part",
    ],
    "thermal": [
        "eau chaude", "chauffe eau", "chauffe-eau", "chauffage solaire",
        "ballon solaire", "thermique", "douche chaude",
    ],
    "ev": [
        "voiture electrique", "vehicule electrique", "borne", "recharge",
        "charger voiture", "chargeur voiture", "tesla", "ev",
    ],
}

SMS_REPLACEMENTS = {
    "c ": "c est ",
    "cest": "c est",
    "jsuis": "je suis",
    "j suis": "je suis",
    "j ai": "j ai",
    "jai": "j ai",
    "jveu": "je veux",
    "jveux": "je veux",
    "bcp": "beaucoup",
    "conso": "consommation",
    "elec": "electricite",
    "batteri": "batterie",
    "ya": "il y a",
    "pano": "panneau",
    "jsp": "je ne sais pas",
    "do": "eau",
    "lma": "eau",
    "dar": "maison",
    "casa": "casablanca",
}

YES_WORDS = {"oui", "yes", "ok", "d accord", "daccord", "bien sur", "exact", "deja"}
NO_WORDS = {"non", "no", "pas encore", "aucun", "jamais", "pas du tout"}
UNKNOWN_WORDS = {
    "je ne sais pas", "je sais pas", "aucune idee", "aucune idee", "je ne connais pas",
    "jsp", "je l ai pas", "je n ai pas la facture", "inconnu",
}


def normalize(text: str) -> str:
    value = str(text or "").strip().lower().replace("\u00a0", " ")
    if unidecode:
        value = unidecode(value)
    else:
        value = "".join(
            char for char in unicodedata.normalize("NFKD", value)
            if not unicodedata.combining(char)
        )
    value = re.sub(r"[’']", " ", value)
    value = re.sub(r"[^a-z0-9%.,/+ -]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    for source, target in SMS_REPLACEMENTS.items():
        value = value.replace(source, target)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def contains_any(text: str, words: list[str] | tuple[str, ...] | set[str]) -> bool:
    text = normalize(text)
    return any(normalize(word) in text for word in words)


def fuzzy_score(text: str, keyword: str) -> int:
    text = normalize(text)
    keyword = normalize(keyword)
    if not keyword:
        return 0
    if keyword in text:
        return 100
    if fuzz:
        return int(max(fuzz.partial_ratio(text, keyword), fuzz.token_set_ratio(text, keyword)))
    return int(SequenceMatcher(None, text, keyword).ratio() * 100)


def is_negated(text: str, keyword: str) -> bool:
    text = normalize(text)
    keyword = re.escape(normalize(keyword))
    patterns = [
        rf"\bpas\s+(de\s+|d\s+|une\s+|un\s+)?{keyword}\b",
        rf"\bne\s+\w+\s+pas\s+(de\s+|d\s+|une\s+|un\s+)?{keyword}\b",
        rf"\bpas\s+{keyword}\b",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def extract_dynamic_matches(text: str, synonyms: list[dict] | None = None) -> list[dict]:
    text = normalize(text)
    matches = []
    for item in synonyms or []:
        variant = normalize(item.get("variant", ""))
        canonical = normalize(item.get("canonical_term", ""))
        if not variant and not canonical:
            continue
        score = max(fuzzy_score(text, variant), fuzzy_score(text, canonical))
        if score >= 88:
            matches.append({**item, "score": score})
    return matches


def score_projects(
    text: str,
    synonyms: list[dict] | None = None,
    learned_examples: list[dict] | None = None,
) -> dict[str, int]:
    text = normalize(text)
    scores = {project: 0 for project in PROJECT_KEYWORDS}
    for project, keywords in PROJECT_KEYWORDS.items():
        for keyword in keywords:
            if is_negated(text, keyword):
                continue
            score = fuzzy_score(text, keyword)
            if score >= 90:
                scores[project] += 18
            elif score >= 78:
                scores[project] += 8

    for item in extract_dynamic_matches(text, synonyms):
        project = item.get("project_type") or ""
        if project in scores and not is_negated(text, item.get("variant", "")):
            scores[project] += 14

    for item in learned_examples or []:
        project = item.get("project_type") or ""
        if project not in scores:
            continue
        if is_negated(text, item.get("example_text", "")):
            continue
        score = max(
            fuzzy_score(text, item.get("normalized_text", "")),
            fuzzy_score(text, item.get("example_text", "")),
        )
        if score >= 86:
            scores[project] += 22
        elif score >= 78:
            scores[project] += 10

    if "maison" in text and contains_any(text, ["solaire", "panneau"]) and not contains_any(text, ["borne", "eau chaude"]):
        scores["ongrid"] += 8
        scores["offgrid"] += 8
        scores["hybrid"] += 8
    if contains_any(text, ["coupure", "ca coupe", "courant part", "coupures"]) and not is_negated(text, "coupure"):
        scores["hybrid"] += 26
    if contains_any(text, ["pas de reseau", "sans reseau", "hors reseau"]) or ("reseau" in text and contains_any(text, ["pas", "sans"])):
        scores["offgrid"] += 30
    if "maison" in text and "solaire" in text and "coupure" not in text:
        scores["ongrid"] += 8
    if "ferme" in text and contains_any(text, ["eau", "pompe", "forage", "irrigation"]):
        scores["pumping"] += 20
    return scores


def detect_project(
    text: str,
    synonyms: list[dict] | None = None,
    learned_examples: list[dict] | None = None,
) -> dict:
    normalized = normalize(text)
    scores = score_projects(normalized, synonyms=synonyms, learned_examples=learned_examples)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_project, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0
    if best_score < 18:
        return {"project": None, "confidence": 0, "ambiguous": False, "scores": scores}
    generic_house_solar = (
        "maison" in normalized
        and contains_any(normalized, ["solaire", "panneau", "panneaux"])
        and not contains_any(normalized, ["batterie", "coupure", "coupures", "sans reseau", "pas de reseau", "facture"])
    )
    return {
        "project": best_project,
        "confidence": min(100, best_score),
        "ambiguous": generic_house_solar or (best_score - second_score < 10 and second_score >= 18),
        "scores": scores,
    }


def yes_no(text: str) -> bool | None:
    normalized = normalize(text)
    if is_unknown_answer(normalized):
        return None
    if normalized in YES_WORDS or contains_any(normalized, YES_WORDS):
        return True
    if normalized in NO_WORDS or contains_any(normalized, NO_WORDS):
        return False
    return None


def is_unknown_answer(text: str) -> bool:
    normalized = normalize(text)
    return normalized in UNKNOWN_WORDS or contains_any(normalized, UNKNOWN_WORDS)
