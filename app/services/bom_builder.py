"""Build an immutable, explainable bill of materials from product selections.

The builder deliberately does not decide whether a product is compatible.  It
only turns decisions made by :class:`ProductSelector` into quote lines and adds
honest placeholders for work that still requires an HeliAntha engineer.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


COMPONENT_LABELS = {
    "panel": "Panneau photovoltaïque",
    "battery": "Batterie",
    "inverter": "Onduleur",
    "pump": "Pompe",
    "pump_drive": "Variateur de pompage",
    "ev_charger": "Borne EV",
    "thermal_tank": "Ballon solaire",
    "thermal_collector": "Capteur solaire thermique",
    "protection_dc": "Protection DC",
    "protection_ac": "Protection AC",
    "protection_battery": "Protection batterie",
    "protection_motor": "Protection moteur",
    "ev_protection": "Protection dédiée borne EV",
    "cable_dc": "Câble photovoltaïque DC",
    "cable_ac": "Câble AC",
    "cable_battery": "Câble batterie",
    "cable_motor": "Câble moteur",
    "ev_cable": "Câble borne EV",
    "structure": "Structure photovoltaïque",
    "thermal_structure": "Support solaire thermique",
    "accessory": "Accessoires",
}


def _money(value: Any) -> float:
    try:
        amount = Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        amount = Decimal("0.00")
    return float(amount)


def _warning(code: str, message: str, recommendation: str, parameter: str = "") -> dict[str, Any]:
    return {
        "code": code,
        "level": "warning",
        "message": message,
        "parameter": parameter,
        "value": "",
        "recommendation": recommendation,
    }


class BOMBuilder:
    """Create the technical and priced material snapshot for a new quote."""

    version = "1.0"

    def build(
        self,
        project: str,
        selections: dict[str, dict[str, Any]],
        data: dict[str, Any],
        final_results: dict[str, Any],
        fallback_lines: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        lines: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        for component, selection in selections.items():
            if not selection or not selection.get("selected_product"):
                continue
            lines.append(self._selection_line(component, selection))

        # Keep an explicit fallback technical line only when no selected
        # catalogue line already fulfils that historical category.
        selected_categories = {line.get("category") for line in lines}
        for fallback in fallback_lines or []:
            category = fallback.get("category")
            if category in selected_categories:
                continue
            lines.append(self._fallback_line(fallback))
            selected_categories.add(category)

        required_placeholders = self._required_placeholders(project, selections, data, final_results)
        for placeholder in required_placeholders:
            component = placeholder["component"]
            if selections.get(component, {}).get("selected_product"):
                continue
            lines.append(self._placeholder_line(**placeholder))
            warnings.append(_warning(
                placeholder["warning_code"],
                placeholder["warning_message"],
                placeholder["recommendation"],
                component,
            ))

        material_total = _money(sum(float(line.get("total_price") or 0) for line in lines))
        unpriced = [line for line in lines if line.get("price_status") != "catalog_price"]
        manual = [line for line in lines if line.get("compatibility_status") == "manual_validation_required"]
        return {
            "version": self.version,
            "lines": lines,
            "material_total": material_total,
            "currency": "DH",
            "line_count": len(lines),
            "unpriced_line_count": len(unpriced),
            "manual_validation_line_count": len(manual),
            "warnings": warnings,
        }

    @staticmethod
    def _selection_line(component: str, selection: dict[str, Any]) -> dict[str, Any]:
        product = deepcopy(selection["selected_product"])
        quantity = float(selection.get("quantity") or 1)
        if quantity.is_integer():
            quantity = int(quantity)
        unit_price = _money(selection.get("unit_price") if selection.get("unit_price") is not None else product.get("sale_price"))
        reasons = [str(item) for item in selection.get("reasons") or []]
        source_type = selection.get("source_type") or product.get("source_type") or ("heliantha" if product.get("demo") else "catalog")
        source_name = selection.get("source_name") or product.get("source_name") or ("HeliAntha" if product.get("demo") else " ".join(str(product.get(key) or "") for key in ("brand", "model")).strip())
        source_name = source_name or product.get("reference") or "Produit catalogue"
        source_reference = selection.get("source_reference") or product.get("source_reference") or product.get("reference") or ""
        financial_category = selection.get("financial_category") or product.get("financial_category") or product.get("category") or "other"
        vat_rate = selection.get("vat_rate") if selection.get("vat_rate") is not None else product.get("vat_rate")
        return {
            "category": product.get("category") or "other",
            "financial_category": financial_category,
            "component": component,
            "product_id": product.get("id"),
            "reference": product.get("reference") or "",
            "brand": product.get("brand") or "",
            "model": product.get("model") or "",
            "description": product.get("description") or COMPONENT_LABELS.get(component, component),
            "role": COMPONENT_LABELS.get(component, component),
            "quantity": quantity,
            "unit": product.get("unit") or "piece",
            "unit_price": unit_price,
            "total_price": _money(Decimal(str(quantity)) * Decimal(str(unit_price))),
            "price_status": selection.get("price_status") or ("catalog_price" if unit_price else "to_confirm"),
            "currency": product.get("currency") or "DH",
            "vat_rate": vat_rate,
            "technical_reason": " ; ".join(reasons),
            "selection_reasons": reasons,
            "selection_score": selection.get("selection_score", selection.get("score")),
            "compatibility_status": selection.get("status") or selection.get("compatibility_status") or "manual_validation_required",
            "compatibility": deepcopy(selection.get("compatibility") or {}),
            "source": {
                "source_type": source_type,
                "source_name": source_name,
                "source_reference": source_reference,
                "product_id": product.get("id"),
            },
            "source_type": source_type,
            "demo": bool(product.get("demo")),
            "preferred": bool(product.get("preferred")),
            "priority": int(product.get("priority") or 0),
            "technical_specs": deepcopy(product.get("technical_specs") or {}),
            "power_w": product.get("power_w"),
            "power_kw": product.get("power_kw"),
            "capacity_kwh": product.get("capacity_kwh"),
            "capacity_l": product.get("capacity_l"),
            "efficiency": product.get("efficiency"),
            "technology": product.get("technology") or "",
            "warranty": product.get("warranty") or "",
            "datasheet_url": product.get("datasheet_url") or "",
            "product_snapshot": product,
        }

    @staticmethod
    def _fallback_line(item: dict[str, Any]) -> dict[str, Any]:
        line = deepcopy(item)
        quantity = float(line.get("quantity") or 1)
        if quantity.is_integer():
            quantity = int(quantity)
        unit_price = _money(line.get("unit_price"))
        source = deepcopy(line.get("source") or {})
        source_type = line.get("source_type") or source.get("source_type") or "fallback"
        source_name = line.get("source_name") or source.get("source_name") or "Valeur de secours HeliAntha Smart Quote"
        source_reference = line.get("source_reference") or source.get("source_reference") or line.get("reference") or ""
        financial_category = line.get("financial_category") or line.get("category") or "other"
        line.update({
            "component": line.get("component") or line.get("category") or "fallback",
            "product_id": None,
            "quantity": quantity,
            "unit_price": unit_price,
            "total_price": _money(Decimal(str(quantity)) * Decimal(str(unit_price))),
            "price_status": line.get("price_status") or ("fallback_price" if unit_price else "to_confirm"),
            "currency": line.get("currency") or "DH",
            "financial_category": financial_category,
            "technical_reason": line.get("technical_reason") or line.get("role") or "Valeur technique de secours.",
            "selection_reasons": line.get("selection_reasons") or ["Aucun produit catalogue compatible n'a été confirmé."],
            "compatibility_status": line.get("compatibility_status") or "manual_validation_required",
            "source": source or {
                "source_type": source_type,
                "source_name": source_name,
                "source_reference": source_reference,
                "product_id": None,
            },
            "source_type": source_type,
            "demo": bool(line.get("demo", True)),
            "technical_specs": deepcopy(line.get("technical_specs") or {}),
            "product_snapshot": None,
        })
        line["source_name"] = source_name
        line["source_reference"] = source_reference
        return line

    @staticmethod
    def _placeholder_line(
        component: str,
        category: str,
        description: str,
        quantity: float,
        unit: str,
        technical_specs: dict[str, Any],
        **_: Any,
    ) -> dict[str, Any]:
        return {
            "category": category,
            "component": component,
            "product_id": None,
            "reference": "",
            "brand": "",
            "model": "À confirmer",
            "description": description,
            "role": COMPONENT_LABELS.get(component, description),
            "quantity": quantity,
            "unit": unit,
            "unit_price": 0.0,
            "total_price": 0.0,
            "price_status": "to_confirm",
            "currency": "DH",
            "technical_reason": "Dimensionnement détaillé à valider avec les données du site et les règles HeliAntha.",
            "selection_reasons": ["Aucune référence catalogue suffisamment documentée n'a été sélectionnée."],
            "selection_score": None,
            "compatibility_status": "manual_validation_required",
            "compatibility": {"status": "manual_validation_required", "checks": []},
            "source": {
                "source_type": "manual_validation",
                "source_name": "Validation technique HeliAntha nécessaire",
                "source_reference": "",
                "product_id": None,
            },
            "source_type": "manual_validation",
            "demo": False,
            "technical_specs": technical_specs,
            "product_snapshot": None,
        }

    @staticmethod
    def _required_placeholders(
        project: str,
        selections: dict[str, dict[str, Any]],
        data: dict[str, Any],
        final: dict[str, Any],
    ) -> list[dict[str, Any]]:
        panels = int(final.get("panels") or selections.get("panel", {}).get("quantity") or 0)
        distance = float(data.get("distance") or data.get("cable_length") or 0)

        def item(component: str, category: str, description: str, code: str, message: str,
                 quantity: float = 1, unit: str = "lot", specs: dict[str, Any] | None = None) -> dict[str, Any]:
            return {
                "component": component,
                "category": category,
                "description": description,
                "quantity": quantity,
                "unit": unit,
                "technical_specs": specs or {},
                "warning_code": code,
                "warning_message": message,
                "recommendation": "Choisir et dimensionner la référence lors de la validation technique.",
            }

        placeholders: list[dict[str, Any]] = []
        if project in {"offgrid", "hybrid", "ongrid"}:
            placeholders.extend([
                item("protection_dc", "protections", "Sectionnement et protection du champ photovoltaïque", "PROTECTION_SIZING_REQUIRED", "Les protections DC restent à dimensionner."),
                item("protection_ac", "protections", "Protection AC et coffret", "PROTECTION_SIZING_REQUIRED", "La protection AC reste à dimensionner."),
                item("cable_dc", "cables", "Câblage solaire DC", "CABLE_SIZING_REQUIRED", "La section et la longueur du câble DC restent à confirmer.", specs={"length_m": distance or None, "section_theoretical_mm2": None, "section_selected_mm2": None}),
                item("structure", "structures", "Structure adaptée au support du site", "STRUCTURE_SELECTION_REQUIRED", "La structure doit être confirmée selon le type de toiture ou de sol.", quantity=max(panels, 1), unit="support panneau", specs={"panel_quantity": panels, "mounting_type": data.get("mounting_type") or data.get("roof_type") or "à confirmer"}),
            ])
        if project in {"offgrid", "hybrid"}:
            placeholders.extend([
                item("protection_battery", "protections", "Protection batterie", "PROTECTION_SIZING_REQUIRED", "La protection batterie reste à dimensionner."),
                item("cable_battery", "cables", "Câblage batterie", "CABLE_SIZING_REQUIRED", "La section du câble batterie reste à confirmer.", specs={"section_theoretical_mm2": None, "section_selected_mm2": None}),
            ])
        if project == "pumping" and not final.get("pumping_rule_key"):
            placeholders.extend([
                item("protection_motor", "protections", "Protection et sectionnement moteur", "PROTECTION_SIZING_REQUIRED", "La protection du moteur reste à dimensionner."),
                item("cable_motor", "cables", "Câble pompe / moteur", "CABLE_SIZING_REQUIRED", "La section du câble moteur reste à confirmer.", quantity=max(distance, 1), unit="m" if distance else "lot", specs={"length_m": distance or None, "section_theoretical_mm2": None, "section_selected_mm2": None}),
            ])
        if project == "ev":
            placeholders.extend([
                item("ev_protection", "protections", "Disjoncteur et différentiel dédiés à la borne", "PROTECTION_SIZING_REQUIRED", "La protection dédiée à la borne reste à dimensionner."),
                item("ev_cable", "cables", "Câble d'alimentation de la borne", "CABLE_SIZING_REQUIRED", "La section du câble EV reste à confirmer.", quantity=max(distance, 1), unit="m" if distance else "lot", specs={"length_m": distance or None, "section_theoretical_mm2": None, "section_selected_mm2": None}),
            ])
        if project == "thermal":
            placeholders.append(item("thermal_structure", "structures", "Support du système solaire thermique", "STRUCTURE_SELECTION_REQUIRED", "Le support thermique doit être confirmé selon le site."))
        return placeholders
