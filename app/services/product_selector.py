"""Deterministic catalogue selection helpers for HeliAntha Smart Quote."""

from __future__ import annotations

from copy import deepcopy
from math import ceil
from typing import Any

from app.catalog import normalize_category, product_completeness

from .compatibility import (
    CompatibilityChecker,
    as_float,
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
            "pump": "NO_COMPATIBLE_PUMP",
            "pump_drive": "NO_COMPATIBLE_DRIVE",
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
