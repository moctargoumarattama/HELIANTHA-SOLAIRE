"""BOM-based pricing for HeliAntha Smart Quote.

Real catalogue prices are used line by line.  Existing configurable percentage
rules remain available only as explicit fallbacks when a BOM family has no
priced catalogue product yet.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any


MAIN_EQUIPMENT_CATEGORIES = {
    "panels", "batteries", "inverters", "pumps", "drives", "ev_chargers", "thermal"
}


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0")


def _money(value: Decimal | float | int) -> Decimal:
    return _decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _float(value: Decimal) -> float:
    return float(_money(value))


def _warning(code: str, message: str, recommendation: str, value: Any = "") -> dict[str, Any]:
    return {
        "code": code,
        "level": "warning",
        "message": message,
        "parameter": "pricing",
        "value": value,
        "recommendation": recommendation,
    }


class PricingEngine:
    version = "2.0-bom"

    labels = {
        "principal_equipment": "Matériel principal",
        "accessories": "Accessoires",
        "protections": "Protections",
        "cabling": "Câblage",
        "structure": "Structure",
        "installation": "Installation",
        "labor": "Main-d'oeuvre",
        "travel": "Déplacement",
        "other_costs": "Autres coûts",
    }

    fallback_rules = {
        "accessories": "accessories_rate",
        "protections": "protections_rate",
        "cabling": "cabling_rate",
        "structure": "structure_rate",
    }

    def breakdown(
        self,
        project: str,
        equipment: list[dict[str, Any]],
        context: Any,
        travel_km: float = 0,
    ) -> dict[str, Any]:
        categories = {key: Decimal("0") for key in self.labels}
        priced_families: set[str] = set()
        warnings: list[dict[str, Any]] = []
        demo_prices = False

        for item in equipment:
            financial_category = item.get("financial_category") or self._financial_category(item)
            total = _money(item.get("total_price"))
            categories[financial_category] = categories.get(financial_category, Decimal("0")) + total
            if item.get("price_status") == "catalog_price" and total > 0:
                priced_families.add(financial_category)
            if item.get("price_status") == "to_confirm" and item.get("product_id"):
                warnings.append(_warning(
                    "PRICE_CONFIRMATION_REQUIRED",
                    f"Le prix du produit {item.get('reference') or item.get('model') or ''} n'est pas renseigné.",
                    "Compléter le prix catalogue avant d'émettre un devis définitif.",
                    item.get("reference") or "",
                ))
            if item.get("demo") and total > 0:
                demo_prices = True

        principal = categories["principal_equipment"]
        pricing_sources: list[dict[str, Any]] = []
        for family, rule_key in self.fallback_rules.items():
            if family in priced_families:
                pricing_sources.append({
                    "category": family,
                    "source_type": "catalog",
                    "source_name": "Somme des lignes catalogue de la BOM",
                    "rule_key": "",
                    "value": _float(categories[family]),
                })
                continue
            rate = _decimal(context.r(rule_key, 0))
            fallback_amount = _money(principal * rate)
            categories[family] += fallback_amount
            if fallback_amount > 0:
                pricing_sources.append({
                    "category": family,
                    "source_type": "fallback_pricing_rule",
                    "source_name": getattr(context, "pricing", {}).get(rule_key, {}).get("name") or rule_key,
                    "rule_key": rule_key,
                    "rate": float(rate),
                    "value": _float(fallback_amount),
                })
                warnings.append(_warning(
                    "PRICE_FALLBACK_USED",
                    f"Le poste « {self.labels[family]} » utilise encore une règle tarifaire proportionnelle de secours.",
                    "Ajouter les produits réels correspondants au catalogue pour obtenir un prix exact.",
                    rule_key,
                ))

        fixed_rules = {
            "installation": ("installation_base",),
            "labor": ("labor_base",),
            "other_costs": ("study_fee", "commissioning_fee", "other_costs"),
        }
        for family, keys in fixed_rules.items():
            amount = sum((_decimal(context.r(key, 0)) for key in keys), Decimal("0"))
            categories[family] += _money(amount)
            pricing_sources.append({
                "category": family,
                "source_type": "pricing_rule",
                "source_name": ", ".join(keys),
                "rule_key": ",".join(keys),
                "value": _float(_money(amount)),
            })

        travel_fixed = _decimal(context.r("travel_fixed", 0))
        travel_variable = _decimal(travel_km) * _decimal(context.r("travel_cost_per_km", 0))
        categories["travel"] += _money(max(travel_fixed, travel_variable))
        pricing_sources.append({
            "category": "travel",
            "source_type": "pricing_rule",
            "source_name": "Déplacement fixe ou kilométrique",
            "rule_key": "travel_fixed,travel_cost_per_km",
            "value": _float(categories["travel"]),
        })

        if demo_prices:
            warnings.append(_warning(
                "PRICE_FALLBACK_USED",
                "Au moins un prix provient d'une référence HeliAntha.",
                "Remplacer les prix provisoires par le catalogue validé HeliAntha.",
                "heliantha_catalog",
            ))

        subtotal = _money(sum(categories.values(), Decimal("0")))
        margin_rate = _decimal(context.r("margin_rate", 0))
        vat_rate = _decimal(context.r("vat_rate", 0))
        margin = _money(subtotal * margin_rate)
        total_ht = _money(subtotal + margin)
        vat = _money(total_ht * vat_rate)
        total_ttc = _money(total_ht + vat)
        material_total = _money(sum(
            (_decimal(item.get("total_price")) for item in equipment if item.get("price_status") == "catalog_price"),
            Decimal("0"),
        ))

        pricing_rules_used = {}
        for key, item in getattr(context, "pricing", {}).items():
            if int(item.get("active", 1) or 0) != 1:
                continue
            pricing_rules_used[key] = {
                "key": key,
                "name": item.get("name") or key,
                "value": item.get("value"),
                "unit": item.get("unit") or "",
                "value_type": item.get("value_type") or item.get("type") or "",
                "project": item.get("project"),
            }

        return {
            "project": project,
            "categories": [
                {"key": key, "label": label, "amount": _float(categories.get(key, Decimal("0")))}
                for key, label in self.labels.items()
            ],
            "material_catalog_total": _float(material_total),
            "subtotal_before_margin": _float(subtotal),
            "margin_rate": float(margin_rate),
            "commercial_margin": _float(margin),
            "total_ht": _float(total_ht),
            "vat_rate": float(vat_rate),
            "vat": _float(vat),
            "total_ttc": _float(total_ttc),
            "currency": "DH",
            "pricing_version": self.version,
            "pricing_sources": pricing_sources,
            "pricing_rules_used": pricing_rules_used,
            "warnings": self._deduplicate_warnings(warnings),
            "contains_demo_prices": demo_prices,
            "is_final_price": not warnings,
        }

    @staticmethod
    def _financial_category(item: dict[str, Any]) -> str:
        category = item.get("category")
        if category in MAIN_EQUIPMENT_CATEGORIES:
            return "principal_equipment"
        if category == "protections":
            return "protections"
        if category == "cables":
            return "cabling"
        if category == "structures":
            return "structure"
        if category == "accessories":
            return "accessories"
        return "other_costs"

    @staticmethod
    def _deduplicate_warnings(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique = []
        seen = set()
        for item in warnings:
            signature = (item.get("code"), item.get("message"), item.get("value"))
            if signature in seen:
                continue
            seen.add(signature)
            unique.append(item)
        return unique
