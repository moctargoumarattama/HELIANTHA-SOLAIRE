"""Deterministic On-Grid sizing and costing rules."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_EVEN
from math import ceil
from typing import Any

from app.defaults import ONGRID_PARAMETER_DEFAULTS
from app.tax import money, vat_rate_for_component


MONEY = Decimal("0.01")


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value).strip().replace(",", "."))
    except Exception:
        return default


def _money(value: Decimal) -> Decimal:
    return money(value)


def _as_float(value: Decimal) -> float:
    return float(_money(value))


def default_parameters() -> dict[str, Decimal]:
    return {
        key: _decimal(value)
        for key, _label, value, _unit, _description in ONGRID_PARAMETER_DEFAULTS
    }


def parameters_from_context(context: dict[str, Any] | None) -> dict[str, Decimal]:
    params = default_parameters()
    rows = (context or {}).get("ongrid_parameters") or {}
    for key, row in rows.items():
        if key in params:
            params[key] = _decimal(row.get("value"), params[key])
    for key, component in {
        "vat_pv_rate": "panel",
        "vat_standard_rate": "inverter",
        "vat_accessories_rate": "structure",
        "vat_transport_rate": "transport",
        "vat_installation_rate": "installation",
    }.items():
        params[key] = vat_rate_for_component(context, "photovoltaic", component) * Decimal("100")
    return params


def _phase(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"mono", "monophase", "monophasé", "monophasee"}:
        return "monophase"
    if normalized in {"tri", "triphase", "triphasé", "triphasee"}:
        return "triphase"
    raise ValueError("Le type de réseau doit être monophase ou triphase.")


def _meter_type(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"numerique", "numérique", "digital"}:
        return "numerique"
    if normalized in {"mecanique", "mécanique", "analogique", "analogue", "disque"}:
        return "mecanique"
    return "numerique"


def _required_inverter_brand(meter_type: str) -> str:
    return "SolaX" if meter_type == "mecanique" else "Deye"


def choose_panel_power(phase: str, target_kw: Decimal) -> int:
    if phase == "monophase":
        if target_kw <= Decimal("3.5"):
            return 400
        if target_kw <= Decimal("8.0"):
            return 590
        return 630
    if target_kw <= Decimal("6.0"):
        return 400
    if target_kw <= Decimal("17.5"):
        return 590
    if target_kw <= Decimal("40.0"):
        return 630
    return 715


def balance_strings(raw_panels: Decimal, phase: str) -> dict[str, Any]:
    min_per, max_per = (6, 8) if phase == "monophase" else (10, 15)
    raw = float(raw_panels)
    strings = max(1, ceil(raw / max_per))
    per_string = max(min_per, ceil((raw / strings) + (0.5 if phase == "monophase" and strings > 1 else 0)))
    if per_string > max_per:
        strings = ceil(raw / max_per)
        while True:
            per_string = max(min_per, ceil((raw / strings) + (0.5 if phase == "monophase" and strings > 1 else 0)))
            if per_string <= max_per:
                break
            strings += 1
    total = strings * per_string
    return {
        "string_count": strings,
        "panels_per_string": per_string,
        "panel_count": total,
        "string_layout": [per_string for _ in range(strings)],
    }


def _product_power(product: dict[str, Any]) -> Decimal:
    specs = product.get("technical_specs") or {}
    return _decimal(product.get("power_kw") or specs.get("power_kw") or 0)


def _product_phase(product: dict[str, Any]) -> str:
    specs = product.get("technical_specs") or {}
    return str(product.get("subcategory") or specs.get("phases") or specs.get("phase") or "").strip().lower()


def select_panel(products: list[dict[str, Any]], power_w: int) -> dict[str, Any]:
    candidates = [
        deepcopy(product)
        for product in products
        if product.get("category") == "panels"
        and int(product.get("active", 1) or 0) == 1
        and int(float(product.get("power_w") or (product.get("technical_specs") or {}).get("power_w") or 0)) == int(power_w)
    ]
    if not candidates:
        raise ValueError(f"Aucun panneau actif {power_w} W n'est disponible au catalogue.")
    candidates.sort(key=lambda item: (
        0 if item.get("preferred") else 1,
        -int(item.get("priority") or 0),
        _decimal(item.get("sale_price"), Decimal("999999999")),
        str(item.get("reference") or ""),
    ))
    return candidates[0]


def select_inverter(products: list[dict[str, Any]], phase: str, dc_kw: Decimal, meter_type: str = "numerique") -> dict[str, Any]:
    required_brand = _required_inverter_brand(meter_type)
    base_candidates = [
        deepcopy(product)
        for product in products
        if product.get("category") == "inverters"
        and int(product.get("active", 1) or 0) == 1
        and _product_phase(product) == phase
        and _product_power(product) >= dc_kw
    ]
    candidates = [
        product
        for product in base_candidates
        if required_brand.lower() in str(product.get("brand") or "").strip().lower()
    ]
    fallback_used = False
    if not candidates:
        candidates = base_candidates
        fallback_used = True
    if not candidates:
        raise ValueError(f"Aucun onduleur actif {phase} ne couvre {dc_kw:.2f} kW.")
    candidates.sort(key=lambda item: (
        _product_power(item),
        _decimal(item.get("sale_price"), Decimal("999999999")),
        str(item.get("reference") or ""),
    ))
    selected = candidates[0]
    selected["_required_brand"] = required_brand
    selected["_brand_fallback_used"] = fallback_used
    return selected


def select_structure(products: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [
        deepcopy(product)
        for product in products
        if product.get("category") == "structures"
        and int(product.get("active", 1) or 0) == 1
        and str(product.get("subcategory") or "").strip().lower() in {"ongrid", "photovoltaic", "pv"}
    ]
    if not candidates:
        raise ValueError("Aucune structure On-Grid active n'est disponible au catalogue.")
    candidates.sort(key=lambda item: (
        0 if item.get("preferred") else 1,
        _decimal(item.get("sale_price"), Decimal("999999999")),
        str(item.get("reference") or ""),
    ))
    return candidates[0]


def _catalog_line(
    component: str,
    product: dict[str, Any],
    quantity: Decimal,
    role: str,
    vat_rate: Decimal,
    financial_category: str,
) -> dict[str, Any]:
    unit_price = _money(_decimal(product.get("sale_price")))
    total = _money(quantity * unit_price)
    technical_specs = deepcopy(product.get("technical_specs") or {})
    return {
        "category": product.get("category") or "",
        "financial_category": financial_category,
        "component": component,
        "product_id": product.get("id"),
        "reference": product.get("reference") or "",
        "brand": product.get("brand") or "",
        "model": product.get("model") or "",
        "description": product.get("description") or role,
        "role": role,
        "quantity": int(quantity) if quantity == quantity.to_integral() else float(quantity),
        "unit": product.get("unit") or "piece",
        "unit_price": _as_float(unit_price),
        "total_price": _as_float(total),
        "price_status": "catalog_price",
        "currency": product.get("currency") or "DH",
        "vat_rate": float(vat_rate),
        "technical_reason": "Produit catalogue On-Grid retenu.",
        "selection_reasons": ["Dimensionnement On-Grid HeliAntha."],
        "compatibility_status": "compatible",
        "compatibility": {"status": "compatible", "checks": []},
        "source_type": "catalog",
        "demo": bool(product.get("demo")),
        "technical_specs": technical_specs,
        "power_w": product.get("power_w") or technical_specs.get("power_w"),
        "power_kw": product.get("power_kw") or technical_specs.get("power_kw"),
        "capacity_kwh": product.get("capacity_kwh") or technical_specs.get("capacity_kwh"),
        "product_snapshot": product,
    }


def _service_line(
    component: str,
    category: str,
    description: str,
    quantity: Decimal,
    unit_price: Decimal,
    vat_rate: Decimal,
    financial_category: str,
) -> dict[str, Any]:
    unit_price = _money(unit_price)
    total = _money(quantity * unit_price)
    return {
        "category": category,
        "financial_category": financial_category,
        "component": component,
        "product_id": None,
        "reference": "",
        "brand": "HeliAntha",
        "model": "",
        "description": description,
        "role": description,
        "quantity": int(quantity) if quantity == quantity.to_integral() else float(quantity),
        "unit": "forfait" if quantity == 1 else "piece",
        "unit_price": _as_float(unit_price),
        "total_price": _as_float(total),
        "price_status": "rule_price",
        "currency": "DH",
        "vat_rate": float(vat_rate),
        "technical_reason": "Forfait On-Grid administrable.",
        "selection_reasons": ["Règle On-Grid HeliAntha."],
        "compatibility_status": "compatible",
        "compatibility": {"status": "compatible", "checks": []},
        "source_type": "heliantha",
        "demo": False,
        "technical_specs": {},
        "product_snapshot": None,
    }


def calculate_ongrid(data: dict[str, Any], context: dict[str, Any] | None) -> dict[str, Any]:
    params = parameters_from_context(context)
    products = list((context or {}).get("products") or [])
    meter_type = _meter_type(data.get("meter_type"))
    phase = _phase(data.get("phase"))
    monthly = _decimal(data.get("monthly_consumption_kwh") or data.get("monthly_kwh"))
    if monthly <= 0:
        raise ValueError("La consommation mensuelle doit être supérieure à zéro.")
    psh = params["psh_hours"]
    if psh <= 0:
        raise ValueError("Le PSH On-Grid doit être supérieur à zéro.")

    daily = monthly / Decimal("30")
    target_kw = daily / psh
    panel_power_w = choose_panel_power(phase, target_kw)
    raw_panels = (monthly * Decimal("1000")) / (Decimal("30") * Decimal(panel_power_w) * psh)
    strings = balance_strings(raw_panels, phase)
    panel_count = Decimal(strings["panel_count"])
    dc_kw = (panel_count * Decimal(panel_power_w)) / Decimal("1000")

    panel = select_panel(products, panel_power_w)
    inverter = select_inverter(products, phase, dc_kw, meter_type)
    structure = select_structure(products)
    inverter_brand = str(inverter.get("brand") or "").strip()

    injection_limit = (
        params["injection_limit_mono"]
        if phase == "monophase"
        else (
            params["injection_limit_tri_low"]
            if dc_kw <= params["injection_limit_tri_threshold"]
            else params["injection_limit_tri_high"]
        )
    )

    lines = [
        _catalog_line("panel", panel, panel_count, "Panneaux photovoltaïques", vat_rate_for_component(context, "photovoltaic", "panel"), "principal_equipment"),
        _catalog_line("inverter", inverter, Decimal("1"), f"Onduleur réseau {inverter_brand or 'On-Grid'}", vat_rate_for_component(context, "photovoltaic", "inverter"), "principal_equipment"),
        _catalog_line("structure", structure, panel_count, "Structure photovoltaïque", vat_rate_for_component(context, "photovoltaic", "structure"), "structure"),
        _service_line("protection_acdc", "protections", "Protection AC/DC", panel_count, params["protection_acdc_per_pv"], vat_rate_for_component(context, "photovoltaic", "protection_acdc"), "protections"),
        _service_line("cabling_acdc", "cables", "Câblage AC/DC", panel_count, params["cablage_acdc_per_pv"], vat_rate_for_component(context, "photovoltaic", "cabling_acdc"), "cabling"),
        _service_line("injection_limiter", "accessories", "Limiteur d'injection", Decimal("1"), injection_limit, vat_rate_for_component(context, "photovoltaic", "injection_limiter"), "accessories"),
        _service_line("installation", "services", "Installation et mise en service", panel_count, params["installation_per_pv"], vat_rate_for_component(context, "photovoltaic", "installation"), "installation"),
        _service_line("transport", "transport", "Transport", panel_count, params["transport_per_pv"], vat_rate_for_component(context, "photovoltaic", "transport"), "transport"),
    ]

    return {
        "inputs": {
            "meter_type": meter_type,
            "phase": phase,
            "monthly_consumption_kwh": float(monthly),
        },
        "parameters": {key: float(value) for key, value in params.items()},
        "final_results": {
            "meter_type": meter_type,
            "phase": phase,
            "monthly_consumption_kwh": float(monthly),
            "daily_consumption_kwh": float(daily.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)),
            "psh_hours": float(psh),
            "target_kwp": float(target_kw.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)),
            "panel_power_w": panel_power_w,
            "raw_panel_count": float(raw_panels.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)),
            "panel_count": int(panel_count),
            "string_count": strings["string_count"],
            "panels_per_string": strings["panels_per_string"],
            "string_layout": strings["string_layout"],
            "installed_power_kwp": float(dc_kw.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)),
            "inverter_power_kw": float(_product_power(inverter)),
            "inverter_reference": inverter.get("reference") or "",
            "inverter_brand": inverter_brand,
            "inverter_required_brand": inverter.get("_required_brand") or _required_inverter_brand(meter_type),
            "inverter_brand_fallback_used": bool(inverter.get("_brand_fallback_used")),
            "panel_reference": panel.get("reference") or "",
            "injection_limiter_ht": _as_float(injection_limit),
        },
        "selected_equipment": lines,
    }
