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
        "principal_equipment": "MatÃ©riel principal",
        "accessories": "Accessoires",
        "protections": "Protections",
        "cabling": "CÃ¢blage",
        "structure": "Structure",
        "installation": "Installation",
        "labor": "Main-d'oeuvre",
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
        line_items: list[dict[str, Any]] = []

        global_vat_rate = _decimal(context.r("vat_rate", 0))

        for item in equipment:
            financial_category = item.get("financial_category") or self._financial_category(item)
            total = _money(item.get("total_price"))
            categories[financial_category] = categories.get(financial_category, Decimal("0")) + total
            line_vat_rate = _decimal(item.get("vat_rate") if item.get("vat_rate") not in (None, "") else global_vat_rate)
            line_items.append({
                "category": financial_category,
                "total": _decimal(total),
                "vat_rate": line_vat_rate,
                "price_status": item.get("price_status") or "",
                "source_type": item.get("source_type") or item.get("source", {}).get("source_type") or "",
                "source_name": item.get("source_name") or item.get("source", {}).get("source_name") or "",
            })
            if item.get("price_status") in {"catalog_price", "rule_price"} and total > 0:
                priced_families.add(financial_category)
            if item.get("price_status") == "to_confirm" and item.get("product_id"):
                warnings.append(_warning(
                    "PRICE_CONFIRMATION_REQUIRED",
                    f"Le prix du produit {item.get('reference') or item.get('model') or ''} n'est pas renseignÃ©.",
                    "ComplÃ©ter le prix catalogue avant d'Ã©mettre un devis dÃ©finitif.",
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
                line_items.append({
                    "category": family,
                    "total": _decimal(fallback_amount),
                    "vat_rate": global_vat_rate,
                    "price_status": "fallback_price",
                    "source_type": "fallback_pricing_rule",
                    "source_name": getattr(context, "pricing", {}).get(rule_key, {}).get("name") or rule_key,
                })
                warnings.append(_warning(
                    "PRICE_FALLBACK_USED",
                    f"Le poste Â« {self.labels[family]} Â» utilise encore une rÃ¨gle tarifaire proportionnelle de secours.",
                    "Ajouter les produits rÃ©els correspondants au catalogue pour obtenir un prix exact.",
                    rule_key,
                ))

        has_installation_line = any((item.get("financial_category") or self._financial_category(item)) == "installation" for item in equipment)
        fixed_rules = {
            "installation": ("installation_base", "commissioning_fee"),
            "labor": ("labor_base",),
        }
        for family, keys in fixed_rules.items():
            if family in {"installation", "labor"} and has_installation_line:
                continue
            amount = sum((_decimal(context.r(key, 0)) for key in keys), Decimal("0"))
            amount = _money(amount)
            categories[family] += amount
            pricing_sources.append({
                "category": family,
                "source_type": "pricing_rule",
                "source_name": ", ".join(keys),
                "rule_key": ",".join(keys),
                "value": _float(amount),
            })
            if amount > 0:
                line_items.append({
                    "category": family,
                    "total": _decimal(amount),
                    "vat_rate": global_vat_rate,
                    "price_status": "pricing_rule",
                    "source_type": "pricing_rule",
                    "source_name": ", ".join(keys),
                })

        if demo_prices:
            warnings.append(_warning(
                "PRICE_FALLBACK_USED",
                "Au moins un prix provient d'une rÃ©fÃ©rence HeliAntha.",
                "Remplacer les prix provisoires par le catalogue validÃ© HeliAntha.",
                "heliantha_catalog",
            ))

        subtotal = _money(sum(categories.values(), Decimal("0")))
        total_ht = subtotal
        vat = Decimal("0")
        vat_breakdown: list[dict[str, Any]] = []
        if subtotal > 0:
            for item in line_items:
                base = _decimal(item.get("total"))
                if base <= 0:
                    continue
                line_ht = base
                line_vat_rate = _decimal(item.get("vat_rate") if item.get("vat_rate") not in (None, "") else global_vat_rate)
                line_vat = _money(line_ht * line_vat_rate)
                vat += _decimal(line_vat)
                vat_breakdown.append({
                    "category": item.get("category"),
                    "total_ht": _float(_money(line_ht)),
                    "vat_rate": float(line_vat_rate),
                    "vat": _float(line_vat),
                })
        vat = _money(vat)
        total_ttc = _money(total_ht + vat)
        material_total = _money(sum(
            (_decimal(item.get("total")) for item in line_items if item.get("price_status") != "to_confirm"),
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
            "total_ht": _float(total_ht),
            "vat_rate": float(global_vat_rate),
            "vat": _float(vat),
            "total_ttc": _float(total_ttc),
            "currency": "DH",
            "pricing_version": self.version,
            "pricing_sources": pricing_sources,
            "pricing_rules_used": pricing_rules_used,
            "vat_breakdown": vat_breakdown,
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
        return "installation"

    @staticmethod
    def _deduplicate_warnings(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique: list[dict[str, Any]] = []
        seen: set[tuple[Any, Any, Any, Any]] = set()
        for warning in warnings:
            key = (
                warning.get("code"),
                warning.get("message"),
                warning.get("value"),
                warning.get("recommendation"),
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(warning)
        return unique
