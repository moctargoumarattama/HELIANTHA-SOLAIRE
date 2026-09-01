"""Deterministic catalogue selection helpers for HeliAntha Smart Quote."""

from __future__ import annotations

from copy import deepcopy
from math import ceil
from typing import Any

from app.catalog import normalize_category, product_completeness

from .compatibility import (
    CompatibilityChecker,
    as_float,
    as_ratio,
    check,
    compatibility_result,
    normalize_text,
    spec_value,
    warning,
)


STATUS_ORDER = {
    "compatible": 0,
    "compatible_with_warning": 1,
    "manual_validation_required": 2,
    "incompatible": 3,
}


def _price_value(product: dict[str, Any]) -> float:
    value = as_float(product.get("sale_price"))
    return value if value is not None else 10**9


class ProductSelector:
    """Choose the best catalogue product for a calculated target."""

    version = "1.0"

    def __init__(
        self,
        products: list[dict[str, Any]] | None,
        compatibility: CompatibilityChecker | None = None,
    ):
        self.all_products = [deepcopy(item) for item in (products or [])]
        self.products = [item for item in self.all_products if int(item.get("active", 1) or 0) == 1]
        self.compatibility = compatibility or CompatibilityChecker()

    def category_products(self, category: str, subcategory_tokens: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        canonical = normalize_category(category)
        candidates = [deepcopy(item) for item in self.products if item.get("category") == canonical]
        if not subcategory_tokens:
            return candidates
        normalized_tokens = tuple(normalize_text(token) for token in subcategory_tokens if token)
        filtered = []
        for item in candidates:
            haystack = " ".join(
                normalize_text(item.get(field))
                for field in ("subcategory", "description", "model", "technology")
            )
            if any(token and token in haystack for token in normalized_tokens):
                filtered.append(item)
        return filtered or candidates

    def select_panel(self, target_kwp: float, roof_area_m2: float | None = None) -> dict[str, Any]:
        candidates = []
        for product in self.category_products("panels"):
            power_w = as_float(spec_value(product, "power_w"))
            surface_m2 = as_float(spec_value(product, "surface_m2"))
            if not power_w or power_w <= 0:
                compatibility = compatibility_result(
                    [check("PANEL_POWER_MISSING", "Puissance panneau", "failed", "La puissance du panneau n'est pas renseignee.")],
                    [warning("PANEL_MANUAL_VALIDATION_REQUIRED", "Le panneau ne peut pas etre compare sans puissance nominale.")],
                )
                quantity = 0
                theoretical = 0.0
                installed_kwp = 0.0
                reasons = ["Puissance nominale manquante dans le catalogue."]
            else:
                theoretical = float(target_kwp) * 1000 / power_w
                quantity = max(1, ceil(theoretical))
                installed_kwp = quantity * power_w / 1000
                checks = [
                    check(
                        "PANEL_POWER_TARGET",
                        "Puissance panneau",
                        "passed",
                        "Le nombre de panneaux couvre la puissance PV cible.",
                        expected=f">= {target_kwp:.2f} kWp",
                        actual=installed_kwp,
                    )
                ]
                warnings_list = []
                if roof_area_m2 and surface_m2:
                    required_area = quantity * surface_m2
                    status = "passed" if required_area <= roof_area_m2 + 1e-9 else "failed"
                    checks.append(check(
                        "PANEL_SURFACE",
                        "Surface disponible",
                        status,
                        "La surface disponible couvre le champ PV." if status == "passed" else "La surface disponible semble insuffisante.",
                        expected=f"<= {roof_area_m2}",
                        actual=required_area,
                    ))
                    if status == "failed":
                        warnings_list.append(warning(
                            "ROOF_AREA_LIMIT",
                            "La surface disponible semble insuffisante pour ce panneau.",
                            value=required_area,
                        ))
                elif roof_area_m2:
                    checks.append(check(
                        "PANEL_SURFACE_DATA_MISSING",
                        "Surface disponible",
                        "manual",
                        "La surface unitaire du panneau manque dans le catalogue.",
                    ))
                    warnings_list.append(warning(
                        "PANEL_SURFACE_VALIDATION_REQUIRED",
                        "La surface du panneau doit etre confirmee pour verifier la toiture.",
                    ))
                compatibility = compatibility_result(checks, warnings_list)
                reasons = [
                    f"{quantity} panneau(x) donnent {installed_kwp:.2f} kWp pour un besoin cible de {target_kwp:.2f} kWp.",
                    f"Puissance unitaire catalogue: {power_w:.0f} W.",
                ]
            candidates.append(self._candidate(
                component="panel",
                product=product,
                quantity=quantity,
                compatibility=compatibility,
                reasons=reasons,
                metrics={
                    "target_kwp": float(target_kwp),
                    "theoretical_quantity": theoretical,
                    "installed_kwp": installed_kwp,
                    "power_w": power_w,
                    "surface_m2": surface_m2,
                },
                oversizing=max(0.0, installed_kwp - float(target_kwp)),
            ))
        return self._select_best("panel", candidates, "Puissance PV cible")

    def select_battery(
        self,
        required_usable_kwh: float,
        *,
        battery_margin: float,
        fallback_dod: float,
        fallback_efficiency: float,
        required_power_kw: float | None = None,
    ) -> dict[str, Any]:
        candidates = []
        for product in self.category_products("batteries"):
            nominal_kwh = as_float(spec_value(product, "capacity_kwh", "energy_kwh"))
            dod = as_ratio(spec_value(product, "usable_energy_kwh"))  # explicit usable handled below
            usable_kwh = as_float(spec_value(product, "usable_energy_kwh"))
            if usable_kwh is None and nominal_kwh is not None:
                dod_ratio = as_ratio(spec_value(product, "depth_of_discharge", "dod_percent", "battery_dod"), fallback_dod)
                eff_ratio = as_ratio(spec_value(product, "round_trip_efficiency", "efficiency_percent", "efficiency"), fallback_efficiency)
                usable_kwh = nominal_kwh * max(dod_ratio or 0, 0.01) * max(eff_ratio or 0, 0.01)
            if nominal_kwh is None or usable_kwh is None or usable_kwh <= 0:
                compatibility = compatibility_result(
                    [check("BATTERY_CAPACITY_MISSING", "Capacite batterie", "failed", "La capacite batterie n'est pas exploitable.")],
                    [warning("BATTERY_MANUAL_VALIDATION_REQUIRED", "La batterie ne peut pas etre dimensionnee sans capacite exploitable.")],
                )
                quantity = 0
                installed_nominal = 0.0
                installed_usable = 0.0
                reasons = ["Capacite nominale ou energie utile manquante dans le catalogue."]
            else:
                quantity = max(1, ceil((required_usable_kwh * (1 + battery_margin)) / usable_kwh))
                installed_nominal = quantity * nominal_kwh
                installed_usable = quantity * usable_kwh
                checks = [
                    check(
                        "BATTERY_USABLE_TARGET",
                        "Energie utile batterie",
                        "passed" if installed_usable + 1e-9 >= required_usable_kwh * (1 + battery_margin) else "failed",
                        "La batterie couvre le besoin utile avec marge." if installed_usable + 1e-9 >= required_usable_kwh * (1 + battery_margin) else "La batterie ne couvre pas le besoin utile avec marge.",
                        expected=f">= {required_usable_kwh * (1 + battery_margin):.2f}",
                        actual=installed_usable,
                    ),
                ]
                compatibility = compatibility_result(checks, [])
                reasons = [
                    f"{quantity} module(s) donnent environ {installed_nominal:.2f} kWh installes.",
                    f"Energie utile prise en compte par module: {usable_kwh:.2f} kWh.",
                ]
            candidates.append(self._candidate(
                component="battery",
                product=product,
                quantity=quantity,
                compatibility=compatibility,
                reasons=reasons,
                metrics={
                    "required_usable_kwh": float(required_usable_kwh),
                    "battery_margin": float(battery_margin),
                    "installed_nominal_kwh": installed_nominal,
                    "installed_usable_kwh": installed_usable,
                    "nominal_unit_kwh": nominal_kwh,
                    "usable_unit_kwh": usable_kwh,
                    "required_power_kw": as_float(required_power_kw),
                },
                oversizing=max(0.0, installed_usable - (required_usable_kwh * (1 + battery_margin))),
            ))
        return self._select_best("battery", candidates, "Capacite utile cible")

    def select_inverter(
        self,
        target_power_kw: float,
        *,
        project: str,
        installed_pv_kwp: float | None = None,
        panel: dict[str, Any] | None = None,
        panel_count: int | None = None,
        battery: dict[str, Any] | None = None,
        battery_quantity: int = 1,
        required_battery_power_kw: float | None = None,
        dc_ac_ratio_min: float | None = None,
        dc_ac_ratio_max: float | None = None,
    ) -> dict[str, Any]:
        project_tokens = {
            "ongrid": ("on-grid", "on_grid", "reseau", "grid"),
            "offgrid": ("hybride", "hybrid", "off-grid", "off_grid"),
            "hybrid": ("hybride", "hybrid"),
        }.get(project, ())
        candidates = []
        for product in self.category_products("inverters", project_tokens):
            power_kw = as_float(spec_value(product, "rated_power_kw", "power_kw"))
            if power_kw is None or power_kw <= 0:
                compatibility = compatibility_result(
                    [check("INVERTER_POWER_MISSING", "Puissance onduleur", "failed", "La puissance de l'onduleur manque dans le catalogue.")],
                    [warning("INVERTER_MANUAL_VALIDATION_REQUIRED", "L'onduleur ne peut pas etre compare sans puissance nominale.")],
                )
                reasons = ["Puissance nominale manquante dans le catalogue."]
                quantity = 0
            else:
                base_checks = [
                    check(
                        "INVERTER_TARGET_POWER",
                        "Puissance onduleur",
                        "passed" if power_kw + 1e-9 >= target_power_kw else "failed",
                        "La puissance catalogue couvre la cible." if power_kw + 1e-9 >= target_power_kw else "La puissance catalogue est inferieure a la cible.",
                        expected=f">= {target_power_kw:.2f}",
                        actual=power_kw,
                    )
                ]
                compatibility_items = [compatibility_result(base_checks, [])]
                if installed_pv_kwp:
                    compatibility_items.append(self.compatibility.check_dc_ac_ratio(
                        installed_pv_kwp,
                        product,
                        min_ratio=dc_ac_ratio_min,
                        max_ratio=dc_ac_ratio_max,
                    ))
                if panel and panel_count:
                    compatibility_items.append(self.compatibility.check_panel_inverter(panel, product, panel_count=panel_count))
                if battery:
                    compatibility_items.append(self.compatibility.check_battery_inverter(
                        battery,
                        product,
                        battery_quantity=max(1, int(battery_quantity)),
                        required_power_kw=required_battery_power_kw,
                    ))
                compatibility = self.compatibility.combine(*compatibility_items)
                reasons = [f"Puissance catalogue: {power_kw:.2f} kW pour une cible de {target_power_kw:.2f} kW."]
                if installed_pv_kwp:
                    ratio = installed_pv_kwp / power_kw if power_kw else 0
                    reasons.append(f"Ratio DC/AC calcule: {ratio:.2f}.")
                quantity = 1
            candidates.append(self._candidate(
                component="inverter",
                product=product,
                quantity=quantity,
                compatibility=compatibility,
                reasons=reasons,
                metrics={
                    "target_power_kw": float(target_power_kw),
                    "catalog_power_kw": power_kw,
                    "installed_pv_kwp": as_float(installed_pv_kwp),
                },
                oversizing=max(0.0, (power_kw or 0) - float(target_power_kw)),
            ))
        return self._select_best("inverter", candidates, "Puissance onduleur cible")

    def select_ev_charger(
        self,
        target_power_kw: float,
        *,
        available_power_kw: float,
        phases: str,
        quantity: int = 1,
        nominal_voltage_v: float | None = None,
        available_current_a: float | None = None,
    ) -> dict[str, Any]:
        candidates = []
        for product in self.category_products("ev_chargers"):
            product_power = as_float(spec_value(product, "rated_power_kw", "power_kw"))
            checks = []
            if product_power is None:
                checks.append(check("EV_POWER_MISSING", "Puissance borne", "failed", "La puissance borne manque dans le catalogue."))
                compatibility = compatibility_result(checks, [warning("EV_NETWORK_VALIDATION_REQUIRED", "La borne ne peut pas etre comparee sans puissance nominale.")])
            else:
                checks.append(check(
                    "EV_TARGET_POWER",
                    "Puissance borne",
                    "passed" if abs(product_power - target_power_kw) <= 0.6 or product_power >= target_power_kw else "failed",
                    "La borne correspond a la famille de puissance cible." if abs(product_power - target_power_kw) <= 0.6 or product_power >= target_power_kw else "La borne est sous-dimensionnee par rapport a la cible.",
                    expected=f">= {target_power_kw:.2f}",
                    actual=product_power,
                ))
                compatibility = self.compatibility.combine(
                    compatibility_result(checks, []),
                    self.compatibility.check_ev_network(
                        product,
                        available_power_kw=available_power_kw,
                        phases=phases,
                        nominal_voltage_v=nominal_voltage_v,
                        available_current_a=available_current_a,
                    ),
                )
            candidates.append(self._candidate(
                component="ev_charger",
                product=product,
                quantity=max(1, int(quantity)),
                compatibility=compatibility,
                reasons=[f"Puissance borne catalogue: {product_power:.2f} kW." if product_power else "Puissance borne non documentee."],
                metrics={"target_power_kw": float(target_power_kw), "catalog_power_kw": product_power, "available_power_kw": float(available_power_kw)},
                oversizing=max(0.0, (product_power or 0) - float(target_power_kw)),
            ))
        return self._select_best("ev_charger", candidates, "Puissance borne cible")

    def select_thermal_tank(self, required_liters: float) -> dict[str, Any]:
        candidates = []
        for product in self.category_products("thermal", ("ballon",)):
            capacity_l = as_float(spec_value(product, "capacity_l", "tank_volume_l"))
            compatibility = compatibility_result([
                check(
                    "THERMAL_TANK_CAPACITY",
                    "Capacite ballon",
                    "passed" if capacity_l and capacity_l + 1e-9 >= required_liters else "failed",
                    "Le ballon couvre le volume cible." if capacity_l and capacity_l + 1e-9 >= required_liters else "Le ballon est inferieur au volume cible.",
                    expected=f">= {required_liters:.0f}",
                    actual=capacity_l,
                )
            ], [])
            candidates.append(self._candidate(
                component="thermal_tank",
                product=product,
                quantity=1 if capacity_l else 0,
                compatibility=compatibility,
                reasons=[f"Capacite ballon catalogue: {capacity_l:.0f} L." if capacity_l else "Capacite ballon non documentee."],
                metrics={"required_liters": float(required_liters), "capacity_l": capacity_l},
                oversizing=max(0.0, (capacity_l or 0) - float(required_liters)),
            ))
        return self._select_best("thermal_tank", candidates, "Volume ballon cible")

    def select_thermal_collector(self, quantity: int) -> dict[str, Any]:
        candidates = []
        for product in self.category_products("thermal", ("capteur",)):
            compatibility = compatibility_result(
                [check("THERMAL_COLLECTOR_AVAILABLE", "Capteur thermique", "passed", "Capteur disponible au catalogue.")],
                [],
            )
            candidates.append(self._candidate(
                component="thermal_collector",
                product=product,
                quantity=max(1, int(quantity)),
                compatibility=compatibility,
                reasons=["Capteur thermique actif disponible au catalogue."],
                metrics={"quantity": int(quantity)},
                oversizing=0.0,
            ))
        return self._select_best("thermal_collector", candidates, "Nombre de capteurs")

    def select_supporting_category(
        self,
        component: str,
        category: str,
        *,
        quantity: float = 1,
        subcategory_tokens: tuple[str, ...] = (),
        reason: str = "",
    ) -> dict[str, Any]:
        candidates = []
        for product in self.category_products(category, subcategory_tokens):
            compatibility = compatibility_result(
                [check("SUPPORTING_PRODUCT_AVAILABLE", "Produit de support", "passed", "Produit auxiliaire actif disponible au catalogue.")],
                [],
            )
            candidates.append(self._candidate(
                component=component,
                product=product,
                quantity=quantity,
                compatibility=compatibility,
                reasons=[reason or "Produit auxiliaire catalogue retenu."],
                metrics={"quantity": quantity},
                oversizing=0.0,
            ))
        return self._select_best(component, candidates, "Produit auxiliaire")

    def _candidate(
        self,
        *,
        component: str,
        product: dict[str, Any],
        quantity: float,
        compatibility: dict[str, Any],
        reasons: list[str],
        metrics: dict[str, Any],
        oversizing: float,
    ) -> dict[str, Any]:
        completeness = product_completeness(product)
        candidate = {
            "component": component,
            "product": product,
            "quantity": quantity,
            "compatibility": compatibility,
            "status": compatibility.get("status") or "manual_validation_required",
            "reasons": list(reasons),
            "warnings": list(compatibility.get("warnings") or []),
            "metrics": metrics,
            "oversizing": float(max(0.0, oversizing)),
            "completeness": completeness,
            "preferred": bool(product.get("preferred")),
            "priority": int(product.get("priority") or 0),
            "demo": bool(product.get("demo")),
            "stock": as_float(product.get("stock"), 0) or 0,
            "reference": product.get("reference") or "",
            "sort_key": (),
            "score": 0,
        }
        if candidate["stock"] <= 0:
            candidate["warnings"].append(warning(
                "CATALOG_STOCK_TO_CONFIRM",
                f"Le stock du produit {candidate['reference']} est a confirmer.",
                value=candidate["reference"],
            ))
            candidate["reasons"].append("Stock a confirmer.")
        else:
            candidate["reasons"].append(f"Stock catalogue: {candidate['stock']:.0f}.")
        if candidate["demo"]:
            candidate["warnings"].append(warning(
                "DEMO_PRODUCT_SELECTED",
                f"Le produit {candidate['reference']} est prepare par HeliAntha.",
                value=candidate["reference"],
                recommendation="Remplacer ce produit par une reference HeliAntha validee avant devis final.",
            ))
            candidate["reasons"].append("Produit prepare par HeliAntha.")
        if not completeness["complete"]:
            candidate["warnings"].append(warning(
                "PRODUCT_DATA_INCOMPLETE",
                f"Le produit {candidate['reference']} a une fiche catalogue incomplete.",
                value=", ".join(completeness["missing"][:3]),
                recommendation="Completer les caracteristiques techniques avant validation finale.",
            ))
            if candidate["status"] == "compatible":
                candidate["status"] = "compatible_with_warning"
            candidate["reasons"].append(f"Fiche catalogue {completeness['label'].lower()} ({completeness['score']} %).")

        candidate["sort_key"] = self._sort_key(candidate)
        candidate["score"] = self._score(candidate)
        return candidate

    @staticmethod
    def _sort_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
        return (
            STATUS_ORDER.get(candidate["status"], 2),
            0 if candidate["preferred"] else 1,
            -int(candidate["priority"]),
            0 if not candidate["demo"] else 1,
            0 if candidate["stock"] > 0 else 1,
            float(candidate["oversizing"]),
            100 - int(candidate["completeness"]["score"]),
            _price_value(candidate["product"]),
            candidate["reference"],
        )

    @staticmethod
    def _score(candidate: dict[str, Any]) -> int:
        status_penalty = {
            "compatible": 0,
            "compatible_with_warning": 8,
            "manual_validation_required": 18,
            "incompatible": 60,
        }.get(candidate["status"], 18)
        demo_penalty = 7 if candidate["demo"] else 0
        stock_penalty = 5 if candidate["stock"] <= 0 else 0
        oversize_penalty = min(20, round(candidate["oversizing"] * 3))
        preferred_bonus = 8 if candidate["preferred"] else 0
        priority_bonus = min(12, int(candidate["priority"]))
        completeness_bonus = round(int(candidate["completeness"]["score"]) / 10)
        score = 100 - status_penalty - demo_penalty - stock_penalty - oversize_penalty
        score += preferred_bonus + priority_bonus + completeness_bonus
        return max(0, min(100, score))

    def _select_best(self, component: str, candidates: list[dict[str, Any]], target_label: str) -> dict[str, Any]:
        ordered = sorted(candidates, key=lambda item: item["sort_key"])
        selected = next((item for item in ordered if item["status"] != "incompatible" and item["quantity"]), None)
        missing_code = {
            "panel": "NO_COMPATIBLE_PANEL",
            "battery": "NO_COMPATIBLE_BATTERY",
            "inverter": "NO_COMPATIBLE_INVERTER",
            "pump": "NO_COMPATIBLE_PUMP",
            "pump_drive": "NO_COMPATIBLE_DRIVE",
            "ev_charger": "NO_COMPATIBLE_EV_CHARGER",
            "thermal_tank": "NO_COMPATIBLE_THERMAL_TANK",
            "thermal_collector": "NO_COMPATIBLE_THERMAL_COLLECTOR",
        }.get(component, "CATALOG_PRODUCT_NOT_FOUND")
        rejected = []
        for item in ordered:
            if selected and item["reference"] == selected["reference"]:
                continue
            reason = item["reasons"][0] if item["reasons"] else "Candidat non retenu."
            rejected.append({
                "reference": item["reference"],
                "brand": item["product"].get("brand") or "",
                "model": item["product"].get("model") or "",
                "status": item["status"],
                "reason": reason,
                "score": item["score"],
                "metrics": item["metrics"],
            })
        if not selected:
            return {
                "component": component,
                "selected_product": None,
                "quantity": 0,
                "selection_score": 0,
                "reasons": [f"Aucun produit actif compatible n'a ete trouve pour {target_label.lower()}."],
                "rejected_candidates": rejected,
                "warnings": [warning(
                    missing_code,
                    f"Aucun produit actif n'a pu etre retenu pour {component}.",
                    value=component,
                    recommendation="Completer le catalogue ou valider manuellement une reference.",
                )],
                "compatibility": {"status": "incompatible", "checks": [], "warnings": [], "details": {}},
                "status": "incompatible",
                "metrics": {"candidate_count": len(candidates)},
            }
        return {
            "component": component,
            "selected_product": deepcopy(selected["product"]),
            "quantity": selected["quantity"],
            "selection_score": selected["score"],
            "reasons": selected["reasons"],
            "rejected_candidates": rejected,
            "warnings": selected["warnings"],
            "compatibility": selected["compatibility"],
            "status": selected["status"],
            "metrics": {**selected["metrics"], "candidate_count": len(candidates)},
        }
