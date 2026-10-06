"""Deterministic quote slot filling for the public assistant.

The manager extracts only customer-provided information. It never estimates
prices or sizing values; final figures must come from the official calculator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
import unicodedata
from typing import Any, Callable


QuoteFactory = Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]]

NUMBER_PATTERN = r"(\d+(?:[,.]\d+)?)"
DEVIS_MARKER_TEMPLATE = "<<<DEVIS_DATA:{payload}>>>"

QUOTE_INTENT_WORDS = (
    "devis",
    "estimation",
    "estimer",
    "prix",
    "tarif",
    "cout",
    "chiffrage",
    "offre",
)
INFO_QUESTION_WORDS = (
    "quelle difference",
    "explique",
    "comment",
    "pourquoi",
    "combien",
    "c'est quoi",
    "definition",
)
MANAGER_PROMPT_HINTS = (
    "pour preparer votre devis",
    "il me manque",
    "donnez-moi",
    "donnez moi",
)

CITY_NAMES = {
    "agadir": "Agadir",
    "ait melloul": "Ait Melloul",
    "beni mellal": "Beni Mellal",
    "el jadida": "El Jadida",
    "errachidia": "Errachidia",
    "essaouira": "Essaouira",
    "fes": "Fes",
    "kenitra": "Kenitra",
    "khemisset": "Khemisset",
    "khouribga": "Khouribga",
    "laayoune": "Laayoune",
    "marrakech": "Marrakech",
    "meknes": "Meknes",
    "mohammedia": "Mohammedia",
    "nador": "Nador",
    "ouarzazate": "Ouarzazate",
    "oujda": "Oujda",
    "rabat": "Rabat",
    "safi": "Safi",
    "sale": "Sale",
    "settat": "Settat",
    "tanger": "Tanger",
    "taroudant": "Taroudant",
    "temara": "Temara",
    "tiznit": "Tiznit",
}
DEFAULT_COMPANY_NAME = "HELIANTHA"


def load_company_name() -> str:
    try:
        from ..db import list_company_settings

        settings = {
            str(row.get("key") or "").strip().lower(): str(row.get("value") or "").strip()
            for row in list_company_settings()
        }
    except Exception:
        settings = {}
    return settings.get("company_name") or settings.get("name") or DEFAULT_COMPANY_NAME


@dataclass
class AssistantDevisSlots:
    project: str = ""
    pump_existing: bool | None = None
    existing_pump_cv: float | None = None
    flow_m3_h: float | None = None
    hmt_m: float | None = None
    monthly_consumption_kwh: float | None = None
    phase: str = ""
    meter_type: str = ""
    name: str = ""
    phone: str = ""
    city: str = ""


@dataclass
class AssistantDevisResponse:
    handled: bool
    content: str = ""
    quote: dict[str, Any] | None = None
    project: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    contact: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)


def normalize_text(value: str) -> str:
    text = str(value or "").replace("m\u00b3", "m3")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return text.lower()


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def first_number(patterns: tuple[str, ...], text: str) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            number = parse_float(match.group(1))
            if number is not None:
                return number
    return None


def latest_number(patterns: tuple[str, ...], texts: list[str]) -> float | None:
    for text in reversed(texts):
        number = first_number(patterns, normalize_text(text))
        if number is not None:
            return number
    return None


def user_messages(messages: list[dict[str, str]]) -> list[str]:
    return [
        str(message.get("content") or "").strip()
        for message in messages
        if message.get("role") == "user" and str(message.get("content") or "").strip()
    ]


def latest_user_message(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "").strip()
    return ""


def previous_assistant_prompt(messages: list[dict[str, str]]) -> bool:
    for message in reversed(messages[-4:]):
        if message.get("role") != "assistant":
            continue
        normalized = normalize_text(str(message.get("content") or ""))
        if any(hint in normalized for hint in MANAGER_PROMPT_HINTS):
            return True
    return False


def has_quote_intent(text: str) -> bool:
    normalized = normalize_text(text)
    return any(word in normalized for word in QUOTE_INTENT_WORDS)


def is_information_question(text: str) -> bool:
    normalized = normalize_text(text)
    return any(word in normalized for word in INFO_QUESTION_WORDS)


def extract_project(text: str) -> str:
    normalized = normalize_text(text)
    if any(token in normalized for token in ("hybride", "hybrid", "batterie", "batteries", "stockage")):
        return "hybrid"
    if any(token in normalized for token in ("pompage", "pompe", "forage", "irrigation", "puits", "m3/h", "m3h", "hmt")):
        return "pumping"
    if any(
        token in normalized
        for token in (
            "autoconsommation",
            "on-grid",
            "ongrid",
            "raccorde reseau",
            "reseau",
            "reduction de facture",
            "reduire ma consommation",
            "electricite",
            "photovoltaique",
            "photovoltaic",
            "pv",
        )
    ):
        return "photovoltaic"
    return ""


def extract_phone(text: str) -> str:
    compact_candidates = re.findall(r"(?:\+?212|0)[\s.\-]*(?:5|6|7)(?:[\s.\-]*\d){8}", text)
    if not compact_candidates:
        return ""
    raw = compact_candidates[-1]
    digits = re.sub(r"\D+", "", raw)
    if digits.startswith("212"):
        return "+" + digits
    if digits.startswith("0"):
        return digits
    return raw.strip()


def clean_name(value: str) -> str:
    name = re.split(r"\b(?:tel|telephone|phone|ville|localisation|adresse)\b|[0-9]", value, maxsplit=1, flags=re.IGNORECASE)[0]
    name = re.sub(r"\s+", " ", name.replace(":", " ")).strip(" ,.;:-")
    cities = "|".join(re.escape(city) for city in CITY_NAMES)
    city_suffix = re.search(rf"\s+(?:a|sur)\s+(?:{cities})\b", normalize_text(name))
    if city_suffix:
        name = name[:city_suffix.start()].strip()
    if len(name) < 2:
        return ""
    blocked = {"client", "devis", "pompage", "solaire", "bonjour", "salut"}
    if normalize_text(name) in blocked:
        return ""
    return name[:60]


def extract_name(text: str) -> str:
    patterns = (
        r"(?:je m['\u2019]appelle|mon nom(?:\s+est)?|mon pr[ée]nom(?:\s+est)?|nom\s*:|client\s*:)\s*([^,.;\n]+)",
        r"(?:moi c'est|moi cest)\s*([^,.;\n]+)",
    )
    matches = [match for pattern in patterns for match in re.finditer(pattern, text, flags=re.IGNORECASE)]
    for match in sorted(matches, key=lambda item: item.start(), reverse=True):
        name = clean_name(match.group(1))
        if name:
            return name
    return ""


def contextual_name(text: str, assistant_prompt: str) -> str:
    """Use the assistant's question as a hint, never as a source of customer facts."""
    if not re.search(r"\b(?:votre|ton|le)\s+(?:nom|prenom)\b", normalize_text(assistant_prompt)):
        return ""
    if not re.fullmatch(r"[^\W\d_]+(?:[ '\u2019-][^\W\d_]+){0,5}", text.strip()):
        return ""
    normalized = normalize_text(text)
    if extract_project(text) or extract_city(text) or normalized in {
        "oui", "non", "ok", "merci", "bonjour", "salut", "salam", "d'accord", "solaire",
        "comment", "pourquoi", "combien", "quel", "quelle", "explique",
    }:
        return ""
    return clean_name(text)


