"""Hydraulic pump selection from HeliAntha's measured catalogue points.

This module is the only business policy used when a client does not already
own a pump.  It deliberately does not read product references, inventory, or
stock availability.
"""

from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any, Iterable


NO_STANDARD_PUMP_MESSAGE = (
    "Aucune pompe standard ne couvre ce besoin. "
    "Une configuration HeliAntha personnalisée est nécessaire."
)

FLOW_EPSILON = 1e-9


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def curve_head_for_flow(
    curve_points: Iterable[dict[str, Any]],
    requested_flow_m3_h: float,
) -> dict[str, Any] | None:
    """Return the conservative catalogue head for one requested flow.

    Exact catalogue flows use their exact HMT.  A flow strictly between two
    catalogue points is assigned to that interval and uses the lower HMT of
    the two bounds.  This is intentionally conservative and performs no
    mathematical interpolation.  Requests outside the recorded curve are not
    covered.
    """

    requested = _finite_number(requested_flow_m3_h)
    if requested is None or requested < 0:
        return None

    normalized: list[dict[str, float]] = []
    for point in curve_points or []:
        flow = _finite_number(point.get("flow_m3_h"))
        head = _finite_number(point.get("hmt_m"))
        if flow is None or head is None or flow < 0 or head < 0:
            continue
        normalized.append({"flow_m3_h": flow, "hmt_m": head})
    normalized.sort(key=lambda point: point["flow_m3_h"])

    for point in normalized:
        if abs(point["flow_m3_h"] - requested) <= FLOW_EPSILON:
            return {
                "requested_flow_m3_h": requested,
                "available_hmt_m": point["hmt_m"],
                "interval_start_m3_h": point["flow_m3_h"],
                "interval_end_m3_h": point["flow_m3_h"],
                "policy": "exact_catalogue_point",
            }

    for lower, upper in zip(normalized, normalized[1:]):
        if lower["flow_m3_h"] < requested < upper["flow_m3_h"]:
            return {
                "requested_flow_m3_h": requested,
                "available_hmt_m": min(lower["hmt_m"], upper["hmt_m"]),
                "interval_start_m3_h": lower["flow_m3_h"],
                "interval_end_m3_h": upper["flow_m3_h"],
                "policy": "conservative_interval_no_interpolation",
            }
    return None


def _pump_power_hp(product: dict[str, Any]) -> float | None:
    specs = product.get("technical_specs") or {}
    value = specs.get("power_hp")
    if value in (None, ""):
        value = product.get("power_hp")
    hp = _finite_number(value)
    return hp if hp is not None and hp > 0 else None


def _pump_curve(product: dict[str, Any]) -> list[dict[str, Any]]:
    points = product.get("pump_curve_points")
    if isinstance(points, list):
        return points
    specs = product.get("technical_specs") or {}
    for key in ("curve_points", "pump_curve"):
        if isinstance(specs.get(key), list):
            return specs[key]
    return []


def select_pump_for_duty(
    products: Iterable[dict[str, Any]],
    requested_flow_m3_h: float,
    requested_hmt_m: float,
) -> dict[str, Any] | None:
    """Select the smallest sufficient CV, then the lowest current DB price."""

    requested_flow = _finite_number(requested_flow_m3_h)
    requested_hmt = _finite_number(requested_hmt_m)
    if requested_flow is None or requested_flow <= 0:
        raise ValueError("Le débit demandé doit être supérieur à 0 m³/h.")
    if requested_hmt is None or requested_hmt <= 0:
        raise ValueError("La HMT demandée doit être supérieure à 0 m.")

    candidates: list[dict[str, Any]] = []
    for product in products or []:
        if product.get("category") != "pumps":
            continue
        if int(product.get("active", 1) or 0) != 1:
            continue
        power_hp = _pump_power_hp(product)
        if power_hp is None:
            continue
        duty = curve_head_for_flow(_pump_curve(product), requested_flow)
        if not duty or duty["available_hmt_m"] + FLOW_EPSILON < requested_hmt:
            continue
        price = _finite_number(product.get("sale_price"))
        technical_id = product.get("id")
        try:
            technical_id = int(technical_id)
        except (TypeError, ValueError):
            technical_id = 2**63 - 1
        candidates.append({
            "product": deepcopy(product),
            "selected_pump_cv": power_hp,
            "current_price": price,
            "duty": duty,
            "technical_id": technical_id,
        })

    if not candidates:
        return None

    candidates.sort(key=lambda candidate: (
        candidate["selected_pump_cv"],
        candidate["current_price"] is None,
        candidate["current_price"] if candidate["current_price"] is not None else float("inf"),
        candidate["technical_id"],
    ))
    selected = candidates[0]
    selected["sufficient_candidate_count"] = len(candidates)
    selected["same_cv_candidate_count"] = sum(
        1
        for candidate in candidates
        if abs(candidate["selected_pump_cv"] - selected["selected_pump_cv"]) <= FLOW_EPSILON
    )
    return selected


__all__ = [
    "NO_STANDARD_PUMP_MESSAGE",
    "curve_head_for_flow",
    "select_pump_for_duty",
]
