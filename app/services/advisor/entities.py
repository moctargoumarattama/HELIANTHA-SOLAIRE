from __future__ import annotations

import re

from .rules import contains_any, extract_dynamic_matches, normalize, yes_no


KNOWN_CITIES = {
    "marrakech": "Marrakech",
    "casablanca": "Casablanca",
    "casa": "Casablanca",
    "agadir": "Agadir",
    "rabat": "Rabat",
    "tanger": "Tanger",
    "fes": "Fes",
    "meknes": "Meknes",
    "oujda": "Oujda",
    "laayoune": "Laayoune",
    "beni mellal": "Beni Mellal",
    "kenitra": "Kenitra",
    "safi": "Safi",
    "el jadida": "El Jadida",
}

LOAD_LABELS = {
    "frigo": "frigo",
    "refrigerateur": "frigo",
    "congelateur": "congelateur",
    "lumiere": "eclairage",
    "lumieres": "eclairage",
    "led": "eclairage",
    "wifi": "wifi",
    "internet": "wifi",
    "box": "wifi",
    "tv": "television",
    "tele": "television",
    "television": "television",
    "clim": "climatisation",
    "climatisation": "climatisation",
    "pompe": "pompe",
}

NUMBER_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(kwh\/mois|kwh\/j|kwh|m3\/j|m3|kw|w|m2|m|dh|jours?|jour|personnes?|km|v)?",
    re.IGNORECASE,
)


def _number(value: str) -> float | None:
    try:
        return float(value.replace(",", "."))
    except Exception:
        return None


def extract_entities(message: str, state: dict, synonyms: list[dict] | None = None) -> dict:
    text = normalize(message)
    data: dict = {}
    answered_fields: set[str] = set()
    current_topic = ""
    project = state.get("project_type")
    last_question = state.get("pending_question_id") or state.get("last_question_id")
    yesno = yes_no(text)

    city = extract_city(text)
    if city:
        data["city"] = city
        answered_fields.add("city")

    if _mentions_outages(text):
        data["outages"] = True
        answered_fields.add("outages")

    if _mentions_negative_asset(text, "pompe"):
        data["pump_existing"] = False
        answered_fields.add("pump_existing")
    elif _mentions_positive_asset(text, "pompe"):
        data["pump_existing"] = True
        answered_fields.add("pump_existing")

    if _mentions_negative_asset(text, "reseau"):
        data["network_existing"] = False
        answered_fields.add("network_existing")
    elif _mentions_positive_network(text):
        data["network_existing"] = True
        answered_fields.add("network_existing")

    if contains_any(text, ["monophase", "mono phase"]):
        data["phases"] = "monophase"
        answered_fields.add("phases")
    elif contains_any(text, ["triphase", "tri phase"]):
        data["phases"] = "triphase"
        answered_fields.add("phases")

    if yesno is not None and last_question:
        question_map = {
            "pump_existing": "pump_existing",
            "network_existing": "network_existing",
            "grid_connection": "network_existing",
        }
        key = question_map.get(last_question)
        if key:
            data[key] = yesno
            answered_fields.add(key)

    loads = extract_priority_loads(text)
    if loads:
        data["priority_loads"] = loads
        data["objective"] = ", ".join(loads)
        answered_fields.update({"priority_loads", "objective"})

    matches = list(extract_dynamic_matches(text, synonyms=synonyms))
    if matches:
        current_topic = matches[0].get("canonical_term") or matches[0].get("category") or ""
        if current_topic == "plaque_signaletique":
            answered_fields.add("plaque_signaletique")

    for match in NUMBER_RE.finditer(text):
        value = _number(match.group(1))
        if value is None:
            continue
        unit = normalize(match.group(2) or "")
        window = text[max(0, match.start() - 24): match.end() + 36]
        key = infer_number_key(window, last_question, project, unit)
        if not key:
            continue
        data[key] = value
        answered_fields.add(key)

    if "bill" not in data and contains_any(text, ["dh", "dirham", "mad", "facture"]):
        value = first_number(text)
        if value is not None:
            data["bill"] = value
            answered_fields.add("bill")

    if last_question == "monthly_kwh" and len(text.split()) <= 3 and first_number(text) is not None:
        numeric_value = first_number(text)
        if contains_any(text, ["dh", "dirham", "mad", "facture"]):
            data["bill"] = numeric_value
            answered_fields.add("bill")
        elif "monthly_kwh" not in data:
            data["monthly_kwh"] = numeric_value
            answered_fields.add("monthly_kwh")

    return {
        "data": data,
        "answered_fields": sorted(answered_fields),
        "current_topic": current_topic,
        "has_correction": contains_any(text, ["finalement", "en fait", "plutot", "je me suis trompe", "non c est", "c est pas", "ce n est pas", "desole c est"]),
    }


