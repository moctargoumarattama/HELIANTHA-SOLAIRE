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
        "label": "Panneaux photovoltaques",
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
        {"key": "surface_m2", "label": "Surface du module", "kind": "number", "unit": "m2", "required": True},
        {"key": "voc_v", "label": "Tension a vide Voc", "kind": "number", "unit": "V"},
        {"key": "vmp_v", "label": "Tension MPP Vmp", "kind": "number", "unit": "V"},
        {"key": "isc_a", "label": "Courant de court-circuit Isc", "kind": "number", "unit": "A"},
        {"key": "imp_a", "label": "Courant MPP Imp", "kind": "number", "unit": "A"},
        {"key": "efficiency_percent", "label": "Rendement du panneau", "kind": "percent", "unit": "%"},
        {"key": "temperature_coefficient_voc", "label": "Coeff. temperature Voc", "kind": "number", "unit": "%/C"},
        {"key": "temperature_coefficient_pmax", "label": "Coeff. temperature Pmax", "kind": "number", "unit": "%/C"},
        {"key": "length_mm", "label": "Longueur", "kind": "number", "unit": "mm"},
        {"key": "width_mm", "label": "Largeur", "kind": "number", "unit": "mm"},
        {"key": "weight_kg", "label": "Poids", "kind": "number", "unit": "kg"},
        {"key": "technology", "label": "Technologie cellule", "kind": "text", "unit": ""},
        {"key": "max_system_voltage_v", "label": "Tension systeme max", "kind": "number", "unit": "V"},
        {"key": "warranty_years", "label": "Garantie produit", "kind": "integer", "unit": "ans"},
        {"key": "bifacial", "label": "Module bifacial", "kind": "boolean", "unit": ""},
        {"key": "temperature_coefficient", "label": "Coeff. temperature generique", "kind": "number", "unit": "%/C"},
    ],
    "batteries": [
        {"key": "nominal_voltage_v", "label": "Tension nominale", "kind": "number", "unit": "V"},
        {"key": "capacity_ah", "label": "Capacite Ah", "kind": "number", "unit": "Ah"},
        {"key": "usable_energy_kwh", "label": "Energie utile", "kind": "number", "unit": "kWh"},
        {"key": "depth_of_discharge", "label": "Profondeur de decharge utile", "kind": "percent", "unit": "%", "required": True},
        {"key": "dod_percent", "label": "DoD constructeur", "kind": "percent", "unit": "%"},
        {"key": "round_trip_efficiency", "label": "Rendement aller-retour", "kind": "percent", "unit": "%", "required": True},
        {"key": "efficiency_percent", "label": "Rendement batterie", "kind": "percent", "unit": "%"},
        {"key": "max_charge_current_a", "label": "Courant charge max", "kind": "number", "unit": "A"},
        {"key": "max_discharge_current_a", "label": "Courant decharge max", "kind": "number", "unit": "A"},
        {"key": "continuous_power_kw", "label": "Puissance continue", "kind": "number", "unit": "kW"},
        {"key": "peak_power_kw", "label": "Puissance de pointe", "kind": "number", "unit": "kW"},
        {"key": "cycles", "label": "Nombre de cycles", "kind": "integer", "unit": "cycles"},
        {"key": "communication", "label": "Communication", "kind": "text", "unit": ""},
        {"key": "parallel_max", "label": "Maximum parallele", "kind": "integer", "unit": "modules"},
        {"key": "series_max", "label": "Maximum serie", "kind": "integer", "unit": "modules"},
        {"key": "warranty_years", "label": "Garantie", "kind": "integer", "unit": "ans"},
        {"key": "rack_mountable", "label": "Montage en rack", "kind": "boolean", "unit": ""},
    ],
    "inverters": [
        {"key": "type", "label": "Type d'onduleur", "kind": "choice", "choices": ("on_grid", "off_grid", "hybrid", "pump_drive")},
        {"key": "rated_power_kw", "label": "Puissance nominale AC", "kind": "number", "unit": "kW"},
        {"key": "max_ac_power_kw", "label": "Puissance AC max", "kind": "number", "unit": "kW"},
        {"key": "max_dc_power_kw", "label": "Puissance DC max", "kind": "number", "unit": "kW"},
        {"key": "max_dc_voltage_v", "label": "Tension DC maximale", "kind": "number", "unit": "V"},
        {"key": "mppt_min_voltage_v", "label": "Tension MPPT min", "kind": "number", "unit": "V"},
        {"key": "mppt_max_voltage_v", "label": "Tension MPPT max", "kind": "number", "unit": "V"},
        {"key": "startup_voltage_v", "label": "Tension de demarrage", "kind": "number", "unit": "V"},
        {"key": "number_of_mppt", "label": "Nombre de MPPT", "kind": "integer", "unit": "MPPT"},
        {"key": "mppt_count", "label": "Nombre de MPPT (alias)", "kind": "integer", "unit": "MPPT"},
        {"key": "max_input_current_per_mppt_a", "label": "Courant max par MPPT", "kind": "number", "unit": "A"},
        {"key": "max_input_current_a", "label": "Courant entree max", "kind": "number", "unit": "A"},
        {"key": "max_short_circuit_current_a", "label": "Courant court-circuit max", "kind": "number", "unit": "A"},
        {"key": "efficiency_percent", "label": "Rendement onduleur", "kind": "percent", "unit": "%"},
        {"key": "phases", "label": "Phases", "kind": "choice", "choices": ("monophase", "triphase")},
        {"key": "battery_compatible", "label": "Compatible batterie", "kind": "boolean", "unit": ""},
        {"key": "nominal_battery_voltage_v", "label": "Tension batterie nominale", "kind": "number", "unit": "V"},
        {"key": "battery_voltage_min_v", "label": "Tension batterie min", "kind": "number", "unit": "V"},
        {"key": "battery_voltage_max_v", "label": "Tension batterie max", "kind": "number", "unit": "V"},
        {"key": "communication", "label": "Communication", "kind": "text", "unit": ""},
    ],
    "pumps": [
        {"key": "power_hp", "label": "Puissance HP", "kind": "number", "unit": "HP"},
        {"key": "voltage_v", "label": "Tension nominale", "kind": "number", "unit": "V"},
        {"key": "phases", "label": "Phases", "kind": "choice", "choices": ("monophase", "triphase")},
        {"key": "rated_current_a", "label": "Courant nominal", "kind": "number", "unit": "A"},
        {"key": "flow_m3_h", "label": "Debit nominal", "kind": "number", "unit": "m3/h", "required": True},
        {"key": "hmt_m", "label": "HMT nominale", "kind": "number", "unit": "m", "required": True},
        {"key": "min_flow_m3_h", "label": "Debit minimal", "kind": "number", "unit": "m3/h"},
        {"key": "max_flow_m3_h", "label": "Debit maximal", "kind": "number", "unit": "m3/h"},
        {"key": "min_head_m", "label": "HMT minimale", "kind": "number", "unit": "m"},
        {"key": "max_head_m", "label": "HMT maximale", "kind": "number", "unit": "m"},
        {"key": "pump_efficiency", "label": "Rendement pompe", "kind": "percent", "unit": "%"},
        {"key": "efficiency_percent", "label": "Rendement constructeur", "kind": "percent", "unit": "%"},
        {"key": "pump_type", "label": "Type de pompe", "kind": "text", "unit": ""},
        {"key": "connection_size", "label": "Diametre de raccordement", "kind": "text", "unit": ""},
        {"key": "pump_curve", "label": "Courbe pompe (debit/HMT)", "kind": "pump_curve", "unit": "m3/h : m"},
    ],
    "drives": [
        {"key": "drive_efficiency", "label": "Rendement variateur", "kind": "percent", "unit": "%"},
        {"key": "motor_power_kw", "label": "Puissance moteur couverte", "kind": "number", "unit": "kW"},
        {"key": "max_dc_voltage_v", "label": "Tension DC maximale", "kind": "number", "unit": "V"},
        {"key": "input_voltage_min_v", "label": "Tension PV min", "kind": "number", "unit": "V"},
        {"key": "input_voltage_max_v", "label": "Tension PV max", "kind": "number", "unit": "V"},
        {"key": "mppt_voltage_min_v", "label": "Tension MPPT min", "kind": "number", "unit": "V"},
        {"key": "mppt_voltage_max_v", "label": "Tension MPPT max", "kind": "number", "unit": "V"},
        {"key": "output_voltage_v", "label": "Tension de sortie", "kind": "number", "unit": "V"},
        {"key": "phases", "label": "Phases sortie", "kind": "choice", "choices": ("monophase", "triphase")},
        {"key": "max_output_current_a", "label": "Courant sortie max", "kind": "number", "unit": "A"},
    ],
    "ev_chargers": [
        {"key": "phases", "label": "Phases", "kind": "choice", "choices": ("monophase", "triphase"), "required": True},
        {"key": "connector", "label": "Connecteur", "kind": "choice", "choices": ("Type 1", "Type 2", "CCS", "CHAdeMO"), "required": True},
        {"key": "nominal_voltage_v", "label": "Tension nominale", "kind": "number", "unit": "V"},
        {"key": "max_current_a", "label": "Courant maximal", "kind": "number", "unit": "A"},
        {"key": "smart_charging", "label": "Recharge intelligente", "kind": "boolean", "unit": ""},
        {"key": "ocpp", "label": "Compatible OCPP", "kind": "boolean", "unit": ""},
        {"key": "ip_rating", "label": "Indice IP", "kind": "text", "unit": ""},
    ],
    "thermal": [
        {"key": "surface_m2", "label": "Surface du capteur", "kind": "number", "unit": "m2"},
        {"key": "collector_efficiency", "label": "Rendement du capteur", "kind": "percent", "unit": "%"},
        {"key": "tank_volume_l", "label": "Volume ballon", "kind": "number", "unit": "L"},
        {"key": "max_people", "label": "Capacite usagers indicative", "kind": "integer", "unit": "personnes"},
        {"key": "electric_backup", "label": "Appoint electrique", "kind": "boolean", "unit": ""},
    ],
    "protections": [
        {"key": "poles", "label": "Nombre de poles", "kind": "integer", "unit": ""},
        {"key": "breaking_capacity_ka", "label": "Pouvoir de coupure", "kind": "number", "unit": "kA"},
        {"key": "protection_type", "label": "Type de protection", "kind": "text", "unit": ""},
        {"key": "voltage_v", "label": "Tension nominale", "kind": "number", "unit": "V"},
        {"key": "current_a", "label": "Courant nominal", "kind": "number", "unit": "A"},
        {"key": "dc_or_ac", "label": "Famille", "kind": "choice", "choices": ("dc", "ac")},
    ],
    "cables": [
        {"key": "section_mm2", "label": "Section", "kind": "number", "unit": "mm2", "required": True},
        {"key": "conductor", "label": "Conducteur", "kind": "choice", "choices": ("cuivre", "aluminium")},
        {"key": "solar_rated", "label": "Homologue solaire", "kind": "boolean", "unit": ""},
        {"key": "current_a", "label": "Courant admissible", "kind": "number", "unit": "A"},
        {"key": "voltage_v", "label": "Tension nominale", "kind": "number", "unit": "V"},
    ],
    "structures": [
        {"key": "material", "label": "Materiau", "kind": "text", "unit": ""},
        {"key": "panel_capacity", "label": "Nombre de panneaux supportes", "kind": "integer", "unit": "panneaux"},
        {"key": "roof_type", "label": "Type de support", "kind": "text", "unit": ""},
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
        result.append({"flow_m3_h": float(flow_value), "hmt_m": float(hmt_value)})
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

    reference = str(candidate.get("reference") or "").strip().upper()
    if not reference:
        errors["reference"] = "La reference est obligatoire."
    elif len(reference) > 100:
        errors["reference"] = "La reference ne peut pas depasser 100 caracteres."

    try:
        category = normalize_category(candidate.get("category"))
    except ProductValidationError as exc:
        category = ""
        errors.update(exc.errors)

    normalized: dict[str, Any] = {"reference": reference, "category": category}
    for key in (
        "subcategory",
        "brand",
        "model",
        "description",
        "technology",
        "supplier",
        "unit",
        "warranty",
        "datasheet_url",
    ):
        normalized[key] = str(candidate.get(key) or "").strip()
    normalized["unit"] = normalized["unit"] or "piece"

    for key, label in COMMON_NUMERIC_FIELDS.items():
        try:
            normalized[key] = normalize_number(candidate.get(key), field_label=label)
        except ValueError as exc:
            errors[key] = str(exc)
    normalized["stock"] = 0 if normalized.get("stock") is None else normalized["stock"]

    try:
        normalized["efficiency"] = normalize_ratio(candidate.get("efficiency"), field_label="Rendement")
    except ValueError as exc:
        errors["efficiency"] = str(exc)
    try:
        default_vat = existing.get("vat_rate") if existing.get("vat_rate") is not None else 0.20
        normalized["vat_rate"] = normalize_ratio(candidate.get("vat_rate"), field_label="TVA", default=default_vat)
    except ValueError as exc:
        errors["vat_rate"] = str(exc)

    currency = str(candidate.get("currency") or existing.get("currency") or "DH").strip().upper()
    if not re.fullmatch(r"[A-Z]{2,5}", currency):
        errors["currency"] = "La devise doit contenir entre 2 et 5 lettres."
    normalized["currency"] = currency

    datasheet_url = normalized["datasheet_url"]
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

    if errors:
        raise ProductValidationError(errors)
    return normalized


def product_completeness(product: Mapping[str, Any]) -> dict[str, Any]:
    category = CATEGORY_ALIASES.get(_token(product.get("category")), str(product.get("category") or ""))
    specs = product.get("technical_specs") or {}
    checks: list[tuple[str, Any]] = [
        ("Reference", product.get("reference")),
        ("Categorie", category),
        ("Marque", product.get("brand")),
        ("Modele", product.get("model")),
        ("Prix de vente", product.get("sale_price")),
        ("Unite", product.get("unit")),
        ("TVA", product.get("vat_rate")),
        ("Garantie", product.get("warranty")),
    ]
    capability_by_category = {
        "panels": ("Puissance W", product.get("power_w")),
        "batteries": ("Capacite kWh", product.get("capacity_kwh")),
        "inverters": ("Puissance kW", product.get("power_kw")),
        "pumps": ("Puissance kW", product.get("power_kw")),
        "drives": ("Puissance kW", product.get("power_kw")),
        "ev_chargers": ("Puissance kW", product.get("power_kw")),
        "thermal": ("Capacite ou sous-categorie", product.get("capacity_l") or product.get("subcategory")),
        "cables": ("Section", specs.get("section_mm2")),
    }
    if category in capability_by_category:
        checks.append(capability_by_category[category])
    for field in TECHNICAL_FIELDS.get(category, []):
        if field.get("required"):
            checks.append((field["label"], specs.get(field["key"])))

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
