"""Deterministic 220 V monophase hybrid sizing with lithium storage."""

from __future__ import annotations

from app.transport import TRANSPORT_DESCRIPTION

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any

from app.tax import vat_rate_for_component
from app.services.ongrid_service import (
    _as_float,
    _catalog_line,
    _decimal,
    _product_power,
    _service_line,
    parameters_from_context,
    select_structure,
)


HYBRID_TIERS = [
    {
        "tier": 1,
        "min_kwh": Decimal("0"),
        "max_kwh": Decimal("700"),
        "panel_count": 8,
        "panel_power_options": (585,),
        "inverter_power_kw": Decimal("6"),
        "battery_unit_capacity_kwh": Decimal("5"),
        "battery_count": 2,
    },
    {
        "tier": 2,
        "min_kwh": Decimal("700"),
        "max_kwh": Decimal("1400"),
        "panel_count": 16,
        "panel_power_options": (585,),
        "inverter_power_kw": Decimal("10"),
        "battery_unit_capacity_kwh": Decimal("15"),
        "battery_count": 1,
    },
    {
        "tier": 3,
        "min_kwh": Decimal("1400"),
        "max_kwh": None,
        "panel_count": 24,
        "panel_power_options": (725, 720),
        "inverter_power_kw": Decimal("18"),
        "battery_unit_capacity_kwh": Decimal("15"),
        "battery_count": 2,
    },
]


def _tier_for_monthly(monthly: Decimal) -> dict[str, Any]:
    for tier in HYBRID_TIERS:
        max_kwh = tier["max_kwh"]
        if max_kwh is None and monthly > tier["min_kwh"]:
            return tier
        if max_kwh is not None and tier["min_kwh"] < monthly <= max_kwh:
            return tier
        if monthly == 0 and tier["tier"] == 1:
            return tier
    return HYBRID_TIERS[-1]


def _product_capacity(product: dict[str, Any]) -> Decimal:
    specs = product.get("technical_specs") or {}
    return _decimal(product.get("capacity_kwh") or specs.get("capacity_kwh") or 0)


def select_panel(products: list[dict[str, Any]], power_options: tuple[int, ...]) -> tuple[dict[str, Any], int]:
    for power_w in power_options:
        candidates = [
            deepcopy(product)
            for product in products
            if product.get("category") == "panels"
            and int(product.get("active", 1) or 0) == 1
            and int(float(product.get("power_w") or (product.get("technical_specs") or {}).get("power_w") or 0)) == int(power_w)
        ]
        if candidates:
            candidates.sort(key=lambda item: (
                0 if item.get("preferred") else 1,
                -int(item.get("priority") or 0),
                _decimal(item.get("sale_price"), Decimal("999999999")),
                str(item.get("reference") or ""),
            ))
            return candidates[0], power_w
    raise ValueError(f"Aucun panneau actif {', '.join(str(power) for power in power_options)} W n'est disponible au catalogue.")


def select_hybrid_inverter(products: list[dict[str, Any]], requested_kw: Decimal) -> dict[str, Any]:
    candidates = []
    for product in products:
        specs = product.get("technical_specs") or {}
        if product.get("category") != "inverters" or int(product.get("active", 1) or 0) != 1:
            continue
        if "deye" not in str(product.get("brand") or "").strip().lower():
            continue
        if str(specs.get("type") or product.get("subcategory") or "").strip().lower() != "hybrid":
            continue
        if str(specs.get("phases") or specs.get("phase") or product.get("subcategory") or "").strip().lower() != "monophase":
            continue
        if _product_power(product) >= requested_kw:
            candidates.append(deepcopy(product))
    if not candidates:
        raise ValueError(f"Aucun onduleur hybride Deye monophasé actif ne couvre {requested_kw:.2f} kW.")
    candidates.sort(key=lambda item: (
        _product_power(item),
        _decimal(item.get("sale_price"), Decimal("999999999")),
        str(item.get("reference") or ""),
    ))
    return candidates[0]