def infer_number_key(window: str, last_question: str | None, project: str | None, unit: str = "") -> str | None:
    window = normalize(window)
    if unit == "m3/j" or unit == "m3":
        return "water_need"
    if unit == "dh":
        return "bill"
    if unit == "m2":
        return "roof_area"
    if unit in {"kw", "w"}:
        if project == "ev" or contains_any(window, ["borne", "recharge"]):
            return "charger_power"
        if contains_any(window, ["disponible", "installation", "tableau"]):
            return "available_power"
        if contains_any(window, ["pompe"]) or last_question == "pump_power":
            return "pump_power"
        return "peak_kw"
    if unit == "kwh/mois":
        return "monthly_kwh"
    if unit == "kwh/j":
        return "daily_kwh"
    if unit in {"jour", "jours"}:
        return "autonomy"
    if unit in {"personne", "personnes"}:
        return "people"
    if unit == "km":
        return "daily_km"
    if unit == "m":
        if project == "pumping":
            if contains_any(window, ["distance"]):
                return "distance"
            if contains_any(window, ["hauteur", "elevation", "hmt"]):
                return "elevation"
            return "depth"
        return "depth"

    context_map = {
        "water_need": "water_need",
        "depth": "depth",
        "daily_kwh": "daily_kwh",
        "monthly_kwh": "monthly_kwh",
        "roof_area": "roof_area",
        "autonomy": "autonomy",
        "people": "people",
        "charger_power": "charger_power",
        "available_power": "available_power",
        "pump_power": "pump_power",
        "peak_kw": "peak_kw",
    }
    if last_question in context_map:
        if last_question == "monthly_kwh" and contains_any(window, ["dh", "dirham", "mad", "facture"]):
            return "bill"
        return context_map[last_question]

    if contains_any(window, ["metre cube", "eau par jour", "m3", "m 3"]):
        return "water_need"
    if contains_any(window, ["dh", "dirham", "mad", "facture"]):
        return "bill"
    if contains_any(window, ["toiture", "surface", "m2", "m 2"]):
        return "roof_area"
    if contains_any(window, ["kw", "puissance", "borne"]):
        if project == "ev" or contains_any(window, ["borne", "recharge"]):
            return "charger_power"
        if contains_any(window, ["disponible", "installation", "tableau"]):
            return "available_power"
        if contains_any(window, ["pompe"]) or last_question == "pump_power":
            return "pump_power"
        return "peak_kw"
    if contains_any(window, ["mois", "mensuel", "mensuelle"]):
        return "monthly_kwh"
    if contains_any(window, ["kwh/j", "par jour", "quotidienne"]):
        return "daily_kwh"
    if contains_any(window, ["autonomie", "jour", "jours"]):
        return "autonomy"
    if contains_any(window, ["personne", "personnes"]):
        return "people"
    if contains_any(window, ["km", "kilometre"]):
        return "daily_km"
    if contains_any(window, ["metre", "profondeur", "forage", "puits", "hmt"]):
        if project == "pumping":
            if contains_any(window, ["distance"]):
                return "distance"
            if contains_any(window, ["hauteur", "elevation", "hmt"]):
                return "elevation"
            return "depth"
        return "depth"
    return None


def first_number(text: str) -> float | None:
    match = NUMBER_RE.search(normalize(text))
    return _number(match.group(1)) if match else None


def extract_city(text: str) -> str:
    normalized = normalize(text)
    hits = []
    for key, label in KNOWN_CITIES.items():
        index = normalized.rfind(key)
        if index >= 0:
            hits.append((index, label))
    if not hits:
        return ""
    hits.sort(key=lambda item: item[0])
    return hits[-1][1]


def extract_priority_loads(text: str) -> list[str]:
    normalized = normalize(text)
    loads: list[str] = []
    for key, label in LOAD_LABELS.items():
        if key in normalized and label not in loads:
            loads.append(label)
    return loads


def _mentions_outages(text: str) -> bool:
    return contains_any(text, ["coupure", "coupures", "courant part", "courant coupe", "ca coupe", "beaucoup de coupure"])


def _mentions_negative_asset(text: str, asset: str) -> bool:
    patterns = [
        rf"\bje n ai pas de {asset}\b",
        rf"\bj ai pas de {asset}\b",
        rf"\bpas de {asset}\b",
        rf"\bsans {asset}\b",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _mentions_positive_asset(text: str, asset: str) -> bool:
    patterns = [
        rf"\bj ai deja une? {asset}\b",
        rf"\bil y a une? {asset}\b",
        rf"\bune? {asset} existe\b",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _mentions_positive_network(text: str) -> bool:
    return contains_any(text, ["raccorde au reseau", "deja raccorde", "j ai le reseau", "oui j ai le reseau", "avec reseau"])