def extract_city(text: str) -> str:
    normalized = normalize_text(text)
    for key, city in CITY_NAMES.items():
        if re.search(rf"\b{re.escape(normalize_text(key))}\b", normalized):
            return city

    patterns = (
        r"(?:ville|localisation|adresse)\s*:?\s*([a-z' -]{2,35})",
        r"(?:je suis|nous sommes|site|chantier)\s+(?:a|sur)\s+([a-z' -]{2,35})",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        city = re.split(r"\b(?:tel|telephone|phone|debit|hmt|conso|consommation)\b|[,.;\n0-9]", match.group(1), maxsplit=1, flags=re.IGNORECASE)[0]
        city = re.sub(r"\s+", " ", city).strip(" ,.;:-")
        if city:
            return city[:40]
    return ""


def extract_phase(text: str) -> str:
    normalized = normalize_text(text)
    if re.search(r"\b(tri|triphase|380\s*v?)\b", normalized):
        return "triphase"
    if re.search(r"\b(mono|monophase|220\s*v?)\b", normalized):
        return "monophase"
    return ""


def extract_meter_type(text: str) -> str:
    normalized = normalize_text(text)
    if "mecanique" in normalized:
        return "mecanique"
    if "numerique" in normalized or "digital" in normalized:
        return "numerique"
    return ""


def extract_slots(messages: list[dict[str, str]]) -> AssistantDevisSlots:
    texts = user_messages(messages)
    raw_text = "\n".join(texts)
    normalized = normalize_text(raw_text)
    slots = AssistantDevisSlots()
    assistant_prompt = ""
    for message in messages:
        if message.get("role") == "assistant":
            assistant_prompt = str(message.get("content") or "")
            continue
        if message.get("role") != "user":
            continue
        text = str(message.get("content") or "").strip()
        # New customer corrections override earlier values; assistant content never does.
        slots.project = extract_project(text) or slots.project
        slots.phone = extract_phone(text) or slots.phone
        slots.name = extract_name(text) or contextual_name(text, assistant_prompt) or slots.name
        slots.city = extract_city(text) or slots.city
        slots.phase = extract_phase(text) or slots.phase
        slots.meter_type = extract_meter_type(text) or slots.meter_type
        assistant_prompt = ""

    existing_cv = latest_number(
        (
            rf"(?:pompe|puissance)[^\n,.;]{{0,30}}?{NUMBER_PATTERN}\s*(?:cv|ch|hp)\b",
            rf"\b{NUMBER_PATTERN}\s*(?:cv|ch|hp)\b",
        ),
        texts,
    )
    slots.existing_pump_cv = existing_cv

    if existing_cv is not None:
        slots.pump_existing = True
    elif any(token in normalized for token in ("pas de pompe", "sans pompe", "besoin d'une pompe", "besoin dune pompe", "recommandation de pompe")):
        slots.pump_existing = False
    elif any(token in normalized for token in ("deja une pompe", "pompe existe", "pompe existante", "j'ai une pompe", "jai une pompe")):
        slots.pump_existing = True

    slots.flow_m3_h = latest_number(
        (
            rf"\b{NUMBER_PATTERN}\s*(?:m3\s*/?\s*h|m3h)\b",
            rf"(?:debit)[^\n,.;]{{0,24}}?{NUMBER_PATTERN}",
        ),
        texts,
    )
    slots.hmt_m = latest_number(
        (
            rf"(?:hmt|hauteur|profondeur)[^\n,.;]{{0,24}}?{NUMBER_PATTERN}\s*(?:m|metres?)?\b",
            rf"\b{NUMBER_PATTERN}\s*(?:m|metres?)\s*(?:hmt|de hmt|hauteur|profondeur)\b",
        ),
        texts,
    )
    if slots.flow_m3_h is not None or slots.hmt_m is not None:
        slots.pump_existing = slots.pump_existing if slots.pump_existing is not None else False

    slots.monthly_consumption_kwh = latest_number(
        (
            rf"\b{NUMBER_PATTERN}\s*(?:kwh|kw h)\s*(?:/|par)?\s*(?:mois|mensuel|mensuelle)?\b",
            rf"(?:consommation|conso)[^\n,.;]{{0,30}}?{NUMBER_PATTERN}\s*(?:kwh)?\b",
        ),
        texts,
    )
    return slots


def should_handle_devis(messages: list[dict[str, str]], slots: AssistantDevisSlots) -> bool:
    latest = latest_user_message(messages)
    all_text = "\n".join(user_messages(messages))
    quote_intent = has_quote_intent(all_text)
    collecting = previous_assistant_prompt(messages)

    # A technical question can interrupt collection without discarding earlier customer facts.
    if is_information_question(latest) and not has_quote_intent(latest):
        return False
    if quote_intent:
        return True
    if collecting and (slots.project or slots.phone or slots.city or slots.name):
        return True
    if is_information_question(latest):
        return False
    if slots.project and slots.phone and (slots.city or slots.name):
        return True
    return False


def project_label(project: str) -> str:
    return {
        "pumping": "pompage solaire",
        "photovoltaic": "autoconsommation solaire",
        "hybrid": "solaire hybride avec batteries",
    }.get(project, "projet solaire")


def missing_slots(slots: AssistantDevisSlots) -> list[str]:
    missing: list[str] = []
    if not slots.project:
        return ["project"]

    if slots.project == "pumping":
        if slots.existing_pump_cv is not None:
            pass
        elif slots.pump_existing is True:
            missing.append("existing_pump_cv")
        elif slots.flow_m3_h is None or slots.hmt_m is None:
            if slots.pump_existing is None:
                missing.append("pumping_need")
            else:
                if slots.flow_m3_h is None:
                    missing.append("flow_m3_h")
                if slots.hmt_m is None:
                    missing.append("hmt_m")
    elif slots.project == "photovoltaic":
        if slots.monthly_consumption_kwh is None:
            missing.append("monthly_consumption_kwh")
        if not slots.phase:
            missing.append("phase")
    elif slots.project == "hybrid":
        if slots.monthly_consumption_kwh is None:
            missing.append("monthly_consumption_kwh")

    if not slots.name:
        missing.append("name")
    if not slots.phone:
        missing.append("phone")
    if not slots.city:
        missing.append("city")
    return missing


def build_data(slots: AssistantDevisSlots) -> dict[str, Any]:
    if slots.project == "pumping":
        if slots.existing_pump_cv is not None:
            return {
                "pump_existing": True,
                "existing_pump_cv": slots.existing_pump_cv,
                "city": slots.city,
            }
        return {
            "pump_existing": False,
            "flow_m3_h": slots.flow_m3_h,
            "hmt_m": slots.hmt_m,
            "city": slots.city,
        }

    if slots.project == "photovoltaic":
        return {
            "meter_type": slots.meter_type or "numerique",
            "phase": slots.phase or "monophase",
            "monthly_consumption_kwh": slots.monthly_consumption_kwh,
            "city": slots.city,
        }

    if slots.project == "hybrid":
        return {
            "monthly_consumption_kwh": slots.monthly_consumption_kwh,
            "phase": "monophase",
            "voltage_v": 220,
            "city": slots.city,
        }

    return {}


def build_contact(slots: AssistantDevisSlots) -> dict[str, Any]:
    return {
        "name": slots.name,
        "phone": slots.phone,
        "location": slots.city,
        "email": "",
    }


def question_for_missing(slots: AssistantDevisSlots, missing: list[str]) -> str:
    if "project" in missing:
        return "Avec plaisir. Quel projet souhaitez-vous estimer : pompage solaire, autoconsommation ou solaire hybride avec batteries ?"

    if "pumping_need" in missing:
        return (
            "Pour preparer votre devis de pompage solaire, dites-moi si vous avez deja une pompe. "
            "Si oui, donnez sa puissance en CV. Sinon, donnez le debit en m3/h et la HMT en metres."
        )

    technical_labels = {
        "existing_pump_cv": "la puissance de la pompe en CV",
        "flow_m3_h": "le debit souhaite en m3/h",
        "hmt_m": "la HMT en metres",
        "monthly_consumption_kwh": "la consommation mensuelle en kWh",
        "phase": "le type de branchement, monophase ou triphase",
    }
    contact_labels = {
        "name": "votre nom",
        "phone": "votre telephone",
        "city": "votre ville",
    }
    requested = [technical_labels[key] for key in missing if key in technical_labels]
    requested.extend(contact_labels[key] for key in missing if key in contact_labels)
    if not requested:
        requested = ["les informations manquantes"]
    return f"Pour preparer votre devis {project_label(slots.project)}, il me manque {format_list(requested)}."


def format_list(items: list[str]) -> str:
    clean = [item for item in items if item]
    if len(clean) <= 1:
        return clean[0] if clean else ""
    if len(clean) == 2:
        return f"{clean[0]} et {clean[1]}"
    return ", ".join(clean[:-1]) + f" et {clean[-1]}"


def quote_marker_payload(quote: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": quote.get("id"),
        "ref": quote.get("ref") or quote.get("quote_number"),
        "total_ttc": quote.get("total_ttc"),
        "kwc": quote.get("kwc", ""),
        "panels": quote.get("panels", ""),
        "inverter": quote.get("inverter", ""),
        "pdf_url": quote.get("pdf_url") or quote.get("download_url"),
        "view_url": quote.get("view_url"),
        "system_summary": quote.get("system_summary"),
    }


def final_content_for_quote(quote: dict[str, Any], company_name: str | None = None) -> str:
    company_name = str(company_name or load_company_name() or DEFAULT_COMPANY_NAME).strip()
    payload = json.dumps(quote_marker_payload(quote), ensure_ascii=False, separators=(",", ":"))
    ref = quote.get("ref") or quote.get("quote_number") or "votre devis"
    total = quote.get("total_ttc") or ""
    summary = quote.get("system_summary") or f"solution {company_name}"
    text = f"Parfait, j'ai genere le devis {ref} avec le moteur {company_name} officiel."
    if total:
        text += f" Total TTC : {total}."
    text += f" Solution : {summary}. Le PDF est pret ci-dessous."
    return f"{text}\n{DEVIS_MARKER_TEMPLATE.format(payload=payload)}"


class AssistantDevisManager:
    """Progressive deterministic manager for quote conversations."""

    def handle(self, messages: list[dict[str, str]], quote_factory: QuoteFactory | None = None) -> AssistantDevisResponse:
        slots = extract_slots(messages)
        if not should_handle_devis(messages, slots):
            return AssistantDevisResponse(handled=False)

        missing = missing_slots(slots)
        if missing:
            return AssistantDevisResponse(
                handled=True,
                content=question_for_missing(slots, missing),
                project=slots.project,
                missing=missing,
            )

        data = build_data(slots)
        contact = build_contact(slots)
        if quote_factory is None:
            return AssistantDevisResponse(
                handled=True,
                content="J'ai les informations necessaires pour preparer le devis.",
                project=slots.project,
                data=data,
                contact=contact,
            )

        quote = quote_factory(slots.project, data, contact)
        if quote.get("error"):
            return AssistantDevisResponse(
                handled=True,
                content=f"Je n'ai pas pu finaliser le devis avec ces informations : {quote['error']}",
                project=slots.project,
                data=data,
                contact=contact,
            )

        return AssistantDevisResponse(
            handled=True,
            content=final_content_for_quote(quote),
            quote=quote,
            project=slots.project,
            data=data,
            contact=contact,
        )