def select_battery(products: list[dict[str, Any]], capacity_kwh: Decimal) -> dict[str, Any]:
    candidates = [
        deepcopy(product)
        for product in products
        if product.get("category") == "batteries"
        and int(product.get("active", 1) or 0) == 1
        and abs(_product_capacity(product) - capacity_kwh) <= Decimal("0.05")
    ]
    if not candidates:
        raise ValueError(f"Aucune batterie lithium active {capacity_kwh:g} kWh n'est disponible au catalogue.")
    candidates.sort(key=lambda item: (
        0 if item.get("preferred") else 1,
        -int(item.get("priority") or 0),
        _decimal(item.get("sale_price"), Decimal("999999999")),
        str(item.get("reference") or ""),
    ))
    return candidates[0]


def calculate_hybrid(data: dict[str, Any], context: dict[str, Any] | None) -> dict[str, Any]:
    params = parameters_from_context(context)
    products = list((context or {}).get("products") or [])
    monthly = _decimal(data.get("monthly_consumption_kwh") or data.get("monthly_kwh") or data.get("consumption_kwh"))
    if monthly <= 0:
        raise ValueError("La consommation mensuelle doit être supérieure à zéro.")

    tier = _tier_for_monthly(monthly)
    panel, panel_power_w = select_panel(products, tier["panel_power_options"])
    inverter = select_hybrid_inverter(products, tier["inverter_power_kw"])
    battery = select_battery(products, tier["battery_unit_capacity_kwh"])
    structure = select_structure(products)

    panel_count = Decimal(tier["panel_count"])
    battery_count = Decimal(tier["battery_count"])
    dc_kw = (panel_count * Decimal(panel_power_w)) / Decimal("1000")
    battery_total = battery_count * tier["battery_unit_capacity_kwh"]

    lines = [
        _catalog_line("panel", panel, panel_count, "Panneaux photovoltaïques", vat_rate_for_component(context, "hybrid", "panel"), "principal_equipment"),
        _catalog_line("inverter", inverter, Decimal("1"), "Onduleur hybride Deye", vat_rate_for_component(context, "hybrid", "inverter"), "principal_equipment"),
        _catalog_line("battery", battery, battery_count, "Stockage Lithium", vat_rate_for_component(context, "hybrid", "battery"), "principal_equipment"),
        _catalog_line("structure", structure, panel_count, "Structure photovoltaïque", vat_rate_for_component(context, "hybrid", "structure"), "structure"),
        _service_line("protection_acdc", "protections", "Protection AC/DC", panel_count, params["protection_acdc_per_pv"], vat_rate_for_component(context, "hybrid", "protection_acdc"), "protections"),
        _service_line("cabling_acdc", "cables", "Câblage AC/DC", panel_count, params["cablage_acdc_per_pv"], vat_rate_for_component(context, "hybrid", "cabling_acdc"), "cabling"),
        _service_line("installation", "services", "Installation et mise en service", panel_count, params["installation_per_pv"], vat_rate_for_component(context, "hybrid", "installation"), "installation"),
        _service_line("transport", "transport", TRANSPORT_DESCRIPTION, panel_count, params["transport_per_pv"], vat_rate_for_component(context, "hybrid", "transport"), "transport"),
    ]

    return {
        "inputs": {
            "monthly_consumption_kwh": float(monthly),
            "phase": "monophase",
            "voltage_v": 220,
        },
        "parameters": {key: float(value) for key, value in params.items()},
        "final_results": {
            "monthly_consumption_kwh": float(monthly),
            "phase": "monophase",
            "voltage_v": 220,
            "hybrid_tier": tier["tier"],
            "panel_power_w": panel_power_w,
            "panel_count": int(panel_count),
            "installed_power_kwp": float(dc_kw.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)),
            "inverter_power_kw": float(_product_power(inverter)),
            "inverter_brand": inverter.get("brand") or "",
            "inverter_reference": inverter.get("reference") or "",
            "battery_count": int(battery_count),
            "battery_unit_capacity_kwh": float(tier["battery_unit_capacity_kwh"]),
            "battery_total_capacity_kwh": float(battery_total),
            "battery_reference": battery.get("reference") or "",
            "battery_label": f"{int(battery_count)}x Batterie Lithium {tier['battery_unit_capacity_kwh']:g} kWh - Total {battery_total:g} kWh",
            "panel_reference": panel.get("reference") or "",
            "structure_unit_price": _as_float(_decimal(structure.get("sale_price"))),
        },
        "selected_equipment": lines,
    }
