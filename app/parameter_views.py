from __future__ import annotations

from collections import OrderedDict
from typing import Any

from .defaults import CATEGORY_PRESENTATION, PARAMETER_CLASSIFICATION, PARAMETER_ENGINE_USAGE, SOURCE_TYPES


SOURCE_OPTIONS = [
    ("heliantha", "✅ HeliAntha"),
    ("manufacturer", "🏭 Fabricant"),
    ("reference", "📚 Référentiel technique"),
    ("physical_constant", "🔬 Constante physique"),
    ("local_data", "📍 Donnée locale"),
]


def format_number(value: float, decimals: int = 2) -> str:
    if decimals == 0:
        return f"{value:.0f}".replace(".", ",")
    text = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def format_internal(value: float) -> str:
    return format_number(float(value), 4)


def format_display_value(param: dict[str, Any]) -> str:
    value = float(param.get("value") or 0)
    kind = param.get("display_kind") or param.get("unit") or ""
    if kind == "percent":
        return f"{format_number(value * 100, 1)} %"
    if kind == "multiplier_margin":
        return f"+{format_number((value - 1) * 100, 1)} %"
    if kind == "duration_days":
        suffix = "jour" if abs(value) <= 1 else "jours"
        return f"{format_number(value, 1)} {suffix}"
    if kind == "psh":
        return f"{format_number(value, 1)} h solaires équivalentes / jour"
    if kind == "power_w":
        return f"{format_number(value, 0)} W"
    if kind == "gravity":
        return f"{format_number(value, 2)} m/s²"
    if kind == "density":
        return f"{format_number(value, 0)} kg/m³"
    if kind == "temperature":
        return f"{format_number(value, 1)} °C"
    if kind == "liters_per_day":
        return f"{format_number(value, 0)} L/jour"
    if kind == "liters":
        return f"{format_number(value, 0)} L"
    return f"{format_number(value, 2)} {param.get('unit') or ''}".strip()


def display_input_value(param: dict[str, Any]) -> str:
    value = float(param.get("value") or 0)
    kind = param.get("display_kind") or param.get("unit") or ""
    if kind == "percent":
        return format_number(value * 100, 3)
    if kind == "multiplier_margin":
        return format_number((value - 1) * 100, 3)
    return format_number(value, 4)


def display_input_suffix(param: dict[str, Any]) -> str:
    kind = param.get("display_kind") or param.get("unit") or ""
    return {
        "percent": "%",
        "multiplier_margin": "% de marge",
        "duration_days": "jour(s)",
        "psh": "h/jour",
        "power_w": "W",
        "gravity": "m/s²",
        "density": "kg/m³",
        "temperature": "°C",
        "liters_per_day": "L/jour",
        "liters": "L",
    }.get(kind, param.get("unit") or "")


def parse_display_value(display_kind: str, raw_value: str) -> float:
    normalized = str(raw_value).strip().replace("%", "").replace(",", ".")
    value = float(normalized)
    if display_kind == "percent":
        return value / 100 if abs(value) > 1 else value
    if display_kind == "multiplier_margin":
        if abs(value) > 5:
            return 1 + value / 100
        if -1 < value < 1:
            return 1 + value
        return value
    return value


def enrich_parameter(param: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(param)
    classification = PARAMETER_CLASSIFICATION.get(enriched.get("key") or "", {})
    usage = engine_usage(enriched.get("key") or "")
    source_type = enriched.get("source_type") or "heliantha"
    if source_type == "demo":
        source_type = "heliantha"
    source = SOURCE_TYPES.get(source_type, SOURCE_TYPES["heliantha"])
    category = CATEGORY_PRESENTATION.get(enriched.get("category") or "", {})
    enriched["source_type"] = source_type
    enriched["display_name"] = enriched.get("display_name") or enriched.get("name") or enriched.get("key")
    enriched["display_value"] = format_display_value(enriched)
    enriched["display_internal_value"] = format_internal(float(enriched.get("value") or 0))
    enriched["display_input_value"] = display_input_value(enriched)
    enriched["display_input_suffix"] = display_input_suffix(enriched)
    enriched["source_badge"] = source["badge"]
    enriched["source_label"] = source["label"]
    enriched["source_description"] = source["description"]
    enriched["category_label"] = category.get("label", enriched.get("category") or "Autres")
    enriched["category_icon"] = category.get("icon", "")
    enriched["category_order"] = category.get("order", 999)
    enriched["editable"] = bool(enriched.get("editable"))
    enriched["active"] = bool(enriched.get("active"))
    enriched["admin_visible"] = bool(enriched.get("admin_visible", classification.get("admin_visible", True)))
    enriched["management_scope"] = enriched.get("management_scope") or classification.get("management_scope", "business_rule")
    enriched["role_label"] = enriched.get("role_label") or classification.get("role_label", "Regle HeliAntha")
    enriched["role_description"] = enriched.get("role_description") or classification.get("role_description", "")
    enriched["engine_usage_status"] = usage["status"]
    enriched["engine_usage_badge"] = usage["badge"]
    enriched["engine_usage_note"] = usage["note"]
    enriched["technical_term"] = technical_term(enriched.get("key", ""))
    enriched["search_text"] = " ".join(
        str(enriched.get(field) or "")
        for field in (
            "key",
            "name",
            "display_name",
            "category",
            "category_label",
            "plain_explanation",
            "used_for",
            "calculator_usage",
            "engine_usage_note",
        )
    ).lower()
    return enriched


def group_parameters(parameters: list[dict[str, Any]]) -> OrderedDict[str, dict[str, Any]]:
    groups: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for param in sorted(parameters, key=lambda item: (item["category_order"], item["display_name"])):
        key = param["category_label"]
        if key not in groups:
            groups[key] = {"label": key, "icon": param["category_icon"], "parameters": []}
        groups[key]["parameters"].append(param)
    return groups


def filter_and_group_parameters(
    raw_parameters: list[dict[str, Any]],
    search: str = "",
    category: str = "",
) -> OrderedDict[str, dict[str, Any]]:
    terms = search.strip().lower()
    enriched = [enrich_parameter(param) for param in raw_parameters]
    enriched = [param for param in enriched if param["admin_visible"]]
    if category:
        enriched = [param for param in enriched if param.get("category") == category]
    if terms:
        enriched = [param for param in enriched if terms in param["search_text"]]
    return group_parameters(enriched)


def technical_term(key: str) -> str:
    return {
        "battery_dod": "Depth of Discharge (DoD)",
        "pv_performance_ratio": "Performance Ratio (PR)",
        "productible_default_psh": "Peak Sun Hours (PSH)",
        "inverter_peak_factor": "Peak factor",
        "pump_hydraulic_losses_rate": "Hydraulic losses rate",
    }.get(key, "")


def engine_usage(key: str) -> dict[str, str]:
    default = {
        "status": "used",
        "badge": "✅ Utilise par le moteur",
        "note": "Ce parametre influence actuellement au moins un calcul actif ou sert de valeur de secours au moteur.",
    }
    return {**default, **PARAMETER_ENGINE_USAGE.get(key, {})}
