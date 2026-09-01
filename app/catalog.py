"""Catalogue product taxonomy, normalization and validation helpers.

This module deliberately has no Flask or database dependency. The admin UI,
SQLite layer and calculation engine can therefore share one authoritative
definition of product categories and technical fields.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse


CATALOG_CATEGORIES = {
    "panels": {
        "label": "Panneaux photovoltaïques",
        "aliases": ("panel", "panneau", "panneaux", "module", "modules", "pv", "solar_panel"),
    },
    "batteries": {
        "label": "Batteries",
        "aliases": ("battery", "batterie", "stockage", "storage"),
    },
    "inverters": {
        "label": "Onduleurs",
        "aliases": ("inverter", "onduleur", "onduleurs", "hybrid_inverter"),
    },
    "pumps": {
        "label": "Pompes",
        "aliases": ("pump", "pompe", "pompes"),
    },
    "drives": {
        "label": "Variateurs",
        "aliases": ("drive", "variateur", "variateurs", "vfd", "solar_pump_drive"),
    },
    "ev_chargers": {
        "label": "Bornes de recharge EV",
        "aliases": (
            "ev_charger",
            "charger",
            "chargeur",
            "borne",
            "bornes",
            "borne_ev",
            "bornes_ev",
        ),
    },
    "protections": {
        "label": "Protections",
        "aliases": ("protection", "coffret", "coffrets"),
    },
    "cables": {
        "label": "Cables",
        "aliases": ("cable", "cables", "cablage"),
    },
    "structures": {
        "label": "Structures",
        "aliases": ("structure", "support", "supports"),
    },
    "accessories": {
        "label": "Accessoires",
        "aliases": ("accessory", "accessoire", "accessoires"),
    },
    "thermal": {
        "label": "Solaire thermique",
        "aliases": (
            "thermique",
            "solar_thermal",
            "chauffe_eau",
            "chauffe_eau_solaire",
            "ballon",
            "capteur_thermique",
        ),
    },
    "other": {
        "label": "Autres produits",
        "aliases": ("autre", "autres", "misc", "divers", "other"),
    },
}


TECHNICAL_FIELDS = {
    "panels": [
        {"key": "power_w", "label": "Puissance du panneau", "kind": "number", "unit": "W", "required": True},
    ],
    "batteries": [
        {"key": "capacity_kwh", "label": "Capacité", "kind": "number", "unit": "kWh", "required": True},
    ],
    "inverters": [
        {"key": "type", "label": "Type", "kind": "choice", "choices": ("on_grid", "off_grid", "hybrid"), "required": True},
        {"key": "power_kw", "label": "Puissance", "kind": "number", "unit": "kW", "required": True},
        {"key": "phases", "label": "Phase", "kind": "choice", "choices": ("monophase", "triphase"), "required": True},
    ],
    "pumps": [
        {"key": "power_hp", "label": "Puissance", "kind": "number", "unit": "CV", "required": True},
        {"key": "power_kw", "label": "Puissance", "kind": "number", "unit": "kW"},
        {"key": "phases", "label": "Phase", "kind": "choice", "choices": ("monophase", "triphase")},
        {"key": "voltage_v", "label": "Tension", "kind": "number", "unit": "V"},
        {"key": "current_a", "label": "Courant", "kind": "number", "unit": "A"},
        {
            "key": "curve_points",
            "label": "Points Débit / HMT",
            "kind": "pump_curve",
            "unit": "m³/h : m",
            "required": True,
        },
    ],
    "drives": [
        {"key": "power_kw", "label": "Puissance", "kind": "number", "unit": "kW", "required": True},
        {"key": "phases", "label": "Phase", "kind": "choice", "choices": ("monophase", "triphase"), "required": True},
    ],
    "ev_chargers": [
        {"key": "power_kw", "label": "Puissance", "kind": "number", "unit": "kW", "required": True},
        {"key": "phases", "label": "Phase", "kind": "choice", "choices": ("monophase", "triphase")},
        {"key": "connector", "label": "Connecteur", "kind": "choice", "choices": ("Type 1", "Type 2", "CCS", "CHAdeMO")},
    ],
    "thermal": [
        {"key": "tank_volume_l", "label": "Volume du ballon", "kind": "number", "unit": "L", "required": True},
    ],
    "protections": [
        {"key": "protection_type", "label": "Type", "kind": "choice", "choices": ("Disjoncteur", "Parafoudre", "Fusible", "Sectionneur", "Coffret", "Autre"), "required": True},
        {"key": "current_a", "label": "Courant", "kind": "number", "unit": "A"},
        {"key": "dc_or_ac", "label": "Courant électrique", "kind": "choice", "choices": ("dc", "ac")},
    ],
    "cables": [
        {"key": "dc_or_ac", "label": "Type", "kind": "choice", "choices": ("dc", "ac")},
        {"key": "section_mm2", "label": "Section", "kind": "number", "unit": "mm²", "required": True},
    ],
    "structures": [
        {"key": "structure_type", "label": "Type de structure", "kind": "text", "unit": ""},
    ],
    "accessories": [],
    "other": [],
}


COMMON_NUMERIC_FIELDS = {
    "power_kw": "Puissance kW",
    "power_w": "Puissance W",
    "voltage": "Tension",
    "current_amp": "Courant",
    "capacity_kwh": "Capacite kWh",
    "capacity_l": "Capacite L",
    "purchase_price": "Prix d'achat",
    "sale_price": "Prix de vente",
    "stock": "Stock",
}


class ProductValidationError(ValueError):
    """Raised with field-specific messages for invalid catalogue data."""

    def __init__(self, errors: Mapping[str, str] | list[str] | str):
        if isinstance(errors, str):
            self.errors = {"product": errors}
        elif isinstance(errors, Mapping):
            self.errors = dict(errors)
        else:
            self.errors = {f"error_{index}": message for index, message in enumerate(errors)}
        super().__init__("; ".join(self.errors.values()))


def _token(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    ascii_value = "".join(character for character in normalized if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", "_", ascii_value).strip("_")


CATEGORY_ALIASES = {
    _token(alias): category
    for category, metadata in CATALOG_CATEGORIES.items()
    for alias in (category, *metadata.get("aliases", ()))
}


def category_options() -> list[dict[str, str]]:
    return [{"value": key, "label": item["label"]} for key, item in CATALOG_CATEGORIES.items()]


def normalize_category(value: Any) -> str:
    normalized = CATEGORY_ALIASES.get(_token(value))
    if not normalized:
        raise ProductValidationError({"category": "Categorie produit non reconnue."})
    return normalized


def category_label(value: Any) -> str:
    try:
        return CATALOG_CATEGORIES[normalize_category(value)]["label"]
    except ProductValidationError:
        return str(value or "")


def technical_fields_for(category: Any) -> list[dict[str, Any]]:
    try:
        return [dict(field) for field in TECHNICAL_FIELDS.get(normalize_category(category), [])]
    except ProductValidationError:
        return []


def technical_fields_by_category() -> dict[str, list[dict[str, Any]]]:
    return {key: technical_fields_for(key) for key in CATALOG_CATEGORIES}


def normalize_boolean(value: Any, *, default: bool | None = None) -> bool | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    normalized = _token(value)
    if normalized in {"1", "true", "yes", "oui", "on", "active", "actif"}:
        return True
    if normalized in {"0", "false", "no", "non", "off", "inactive", "inactif"}:
        return False
    raise ValueError("Valeur booleenne attendue (oui/non).")


def normalize_number(value: Any, *, field_label: str, integer: bool = False) -> float | int | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field_label} doit etre un nombre.")
    try:
        number = float(str(value).strip().replace(" ", "").replace(",", "."))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_label} doit etre un nombre.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field_label} doit etre un nombre fini.")
    if number < 0:
        raise ValueError(f"{field_label} ne peut pas etre negatif.")
    if integer:
        if not number.is_integer():
            raise ValueError(f"{field_label} doit etre un nombre entier.")
        return int(number)
    return number


def normalize_ratio(value: Any, *, field_label: str, default: float | None = None) -> float | None:
    number = normalize_number(value, field_label=field_label)
    if number is None:
        return default
    if number > 1:
        if number > 100:
            raise ValueError(f"{field_label} doit etre compris entre 0 et 100 %.")
        number /= 100
    if not 0 <= number <= 1:
        raise ValueError(f"{field_label} doit etre compris entre 0 et 100 %.")
    return float(number)


def normalize_pump_curve(value: Any) -> list[dict[str, float]]:
    if value is None or value == "":
        return []
    parsed = value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            points = []
            for line in re.split(r"[;\n]+", raw):
                if not line.strip():
                    continue
                parts = re.split(r"[:,|]", line, maxsplit=1)
                if len(parts) != 2:
                    raise ValueError("Courbe pompe invalide : utilisez debit:HMT, une ligne par point.")
                points.append(parts)
            parsed = points

    if isinstance(parsed, Mapping):
        parsed = list(parsed.items())
    if not isinstance(parsed, list):
        raise ValueError("La courbe pompe doit etre une liste de points debit/HMT.")

    result = []
    seen_flows: set[float] = set()
    for index, point in enumerate(parsed, start=1):
        if isinstance(point, Mapping):
            flow = point.get("flow_m3_h", point.get("flow", point.get("debit")))
            hmt = point.get("hmt_m", point.get("hmt", point.get("head")))
        elif isinstance(point, (list, tuple)) and len(point) == 2:
            flow, hmt = point
        else:
            raise ValueError(f"Point {index} de la courbe pompe invalide.")
        flow_value = normalize_number(flow, field_label=f"Debit du point {index}")
        hmt_value = normalize_number(hmt, field_label=f"HMT du point {index}")
        if flow_value is None or hmt_value is None:
            raise ValueError(f"Point {index} de la courbe pompe incomplet.")
        normalized_flow = float(flow_value)
        if normalized_flow in seen_flows:
            raise ValueError(f"Le débit {normalized_flow:g} m³/h est présent plusieurs fois.")
        seen_flows.add(normalized_flow)
        result.append({"flow_m3_h": normalized_flow, "hmt_m": float(hmt_value)})
    return sorted(result, key=lambda item: (item["flow_m3_h"], item["hmt_m"]))


def parse_technical_specs(value: Any) -> dict[str, Any]:
    if value is None or value == "":
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON technique invalide (ligne {exc.lineno}, colonne {exc.colno}).") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Les caracteristiques techniques JSON doivent former un objet.")
        return parsed
    raise ValueError("Les caracteristiques techniques doivent former un objet JSON.")


def normalize_technical_specs(
    category: str,
    value: Any,
    *,
    submitted_fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    specs = parse_technical_specs(value)
    metadata = TECHNICAL_FIELDS.get(category, [])
    for field in metadata:
        key = field["key"]
        form_key = f"spec_{key}"
        has_form_value = submitted_fields is not None and form_key in submitted_fields
        if has_form_value:
            raw = submitted_fields.get(form_key)
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                specs.pop(key, None)
                continue
        elif key in specs:
            raw = specs[key]
        else:
            continue

        try:
            kind = field.get("kind", "text")
            if kind in {"percent", "ratio"}:
                normalized = normalize_ratio(raw, field_label=field["label"])
            elif kind == "boolean":
                normalized = normalize_boolean(raw)
            elif kind == "integer":
                normalized = normalize_number(raw, field_label=field["label"], integer=True)
            elif kind == "number":
                normalized = normalize_number(raw, field_label=field["label"])
            elif kind == "pump_curve":
                normalized = normalize_pump_curve(raw)
            elif kind == "choice":
                choices = {str(choice).casefold(): str(choice) for choice in field.get("choices", ())}
                normalized = choices.get(str(raw).strip().casefold())
                if normalized is None:
                    raise ValueError(f"{field['label']} contient une valeur non reconnue.")
            else:
                normalized = str(raw).strip()
        except ValueError as exc:
            raise ProductValidationError({form_key: str(exc)}) from exc
        if normalized in (None, "", []):
            specs.pop(key, None)
        else:
            specs[key] = normalized

    try:
        json.dumps(specs, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ProductValidationError({"technical_specs_json": "Les caracteristiques techniques ne sont pas serialisables."}) from exc
    return specs


def validate_product(
    product: Mapping[str, Any],
    *,
    existing: Mapping[str, Any] | None = None,
    submitted_fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    existing = dict(existing or {})
    candidate = dict(product)
    errors: dict[str, str] = {}

    try:
        category = normalize_category(candidate.get("category"))
    except ProductValidationError as exc:
        category = ""
        errors.update(exc.errors)

    reference = str(candidate.get("reference") or "").strip().upper()
    if not reference and category != "pumps":
        errors["reference"] = "La reference est obligatoire."
    elif len(reference) > 100:
        errors["reference"] = "La reference ne peut pas depasser 100 caracteres."

    normalized: dict[str, Any] = {"reference": reference, "category": category}
    for key in ("brand", "model"):
        normalized[key] = str(candidate.get(key) or "").strip()
    if not normalized["brand"] and category != "pumps":
        errors["brand"] = "La marque est obligatoire."
    datasheet_url = str(candidate.get("datasheet_url") or existing.get("datasheet_url") or "").strip()
    normalized["datasheet_url"] = datasheet_url

    for key, label in COMMON_NUMERIC_FIELDS.items():
        try:
            normalized[key] = normalize_number(candidate.get(key), field_label=label)
        except ValueError as exc:
            errors[key] = str(exc)
    normalized["stock"] = 0 if normalized.get("stock") is None else normalized["stock"]

    try:
        if category == "pumps":
            default_vat = existing.get("vat_rate") if "vat_rate" in existing else None
        else:
            default_vat = existing.get("vat_rate") if existing.get("vat_rate") is not None else 0.20
        normalized["vat_rate"] = normalize_ratio(candidate.get("vat_rate"), field_label="TVA", default=default_vat)
    except ValueError as exc:
        errors["vat_rate"] = str(exc)

    currency = str(candidate.get("currency") or existing.get("currency") or "DH").strip().upper()
    if not re.fullmatch(r"[A-Z]{2,5}", currency):
        errors["currency"] = "La devise doit contenir entre 2 et 5 lettres."
    normalized["currency"] = currency

    if datasheet_url:
        parsed_url = urlparse(datasheet_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            errors["datasheet_url"] = "L'URL de fiche technique doit commencer par http:// ou https://."

    for key, default in (("active", True), ("demo", False), ("preferred", False)):
        try:
            normalized[key] = 1 if normalize_boolean(candidate.get(key), default=default) else 0
        except ValueError as exc:
            errors[key] = str(exc)
    try:
        priority = normalize_number(candidate.get("priority"), field_label="Priorite", integer=True)
        normalized["priority"] = 0 if priority is None else priority
    except ValueError as exc:
        errors["priority"] = str(exc)

    raw_specs = candidate.get("technical_specs", existing.get("technical_specs", {}))
    try:
        normalized["technical_specs"] = normalize_technical_specs(
            category,
            raw_specs,
            submitted_fields=submitted_fields,
        ) if category else {}
    except ProductValidationError as exc:
        errors.update(exc.errors)

    specs = normalized.get("technical_specs") or {}
    if category == "panels":
        if normalized.get("power_w") is None and specs.get("power_w") is not None:
            normalized["power_w"] = specs["power_w"]
    elif category == "batteries":
        if normalized.get("capacity_kwh") is None and specs.get("capacity_kwh") is not None:
            normalized["capacity_kwh"] = specs["capacity_kwh"]
        if normalized.get("voltage") is None and specs.get("nominal_voltage_v") is not None:
            normalized["voltage"] = specs["nominal_voltage_v"]
    elif category == "inverters":
        if normalized.get("power_kw") is None and specs.get("power_kw") is not None:
            normalized["power_kw"] = specs["power_kw"]
        if normalized.get("voltage") is None and specs.get("nominal_battery_voltage_v") is not None:
            normalized["voltage"] = specs["nominal_battery_voltage_v"]
    elif category == "pumps":
        pump_power_kw = specs.get("power_kw")
        pump_power_hp = specs.get("power_hp")
        if pump_power_kw is None and pump_power_hp is not None:
            pump_power_kw = round(float(pump_power_hp) * 0.7355, 3)
        if normalized.get("power_kw") is None and pump_power_kw is not None:
            normalized["power_kw"] = pump_power_kw
        if normalized.get("voltage") is None and specs.get("voltage_v") is not None:
            normalized["voltage"] = specs["voltage_v"]
        if normalized.get("current_amp") is None and specs.get("current_a") is not None:
            normalized["current_amp"] = specs["current_a"]
    elif category == "drives":
        if normalized.get("power_kw") is None and specs.get("power_kw") is not None:
            normalized["power_kw"] = specs["power_kw"]
        if normalized.get("voltage") is None and specs.get("output_voltage_v") is not None:
            normalized["voltage"] = specs["output_voltage_v"]
    elif category == "ev_chargers":
        if normalized.get("power_kw") is None and specs.get("power_kw") is not None:
            normalized["power_kw"] = specs["power_kw"]
        if normalized.get("voltage") is None and specs.get("nominal_voltage_v") is not None:
            normalized["voltage"] = specs["nominal_voltage_v"]
        if normalized.get("current_amp") is None and specs.get("max_current_a") is not None:
            normalized["current_amp"] = specs["max_current_a"]
    elif category == "thermal":
        if normalized.get("capacity_l") is None and specs.get("tank_volume_l") is not None:
            normalized["capacity_l"] = specs["tank_volume_l"]

    if errors:
        raise ProductValidationError(errors)
    return normalized


def product_completeness(product: Mapping[str, Any]) -> dict[str, Any]:
    category = CATEGORY_ALIASES.get(_token(product.get("category")), str(product.get("category") or ""))
    specs = product.get("technical_specs") or {}
    checks: list[tuple[str, Any]] = [
        ("Categorie", category),
        ("Prix de vente", product.get("sale_price")),
        ("Unite", product.get("unit")),
    ]
    if category != "pumps":
        checks[:0] = [
            ("Reference", product.get("reference")),
            ("Marque", product.get("brand")),
        ]
        checks.extend([
            ("Modele", product.get("model")),
            ("TVA", product.get("vat_rate")),
            ("Garantie", product.get("warranty")),
        ])
    capability_by_category = {
        "panels": ("Puissance W", product.get("power_w")),
        "batteries": ("Capacite kWh", product.get("capacity_kwh")),
        "inverters": ("Puissance kW", product.get("power_kw")),
        "pumps": ("Puissance CV", specs.get("power_hp")),
        "drives": ("Puissance kW", product.get("power_kw")),
        "ev_chargers": ("Puissance kW", product.get("power_kw")),
        "thermal": ("Capacite ou sous-categorie", product.get("capacity_l") or product.get("subcategory")),
        "cables": ("Section", specs.get("section_mm2")),
    }
    if category in capability_by_category:
        checks.append(capability_by_category[category])
    for field in TECHNICAL_FIELDS.get(category, []):
        if field.get("required"):
            field_value = (
                product.get("pump_curve_points")
                if category == "pumps" and field["key"] == "curve_points"
                else specs.get(field["key"])
            )
            checks.append((field["label"], field_value))

    missing = [label for label, value in checks if value is None or value == "" or value == []]
    score = round(100 * (len(checks) - len(missing)) / max(len(checks), 1))
    status = "complete" if score >= 85 else ("partial" if score >= 55 else "minimal")
    return {
        "score": score,
        "missing": missing,
        "complete": score >= 85,
        "status": status,
        "label": "Complet" if status == "complete" else ("Partiel" if status == "partial" else "Minimal"),
    }
