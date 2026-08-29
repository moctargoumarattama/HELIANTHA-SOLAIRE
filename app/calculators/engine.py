"""Structured pre-sizing engine for HeliAntha Smart Quote.

The formulas remain provisional. The important change in this version is the
shape of the calculation result: every quote now keeps the inputs, assumptions,
parameters, intermediate values, warnings, selected equipment, pricing details
and calculator versions used at creation time.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from math import ceil
from typing import Any, Callable

from app.constants import GRAVITY, SECONDS_PER_HOUR, WATER_DENSITY, WATER_HEAT_WH_PER_LITER_C, WATTS_PER_KILOWATT
from app.defaults import (
    CALCULATION_PARAMETERS,
    CALCULATOR_VERSIONS,
    CATALOG_PRODUCTS,
    PRICING_RULES,
    SOURCE_TYPES,
    TECHNICAL_REFERENCE,
)
from app.pumping_rules import (
    PUMPING_SOLAR_RULE_DEFAULTS,
    find_rule as find_pumping_rule,
    format_percent,
    format_phase,
    format_pricing_mode,
    normalize_pump_cv,
)
from app.parameter_views import format_display_value
from app.services import BOMBuilder, CompatibilityChecker, PricingEngine as ServicePricingEngine, ProductSelector
from app.services.compatibility import as_float, normalize_text, spec_value


PSH_BY_CITY = {
    "casablanca": 5.1,
    "rabat": 5.0,
    "marrakech": 5.8,
    "agadir": 5.7,
    "ouarzazate": 6.2,
    "fes": 5.3,
    "fès": 5.3,
    "tanger": 4.8,
    "laayoune": 6.0,
    "laâyoune": 6.0,
}

MAIN_EQUIPMENT_CATEGORIES = {
    "panels",
    "batteries",
    "inverters",
    "pumps",
    "drives",
    "ev_chargers",
    "thermal",
}


class ValidationError(ValueError):
    pass


def number(data: dict[str, Any], key: str, default: float = 0) -> float:
    try:
        value = float(data.get(key, default) or default)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"La valeur « {key} » doit être un nombre.") from exc
    if value < 0:
        raise ValidationError(f"La valeur « {key} » ne peut pas être négative.")
    return value


def text(data: dict[str, Any], key: str, default: str = "") -> str:
    return str(data.get(key, default) or default).strip()


def round_up(value: float, step: float = 0.1) -> float:
    return ceil(value / step) * step


def warning(
    code: str,
    level: str,
    message: str,
    parameter: str = "",
    value: Any = "",
    recommendation: str = "",
) -> dict[str, Any]:
    return {
        "code": code,
        "level": level,
        "message": message,
        "parameter": parameter,
        "value": value,
        "recommendation": recommendation,
    }


@dataclass
class CalculationResult:
    project: str
    title: str
    summary: str
    inputs: dict[str, Any]
    assumptions: list[str]
    parameters_used: dict[str, dict[str, Any]]
    intermediate_results: dict[str, Any]
    warnings: list[dict[str, Any]]
    final_results: dict[str, Any]
    selected_equipment: list[dict[str, Any]]
    calculation_version: str
    metrics: list[dict[str, str]]
    reliability: dict[str, Any]
    reasoning_steps: list[dict[str, Any]]
    resolved_sources: dict[str, dict[str, Any]]
    offer_profile: str
    travel_km: float = 0


class ContextView:
    def __init__(self, context: dict[str, Any] | None = None):
        context = context or {}
        default_params = {
            key: {
                "key": key,
                "name": name,
                "value": value,
                "unit": unit,
                "category": category,
                "description": description,
            }
            for key, name, value, unit, category, description in CALCULATION_PARAMETERS
        }
        default_pricing = {
            key: {
                "key": key,
                "name": name,
                "value": value,
                "type": value_type,
                "unit": unit,
                "project": project,
            }
            for key, name, value, value_type, unit, project in PRICING_RULES
        }
        default_pumping_rules = {
            rule["rule_key"]: deepcopy(rule)
            for rule in PUMPING_SOLAR_RULE_DEFAULTS
        }
        products = deepcopy(context["products"]) if "products" in context else deepcopy(CATALOG_PRODUCTS)
        self.all_products = products
        self.products = [p for p in products if int(p.get("active", 1) or 0) == 1]
        self.parameters = self._merge(default_params, context.get("technical_parameters") or {})
        self.pricing = self._merge(default_pricing, context.get("pricing_rules") or {})
        self.pumping_rules = self._merge(default_pumping_rules, context.get("pumping_solar_rules") or {})
        self.reference = dict(context.get("technical_reference") or TECHNICAL_REFERENCE)

    @staticmethod
    def _merge(defaults: dict[str, dict[str, Any]], overrides: dict[str, Any]) -> dict[str, dict[str, Any]]:
        merged = deepcopy(defaults)
        for key, value in overrides.items():
            if isinstance(value, dict):
                base = merged.get(key, {"key": key, "name": key, "unit": "", "category": ""})
                base.update(value)
                merged[key] = base
            else:
                merged[key] = {"key": key, "name": key, "value": value, "unit": "", "category": ""}
        return merged

    def p(self, key: str, default: float = 0) -> float:
        try:
            return float(self.parameters.get(key, {}).get("value", default))
        except (TypeError, ValueError):
            return default

    def r(self, key: str, default: float = 0) -> float:
        try:
            item = self.pricing.get(key, {})
            if item and int(item.get("active", 1) or 0) != 1:
                return default
            return float(item.get("value", default))
        except (TypeError, ValueError):
            return default

    def used_parameters(self, keys: list[str]) -> dict[str, dict[str, Any]]:
        used = {}
        for key in keys:
            if key in self.parameters:
                item = deepcopy(self.parameters[key])
                source_type = "heliantha" if (item.get("source_type") or "") == "demo" else (item.get("source_type") or "heliantha")
                source = SOURCE_TYPES.get(source_type, SOURCE_TYPES["heliantha"])
                item["source_type"] = source_type
                item["source_badge"] = source["badge"]
                item["source_label"] = source["label"]
                used[key] = item
        return used

    def parameter_source(self, key: str, default: float) -> dict[str, Any]:
        parameter = self.parameters.get(key)
        if parameter:
            source_type = "heliantha" if (parameter.get("source_type") or "") == "demo" else (parameter.get("source_type") or "heliantha")
            return {
                "key": key,
                "value": float(parameter.get("value") or default),
                "display_name": parameter.get("display_name") or parameter.get("name") or key,
                "display_kind": parameter.get("display_kind") or parameter.get("unit") or "",
                "unit": parameter.get("unit") or "",
                "category": parameter.get("category") or "",
                "source_type": source_type,
                "source_name": parameter.get("source_name") or "HeliAntha",
                "source_reference": parameter.get("source_reference") or key,
            }
        return {
            "key": key,
            "value": float(default),
            "display_name": key,
            "display_kind": "",
            "unit": "",
            "category": "",
            "source_type": "heliantha",
            "source_name": "HeliAntha",
            "source_reference": key,
        }

    @staticmethod
    def _product_field(product: dict[str, Any] | None, field_name: str | list[str] | tuple[str, ...]) -> Any:
        if not product:
            return None
        field_names = [field_name] if isinstance(field_name, str) else list(field_name)
        technical_specs = product.get("technical_specs") or {}
        for candidate in field_names:
            if product.get(candidate) not in (None, ""):
                return product.get(candidate)
            if technical_specs.get(candidate) not in (None, ""):
                return technical_specs.get(candidate)
        return None

    def product_value_or_parameter(
        self,
        product: dict[str, Any] | None,
        product_key: str | list[str] | tuple[str, ...],
        parameter_key: str,
        default: float,
    ) -> dict[str, Any]:
        """Prepared priority chain for future formula upgrades.

        Current formulas keep their existing behavior. This helper makes the
        intended priority explicit for the next phase: product data first,
        then an active HeliAntha/reference/demo parameter, then a fallback.
        """
        if product and product.get("_fallback_parameter_key") == parameter_key:
            return self.parameter_source(parameter_key, default)
        product_value = self._product_field(product, product_key)
        if product_value not in (None, ""):
            name = " ".join(str(product.get(part) or "") for part in ("brand", "model")).strip() or product.get("reference") or "Produit catalogue"
            return {
                "value": float(product_value),
                "source_type": "manufacturer",
                "source_name": name,
                "source_reference": product.get("reference", ""),
            }
        return self.parameter_source(parameter_key, default)

    def product(self, category: str, minimum_key: str | None = None, minimum_value: float = 0, subcategory: str = ""):
        candidates = [
            p
            for p in self.products
            if p.get("category") == category and (not subcategory or p.get("subcategory") == subcategory)
        ]
        if minimum_key:
            qualified = [p for p in candidates if float(p.get(minimum_key) or 0) >= minimum_value]
            if qualified:
                return sorted(qualified, key=lambda p: float(p.get(minimum_key) or 0))[0]
            if candidates:
                return sorted(candidates, key=lambda p: float(p.get(minimum_key) or 0), reverse=True)[0]
        return candidates[0] if candidates else None

    def panel(self) -> dict[str, Any]:
        panel = self.product("panels")
        if panel:
            return panel
        return {
            "reference": "PV-DEFAULT",
            "category": "panels",
            "brand": "HeliAntha provisoire",
            "model": f"{self.p('pv_panel_default_w', 590):.0f} Wc",
            "power_w": self.p("pv_panel_default_w", 590),
            "sale_price": 0,
            "unit": "piece",
            "_fallback_parameter_key": "pv_panel_default_w",
            "demo": False,
            "preferred": False,
            "priority": 0,
            "technical_specs": {"surface_m2": 2.6},
        }

    def psh_source(self, city: str) -> dict[str, Any]:
        normalized = city.strip().lower()
        if normalized in PSH_BY_CITY:
            return {
                "value": PSH_BY_CITY[normalized],
                "source_type": "local_data",
                "source_name": f"Ville: {city.strip() or normalized}",
                "source_reference": "base_locale_psh",
            }
        return self.parameter_source("productible_default_psh", 5.4)

    def pumping_rule_rows(self, rule_type: str | None = None) -> list[dict[str, Any]]:
        rows = list(self.pumping_rules.values())
        if rule_type:
            rows = [row for row in rows if str(row.get("rule_type") or "") == rule_type]
        return sorted(
            rows,
            key=lambda row: (
                int(row.get("sort_order") or 0),
                float(row.get("pump_cv") or 0),
                float(row.get("panel_power_w") or 0),
                float(row.get("drive_power_kw") or 0),
                str(row.get("title") or row.get("rule_key") or ""),
            ),
        )

    def pumping_rule(self, rule_type: str, **criteria: Any) -> dict[str, Any] | None:
        return find_pumping_rule(self.pumping_rule_rows(rule_type), rule_type, **criteria)


class PricingEngine:
    version = CALCULATOR_VERSIONS["PricingEngine"]

    def __init__(self):
        self._service = ServicePricingEngine()

    labels = {
        "principal_equipment": "Matériel principal",
        "accessories": "Accessoires",
        "protections": "Protections",
        "cabling": "Câblage",
        "structure": "Structure",
        "installation": "Installation",
        "labor": "Main-d'oeuvre",
    }

    def breakdown(
        self,
        project: str,
        equipment: list[dict[str, Any]],
        context: ContextView,
        travel_km: float = 0,
    ) -> dict[str, Any]:
        return self._service.breakdown(project, equipment, context, travel_km)

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


class CalculationEngine:
    version = "MVP-3.0-catalog"

    def __init__(self):
        self.pricing = PricingEngine()
        self.compatibility = CompatibilityChecker()
        self.bom_builder = BOMBuilder()

    def calculate(self, project: str, data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        calculators: dict[str, Callable[[dict[str, Any], ContextView], CalculationResult]] = {
            "pumping": self._pumping,
            "offgrid": self._offgrid,
            "ongrid": self._ongrid,
            "hybrid": self._hybrid,
            "ev": self._ev,
            "thermal": self._thermal,
            "iot": self._iot,
        }
        if project not in calculators:
            raise ValidationError("Type de projet non reconnu.")

        cfg = ContextView(context)
        technical = calculators[project](data, cfg)
        technical = self._phase3_enrich(project, technical, data, cfg)
        offers = self._offers(technical, cfg)
        optimal = next((offer for offer in offers if offer["recommended"]), offers[0])
        warnings = technical.warnings
        calculation_blocks = technical.intermediate_results.get("calculation_blocks") or []
        technical_configuration = technical.intermediate_results.get("technical_configuration") or {}
        compatibility = technical.intermediate_results.get("compatibility") or {}
        product_selections = technical.intermediate_results.get("product_selections") or {}
        bom = technical.intermediate_results.get("bom") or {}
        calculation_detail = {
            "inputs": technical.inputs,
            "assumptions": technical.assumptions,
            "parameters_used": technical.parameters_used,
            "intermediate_results": technical.intermediate_results,
            "calculation_blocks": calculation_blocks,
            "resolved_sources": technical.resolved_sources,
            "warnings": warnings,
            "final_results": technical.final_results,
            "selected_equipment": optimal["selected_equipment"],
            "reasoning_steps": technical.reasoning_steps,
            "calculation_version": technical.calculation_version,
            "technical_configuration": technical_configuration,
            "compatibility": compatibility,
            "product_selections": product_selections,
            "bom": bom,
        }
        snapshot = {
            "inputs": technical.inputs,
            "assumptions": technical.assumptions,
            "parameters_used": technical.parameters_used,
            "intermediate_results": technical.intermediate_results,
            "calculation_blocks": calculation_blocks,
            "resolved_sources": technical.resolved_sources,
            "warnings": warnings,
            "final_results": technical.final_results,
            "selected_equipment": optimal["selected_equipment"],
            "financial_breakdown": optimal["financial_breakdown"],
            "calculator_versions": self._versions(project),
            "technical_reference": cfg.reference,
            "calculation_version": technical.calculation_version,
            "technical_configuration": technical_configuration,
            "compatibility": compatibility,
            "product_selections": product_selections,
            "bom": bom,
        }
        return {
            "project": project,
            "title": technical.title,
            "summary": technical.summary,
            "metrics": technical.metrics,
            "confidence": technical.reliability["score"],
            "confidence_label": self._confidence_label(technical.reliability["score"]),
            "reliability": technical.reliability,
            "warnings": warnings,
            "warning_messages": [w["message"] for w in warnings],
            "offers": offers,
            "selected_equipment": optimal["selected_equipment"],
            "financial_breakdown": optimal["financial_breakdown"],
            "inputs": technical.inputs,
            "assumptions": technical.assumptions,
            "parameters_used": technical.parameters_used,
            "intermediate_results": technical.intermediate_results,
            "calculation_blocks": calculation_blocks,
            "resolved_sources": technical.resolved_sources,
            "final_results": technical.final_results,
            "reasoning_steps": technical.reasoning_steps,
            "calculation_detail": calculation_detail,
            "technical_configuration": technical_configuration,
            "compatibility": compatibility,
            "product_selections": product_selections,
            "bom": bom,
            "calculator_versions": self._versions(project),
            "technical_reference": cfg.reference,
            "quote_snapshot": snapshot,
            "engine_version": self.version,
            "disclaimer": (
                "Pré-estimation indicative basée sur des formules provisoires, "
                "soumise à validation technique HeliAntha et, si nécessaire, à une visite du site."
            ),
        }

    def _phase3_enrich(
        self,
        project: str,
        technical: CalculationResult,
        data: dict[str, Any],
        cfg: ContextView,
    ) -> CalculationResult:
        selector = ProductSelector(cfg.all_products, self.compatibility)
        bundle = self._catalog_bundle(project, technical, data, cfg, selector)
        bom = self.bom_builder.build(
            project,
            bundle["product_selections"],
            data,
            technical.final_results,
            fallback_lines=technical.selected_equipment,
        )

        technical.final_results.update(bundle["final_updates"])
        technical.selected_equipment = bom["lines"]
        technical.resolved_sources.update(bundle["resolved_sources"])
        technical.intermediate_results.update(bundle["intermediate_updates"])
        technical.intermediate_results["product_selections"] = bundle["product_selections"]
        technical.intermediate_results["compatibility"] = bundle["compatibility"]
        technical.intermediate_results["technical_configuration"] = bundle["technical_configuration"]
        technical.intermediate_results["bom"] = bom
        technical.intermediate_results["calculation_blocks"] = [
            *(technical.intermediate_results.get("calculation_blocks") or []),
            *(bundle["calculation_blocks"]),
            self._calc_block("Nomenclature retenue", [
                self._calc_item(
                    line.get("role", line.get("category", "Ligne")),
                    f"{line.get('quantity', 0)} x {line.get('model') or line.get('description') or line.get('reference') or 'A confirmer'}",
                    formula=str(line.get("price_status", "to_confirm")),
                    note=line.get("technical_reason", ""),
                )
                for line in bom["lines"][:8]
            ]),
        ]
        technical.reasoning_steps.extend(bundle["reasoning_steps"])
        technical.warnings = self._dedupe_warnings(technical.warnings + bundle["warnings"] + (bom.get("warnings") or []))
        if bundle["reliability_adjustments"]:
            technical.reliability = self._apply_reliability_adjustments(
                technical.reliability,
                bundle["reliability_adjustments"],
            )
        return technical

    def _catalog_bundle(
        self,
        project: str,
        technical: CalculationResult,
        data: dict[str, Any],
        cfg: ContextView,
        selector: ProductSelector,
    ) -> dict[str, Any]:
        final = technical.final_results
        selections: dict[str, dict[str, Any]] = {}
        warnings_list: list[dict[str, Any]] = []
        resolved_sources: dict[str, dict[str, Any]] = {}
        reliability_adjustments: list[tuple[str, int, str] | None] = []
        calculation_blocks: list[dict[str, Any]] = []
        reasoning_steps: list[dict[str, Any]] = []
        technical_configuration = {"sections": []}
        final_updates: dict[str, Any] = {}
        intermediate_updates: dict[str, Any] = {}
        compat_items: dict[str, Any] = {}

        def maybe_support(component: str, category: str, reason: str, quantity: float = 1, tokens: tuple[str, ...] = ()) -> None:
            if selector.category_products(category, tokens):
                selection = selector.select_supporting_category(
                    component,
                    category,
                    quantity=quantity,
                    subcategory_tokens=tokens,
                    reason=reason,
                )
                if selection.get("selected_product"):
                    selections[component] = selection

        def find_exact_catalog_product(category: str, field_name: str, field_value: float, *, brand: str = "", subcategory: str = "") -> dict[str, Any] | None:
            target = float(field_value or 0)
            if target <= 0:
                return None
            candidates: list[dict[str, Any]] = []
            for product in cfg.products:
                if product.get("category") != category:
                    continue
                if int(product.get("active", 1) or 0) != 1:
                    continue
                if brand and str(product.get("brand") or "").strip().lower() != str(brand).strip().lower():
                    continue
                if subcategory and str(product.get("subcategory") or "").strip().lower() != str(subcategory).strip().lower():
                    continue
                try:
                    product_value = float(product.get(field_name) or 0)
                except (TypeError, ValueError):
                    continue
                if abs(product_value - target) <= 0.05:
                    candidates.append(deepcopy(product))
            if not candidates:
                return None
            candidates.sort(key=lambda product: (
                bool(product.get("demo")),
                not bool(product.get("preferred")),
                -int(product.get("priority") or 0),
                float(product.get("sale_price") or 0),
                str(product.get("reference") or ""),
            ))
            return candidates[0]

        def find_exact_drive_product(drive_power_kw: float, *, brand: str, phase: str) -> dict[str, Any] | None:
            target = float(drive_power_kw or 0)
            if target <= 0:
                return None
            phase_token = str(phase or "").strip().lower()
            brand_token = normalize_text(brand)
            candidates: list[dict[str, Any]] = []
            for product in cfg.products:
                if product.get("category") != "drives":
                    continue
                if int(product.get("active", 1) or 0) != 1:
                    continue
                if brand_token and normalize_text(product.get("brand")) != brand_token:
                    continue
                product_phase = normalize_text(spec_value(product, "phases", "phase"))
                if phase_token and product_phase != phase_token:
                    continue
                product_power = as_float(spec_value(product, "power_kw", "rated_power_kw"))
                if product_power is None:
                    continue
                if abs(product_power - target) <= 0.05:
                    candidates.append(deepcopy(product))
            if not candidates:
                return None
            candidates.sort(key=lambda product: (
                bool(product.get("demo")),
                not bool(product.get("preferred")),
                -int(product.get("priority") or 0),
                float(product.get("sale_price") or 0),
                str(product.get("reference") or ""),
            ))
            return candidates[0]

        def build_rule_selection(
            component: str,
            *,
            category: str,
            quantity: float,
            unit_price_ht: float | None,
            reference: str,
            brand: str,
            model: str,
            description: str,
            role: str,
            financial_category: str,
            vat_rate: float | None,
            source_reference: str,
            source_name: str,
            technical_specs: dict[str, Any] | None = None,
            price_status: str | None = None,
            source_type: str = "heliantha",
            selected_product: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            return self._manual_rule_selection(
                component,
                category=category,
                quantity=quantity,
                unit_price_ht=unit_price_ht,
                reference=reference,
                brand=brand,
                model=model,
                description=description,
                role=role,
                financial_category=financial_category,
                vat_rate=vat_rate,
                source_reference=source_reference,
                source_name=source_name,
                technical_specs=technical_specs or {},
                source_type=source_type,
                price_status=price_status,
                status="compatible",
                selection_score=100,
                reasons=[description],
                selected_product=selected_product,
            )

        if project == "ongrid":
            roof_area = float(final.get("roof_area_m2") or 0) or None
            panel_selection = selector.select_panel(float(final.get("pv_target_kwp") or final.get("pv_power_kwp") or 0), roof_area_m2=roof_area)
            selections["panel"] = panel_selection
            panel_product = panel_selection.get("selected_product") or cfg.panel()
            panel_power_source = cfg.product_value_or_parameter(
                panel_product,
                "power_w",
                "pv_panel_default_w",
                float(final.get("panel_power_w") or cfg.p("pv_panel_default_w", 590)),
            )
            panels = int(panel_selection.get("quantity") or final.get("panels") or 0)
            installed_kwp = panels * panel_power_source["value"] / WATTS_PER_KILOWATT if panels else float(final.get("pv_power_kwp") or 0)
            resolved_sources["pv_panel_default_w"] = self._resolved_source(
                "Puissance panneau utilisee",
                panel_power_source,
                display_kind="power_w",
                key="pv_panel_default_w",
                category="Photovoltaique",
                role="Produit ou valeur de secours",
            )
            final_updates.update({
                "panel_power_w": panel_power_source["value"],
                "panels": panels or final.get("panels"),
                "panel_count_theoretical": float(final.get("pv_target_kwp") or 0) * WATTS_PER_KILOWATT / max(panel_power_source["value"], 1),
                "pv_power_kwp": installed_kwp or final.get("pv_power_kwp"),
                "installed_power_kwp": installed_kwp or final.get("pv_power_kwp"),
            })
            inverter_selection = selector.select_inverter(
                (installed_kwp or float(final.get("pv_power_kwp") or 0)) / max(cfg.p("pv_dc_ac_ratio_max", 1.30), 0.1),
                project=project,
                installed_pv_kwp=installed_kwp or float(final.get("pv_power_kwp") or 0),
                panel=panel_product if panel_selection.get("selected_product") else None,
                panel_count=panels or None,
                dc_ac_ratio_min=cfg.p("pv_dc_ac_ratio_min", 0.80),
                dc_ac_ratio_max=cfg.p("pv_dc_ac_ratio_max", 1.30),
            )
            selections["inverter"] = inverter_selection
            inverter_product = inverter_selection.get("selected_product")
            final_updates["inverter_selected_kw"] = float((inverter_product or {}).get("power_kw") or (inverter_product or {}).get("rated_power_kw") or final.get("inverter_selected_kw") or 0)
            maybe_support("structure", "structures", "Support des modules photovoltaiques.", quantity=max(1, panels))
            maybe_support("protection_dc", "protections", "Protection DC du champ photovoltaique.", tokens=("dc",))
            maybe_support("protection_ac", "protections", "Protection AC du tableau et de l'onduleur.", tokens=("ac",))
            maybe_support("cable_dc", "cables", "Cable DC photovoltaique de liaison.")
            compat_items["panel_inverter"] = inverter_selection.get("compatibility") or {}
            technical_configuration["sections"].append({
                "title": "Configuration photovoltaique retenue",
                "items": [
                    {"label": "Panneau retenu", "value": self._product_label(panel_product), "details": "; ".join(panel_selection.get("reasons") or [])},
                    {"label": "Onduleur retenu", "value": self._product_label(inverter_product), "details": "; ".join(inverter_selection.get("reasons") or [])},
                ],
            })
            calculation_blocks.append(self._calc_block("Selection catalogue", [
                self._calc_item("Panneau retenu", self._product_label(panel_product), formula=f"Score {panel_selection.get('selection_score', 0)}/100", note=" ; ".join(panel_selection.get("reasons", [])[:2])),
                self._calc_item("Onduleur retenu", self._product_label(inverter_product), formula=f"Score {inverter_selection.get('selection_score', 0)}/100", note=" ; ".join(inverter_selection.get("reasons", [])[:2])),
            ]))

        elif project in {"offgrid", "hybrid"}:
            daily = float(final.get("energy_reference_kwh_day") or final.get("daily_consumption_kwh") or 0)
            autonomy = float(final.get("autonomy_days") or 1)
            battery_margin = cfg.p("battery_capacity_margin", 0.10)
            battery_selection = selector.select_battery(
                daily * autonomy,
                battery_margin=battery_margin,
                fallback_dod=cfg.p("battery_dod", 0.80),
                fallback_efficiency=cfg.p("battery_efficiency", 0.93),
                required_power_kw=float(final.get("peak_load_kw") or 0),
            )
            selections["battery"] = battery_selection
            battery_product = battery_selection.get("selected_product")
            battery_qty = int(battery_selection.get("quantity") or 0)
            battery_dod_source = cfg.product_value_or_parameter(
                battery_product,
                ("depth_of_discharge", "dod_percent", "battery_dod"),
                "battery_dod",
                cfg.p("battery_dod", 0.80),
            )
            battery_eff_source = cfg.product_value_or_parameter(
                battery_product,
                ("round_trip_efficiency", "efficiency_percent", "efficiency"),
                "battery_efficiency",
                cfg.p("battery_efficiency", 0.93),
            )
            battery_theoretical = daily * autonomy / max(battery_dod_source["value"] * battery_eff_source["value"], 0.1)
            battery_target = battery_theoretical * (1 + battery_margin)
            battery_unit = float((battery_product or {}).get("capacity_kwh") or 0)
            final_updates.update({
                "battery_dod": battery_dod_source["value"],
                "battery_efficiency": battery_eff_source["value"],
                "battery_theoretical_kwh": battery_theoretical,
                "battery_target_kwh": battery_target,
                "battery_commercial_kwh": (battery_qty * battery_unit) or final.get("battery_commercial_kwh"),
                "battery_configuration": (
                    f"{battery_qty} module(s) x {battery_unit:.2f} kWh"
                    if battery_qty and battery_unit else final.get("battery_configuration", "A confirmer")
                ),
            })
            resolved_sources["battery_dod"] = self._resolved_source(
                "Part utilisable batterie utilisee",
                battery_dod_source,
                display_kind="percent",
                key="battery_dod",
                category="Batteries",
                role="Produit ou valeur de secours",
            )
            resolved_sources["battery_efficiency"] = self._resolved_source(
                "Rendement batterie utilise",
                battery_eff_source,
                display_kind="percent",
                key="battery_efficiency",
                category="Batteries",
                role="Produit ou valeur de secours",
            )

            panel_selection = selector.select_panel(float(final.get("pv_target_kwp") or final.get("pv_power_kwp") or 0))
            selections["panel"] = panel_selection
            panel_product = panel_selection.get("selected_product") or cfg.panel()
            panel_power_source = cfg.product_value_or_parameter(
                panel_product,
                "power_w",
                "pv_panel_default_w",
                float(final.get("panel_power_w") or cfg.p("pv_panel_default_w", 590)),
            )
            panels = int(panel_selection.get("quantity") or final.get("panels") or 0)
            installed_kwp = panels * panel_power_source["value"] / WATTS_PER_KILOWATT if panels else float(final.get("pv_power_kwp") or 0)
            final_updates.update({
                "panel_power_w": panel_power_source["value"],
                "panels": panels or final.get("panels"),
                "panel_count_theoretical": float(final.get("pv_target_kwp") or 0) * WATTS_PER_KILOWATT / max(panel_power_source["value"], 1),
                "pv_power_kwp": installed_kwp or final.get("pv_power_kwp"),
                "installed_power_kwp": installed_kwp or final.get("pv_power_kwp"),
            })
            resolved_sources["pv_panel_default_w"] = self._resolved_source(
                "Puissance panneau utilisee",
                panel_power_source,
                display_kind="power_w",
                key="pv_panel_default_w",
                category="Photovoltaique",
                role="Produit ou valeur de secours",
            )
            inverter_selection = selector.select_inverter(
                float(final.get("inverter_calculated_kw") or final.get("inverter_selected_kw") or 0),
                project=project,
                installed_pv_kwp=installed_kwp or float(final.get("pv_power_kwp") or 0),
                panel=panel_product if panel_selection.get("selected_product") else None,
                panel_count=panels or None,
                battery=battery_product,
                battery_quantity=max(1, battery_qty),
                required_battery_power_kw=float(final.get("peak_load_kw") or 0),
                dc_ac_ratio_min=cfg.p("pv_dc_ac_ratio_min", 0.80),
                dc_ac_ratio_max=cfg.p("pv_dc_ac_ratio_max", 1.30),
            )
            selections["inverter"] = inverter_selection
            inverter_product = inverter_selection.get("selected_product")
            final_updates["inverter_selected_kw"] = float((inverter_product or {}).get("power_kw") or (inverter_product or {}).get("rated_power_kw") or final.get("inverter_selected_kw") or 0)
            maybe_support("structure", "structures", "Support des modules photovoltaiques.", quantity=max(1, panels))
            maybe_support("protection_dc", "protections", "Protection DC du champ photovoltaique.", tokens=("dc",))
            maybe_support("protection_ac", "protections", "Protection AC du tableau et de l'onduleur.", tokens=("ac",))
            maybe_support("cable_dc", "cables", "Cable DC photovoltaique de liaison.")
            maybe_support("cable_battery", "cables", "Cable batterie / onduleur.")
            compat_items["battery_inverter"] = inverter_selection.get("compatibility") or {}
            technical_configuration["sections"].append({
                "title": "Configuration electrique retenue",
                "items": [
                    {"label": "Panneau retenu", "value": self._product_label(panel_product), "details": "; ".join(panel_selection.get("reasons") or [])},
                    {"label": "Batterie retenue", "value": self._product_label(battery_product), "details": "; ".join(battery_selection.get("reasons") or [])},
                    {"label": "Onduleur retenu", "value": self._product_label(inverter_product), "details": "; ".join(inverter_selection.get("reasons") or [])},
                ],
            })
            calculation_blocks.append(self._calc_block("Selection catalogue", [
                self._calc_item("Panneau retenu", self._product_label(panel_product), formula=f"Score {panel_selection.get('selection_score', 0)}/100", note=" ; ".join(panel_selection.get("reasons", [])[:2])),
                self._calc_item("Batterie retenue", self._product_label(battery_product), formula=f"Score {battery_selection.get('selection_score', 0)}/100", note=" ; ".join(battery_selection.get("reasons", [])[:2])),
                self._calc_item("Onduleur retenu", self._product_label(inverter_product), formula=f"Score {inverter_selection.get('selection_score', 0)}/100", note=" ; ".join(inverter_selection.get("reasons", [])[:2])),
            ]))

        elif project == "pumping":
            pump_rule_key = final.get("pumping_rule_key")
            if pump_rule_key:
                pump_cv = float(final.get("existing_pump_cv") or final.get("pump_power_cv") or 0)
                panels = int(float(final.get("panels") or 0))
                panel_power_w = float(final.get("panel_power_w") or cfg.p("pv_panel_default_w", 590))
                drive_power_kw = float(final.get("solar_drive_kw") or final.get("drive_power_kw") or 0)
                phase = str(final.get("phase") or "").strip().lower()
                drive_brand = str(final.get("drive_brand") or "").strip() or "HeliAntha"
                panel_vat_rate = float(final.get("rule_panel_vat_rate") or 0.10)
                other_vat_rate = float(final.get("rule_other_vat_rate") or 0.20)

                exact_panel = find_exact_catalog_product("panels", "power_w", panel_power_w)
                if not exact_panel:
                    raise ValidationError("Produit catalogue exact introuvable")
                panel_unit_price = float(exact_panel.get("sale_price") or 0)
                panel_price_status = "catalog_price"
                panel_selection = build_rule_selection(
                    "panel",
                    category="panels",
                    quantity=panels,
                    unit_price_ht=panel_unit_price,
                    reference=str(exact_panel.get("reference") or pump_rule_key),
                    brand=str(exact_panel.get("brand") or ""),
                    model=str(exact_panel.get("model") or ""),
                    description=str(exact_panel.get("description") or "Panneau photovoltaique catalogue."),
                    role="Panneau photovoltaïque",
                    financial_category="principal_equipment",
                    vat_rate=panel_vat_rate,
                    source_reference=str(exact_panel.get("reference") or pump_rule_key),
                    source_name=" ".join(part for part in (str(exact_panel.get("brand") or "").strip(), str(exact_panel.get("model") or "").strip()) if part).strip(),
                    technical_specs=deepcopy(exact_panel.get("technical_specs") or {}),
                    price_status=panel_price_status,
                    source_type="catalog",
                    selected_product=exact_panel,
                )
                selections["panel"] = panel_selection
                panel_product = panel_selection.get("selected_product")
                panel_power_source = {
                    "key": "pumping_rule_panel_power",
                    "value": panel_power_w,
                    "display_kind": "power_w",
                    "unit": "W",
                    "source_type": "heliantha",
                    "source_name": "Règle HeliAntha",
                    "source_reference": pump_rule_key,
                }
                installed_kwp = panels * panel_power_w / WATTS_PER_KILOWATT if panels else 0
                final_updates.update({
                    "panel_power_w": panel_power_w,
                    "panels": panels or final.get("panels"),
                    "pv_power_kwp": installed_kwp or final.get("pv_power_kwp"),
                    "installed_power_kwp": installed_kwp or final.get("pv_power_kwp"),
                })
                final.update(final_updates)
                resolved_sources["pv_panel_default_w"] = self._resolved_source(
                    "Puissance panneau utilisée",
                    panel_power_source,
                    display_kind="power_w",
                    key="pv_panel_default_w",
                    category="Photovoltaique",
                    role="Règle HeliAntha",
                )

                exact_drive = find_exact_drive_product(drive_power_kw, brand=drive_brand, phase=phase)
                if not exact_drive:
                    raise ValidationError("Produit catalogue exact introuvable")
                drive_unit_price = float(exact_drive.get("sale_price") or 0)
                drive_selection = build_rule_selection(
                    "pump_drive",
                    category="drives",
                    quantity=1,
                    unit_price_ht=drive_unit_price,
                    reference=str(exact_drive.get("reference") or ""),
                    brand=str(exact_drive.get("brand") or ""),
                    model=str(exact_drive.get("model") or ""),
                    description=str(exact_drive.get("description") or f"Variateur solaire {format_phase(phase)} {drive_brand}"),
                    role="Variateur de pompage",
                    financial_category="principal_equipment",
                    vat_rate=other_vat_rate,
                    source_reference=str(exact_drive.get("reference") or pump_rule_key),
                    source_name=" ".join(part for part in (str(exact_drive.get("brand") or "").strip(), str(exact_drive.get("model") or "").strip()) if part).strip(),
                    technical_specs=deepcopy(exact_drive.get("technical_specs") or {}),
                    price_status="catalog_price",
                    source_type="catalog",
                    selected_product=exact_drive,
                )
                selections["pump_drive"] = drive_selection
                drive_product = drive_selection.get("selected_product")
                resolved_sources["pumping_drive_power_kw"] = self._resolved_source(
                    "Puissance variateur retenue",
                    {
                        "key": "pumping_rule_drive_power",
                        "value": drive_power_kw,
                        "display_kind": "power_kw",
                        "unit": "kW",
                        "source_type": "heliantha",
                        "source_name": "Règle HeliAntha",
                        "source_reference": str(exact_drive.get("reference") or pump_rule_key),
                    },
                    display_kind="power_kw",
                    unit="kW",
                    key="pumping_rule_drive_power",
                    category="Pompage",
                    role="Règle HeliAntha",
                )

                structure_rule = cfg.pumping_rule("structure_pricing", panel_power_w=panel_power_w) or {}
                structure_unit_price = float(structure_rule.get("unit_price_ht") or 0)
                structure_selection = build_rule_selection(
                    "structure",
                    category="structures",
                    quantity=panels or 1,
                    unit_price_ht=structure_unit_price,
                    reference=str(structure_rule.get("rule_key") or f"STR-{int(round(panel_power_w))}"),
                    brand="HeliAntha Structure",
                    model=f"{panel_power_w:.0f} Wc",
                    description=f"Structure pour panneau {panel_power_w:.0f} W.",
                    role="Structure photovoltaïque",
                    financial_category="structure",
                    vat_rate=other_vat_rate,
                    source_reference=str(structure_rule.get("rule_key") or pump_rule_key),
                    source_name=str(structure_rule.get("source_name") or "HeliAntha"),
                    technical_specs={"panel_power_w": panel_power_w, "rule_key": pump_rule_key},
                    price_status="rule_price" if structure_unit_price > 0 else "to_confirm",
                )
                selections["structure"] = structure_selection
                resolved_sources["pumping_structure_price"] = self._resolved_source(
                    "Tarif structure retenu",
                    {
                        "key": "pumping_rule_structure_price",
                        "value": structure_unit_price,
                        "display_kind": "money",
                        "unit": "DH",
                        "source_type": "heliantha",
                        "source_name": "Règle HeliAntha",
                        "source_reference": str(structure_rule.get("rule_key") or pump_rule_key),
                    },
                    display_kind="money",
                    unit="DH",
                    key="pumping_rule_structure_price",
                    category="Structures",
                    role="Règle HeliAntha",
                )

                coffret_rule = self._pumping_range_rule(cfg.pumping_rule_rows("coffret_pricing"), pump_cv, phase=phase) or {}
                coffret_unit_price = float(coffret_rule.get("unit_price_ht") or 0)
                coffret_selection = build_rule_selection(
                    "coffret",
                    category="protections",
                    quantity=1,
                    unit_price_ht=coffret_unit_price,
                    reference=str(coffret_rule.get("rule_key") or f"COF-{int(round(pump_cv))}"),
                    brand="HeliAntha",
                    model=format_phase(phase),
                    description=f"Coffret de protection {format_phase(phase)}.",
                    role="Coffret de protection",
                    financial_category="protections",
                    vat_rate=other_vat_rate,
                    source_reference=str(coffret_rule.get("rule_key") or pump_rule_key),
                    source_name=str(coffret_rule.get("source_name") or "HeliAntha"),
                    technical_specs={"pump_cv": pump_cv, "phase": phase, "rule_key": pump_rule_key},
                    price_status="rule_price" if coffret_unit_price > 0 else "to_confirm",
                )
                selections["coffret"] = coffret_selection
                resolved_sources["pumping_coffret_price"] = self._resolved_source(
                    "Prix coffret retenu",
                    {
                        "key": "pumping_rule_coffret_price",
                        "value": coffret_unit_price,
                        "display_kind": "money",
                        "unit": "DH",
                        "source_type": "heliantha",
                        "source_name": "Règle HeliAntha",
                        "source_reference": str(coffret_rule.get("rule_key") or pump_rule_key),
                    },
                    display_kind="money",
                    unit="DH",
                    key="pumping_rule_coffret_price",
                    category="Protections",
                    role="Règle HeliAntha",
                )

                cabling_rule = cfg.pumping_rule("cabling_pricing") or {}
                cabling_unit_price = float(cabling_rule.get("unit_price_ht") or 0)
                cabling_selection = build_rule_selection(
                    "cabling_accessories",
                    category="cables",
                    quantity=panels or 1,
                    unit_price_ht=cabling_unit_price,
                    reference=str(cabling_rule.get("rule_key") or "CABLING"),
                    brand="HeliAntha",
                    model=f"{panels} panneaux" if panels else "Câblage",
                    description="Câblage DC et accessoires par panneau.",
                    role="Câblage DC et accessoires",
                    financial_category="cabling",
                    vat_rate=other_vat_rate,
                    source_reference=str(cabling_rule.get("rule_key") or pump_rule_key),
                    source_name=str(cabling_rule.get("source_name") or "HeliAntha"),
                    technical_specs={"panel_count": panels, "rule_key": pump_rule_key},
                    price_status="rule_price" if cabling_unit_price > 0 else "to_confirm",
                )
                selections["cabling_accessories"] = cabling_selection
                resolved_sources["pumping_cabling_price"] = self._resolved_source(
                    "Prix câblage retenu",
                    {
                        "key": "pumping_rule_cabling_price",
                        "value": cabling_unit_price,
                        "display_kind": "money",
                        "unit": "DH",
                        "source_type": "heliantha",
                        "source_name": "Règle HeliAntha",
                        "source_reference": str(cabling_rule.get("rule_key") or pump_rule_key),
                    },
                    display_kind="money",
                    unit="DH",
                    key="pumping_rule_cabling_price",
                    category="Câblage",
                    role="Règle HeliAntha",
                )

                installation_rule = self._pumping_range_rule(cfg.pumping_rule_rows("installation_pricing"), pump_cv, phase=phase) or {}
                installation_unit_price = float(installation_rule.get("unit_price_ht") or 0)
                installation_mode = str(installation_rule.get("pricing_mode") or "")
                installation_quantity = 1 if installation_mode == "fixed" else max(panels, 1)
                installation_description = (
                    "Forfait installation et mise en service."
                    if installation_mode == "fixed"
                    else "Installation et mise en service par panneau."
                )
                installation_selection = build_rule_selection(
                    "installation",
                    category="installation",
                    quantity=installation_quantity,
                    unit_price_ht=installation_unit_price,
                    reference=str(installation_rule.get("rule_key") or f"INS-{int(round(pump_cv))}"),
                    brand="HeliAntha",
                    model=format_pricing_mode(installation_mode),
                    description=installation_description,
                    role="Installation et mise en service",
                    financial_category="installation",
                    vat_rate=other_vat_rate,
                    source_reference=str(installation_rule.get("rule_key") or pump_rule_key),
                    source_name=str(installation_rule.get("source_name") or "HeliAntha"),
                    technical_specs={"pump_cv": pump_cv, "panel_count": panels, "pricing_mode": installation_mode, "rule_key": pump_rule_key},
                    price_status="rule_price" if installation_unit_price > 0 else "to_confirm",
                )
                selections["installation"] = installation_selection
                resolved_sources["pumping_installation_price"] = self._resolved_source(
                    "Prix installation retenu",
                    {
                        "key": "pumping_rule_installation_price",
                        "value": installation_unit_price,
                        "display_kind": "money",
                        "unit": "DH",
                        "source_type": "heliantha",
                        "source_name": "Règle HeliAntha",
                        "source_reference": str(installation_rule.get("rule_key") or pump_rule_key),
                    },
                    display_kind="money",
                    unit="DH",
                    key="pumping_rule_installation_price",
                    category="Installation",
                    role="Règle HeliAntha",
                )

                resolved_sources["pump_power_cv"] = self._resolved_source(
                    "Puissance pompe existante",
                    {
                        "key": "existing_pump_cv",
                        "value": pump_cv,
                        "display_kind": "cv",
                        "unit": "CV",
                        "source_type": "heliantha",
                        "source_name": "Donnée client",
                        "source_reference": "existing_pump_cv",
                    },
                    display_kind="cv",
                    unit="CV",
                    key="existing_pump_cv",
                    category="Pompage",
                    role="Donnée client",
                )
                pump_energy_kw = float(final.get("pump_power_kw") or round(pump_cv * 0.7355, 2) or 0)
                final_updates.update({
                    "pump_power_kw": pump_energy_kw,
                    "pump_power_cv": pump_cv,
                    "existing_pump_cv": pump_cv,
                    "pumping_rule_key": pump_rule_key,
                    "pumping_rule_title": final.get("pumping_rule_title") or pump_rule_key,
                    "drive_brand": drive_brand,
                    "phase": phase,
                    "solar_drive_kw": drive_power_kw,
                    "rule_panel_vat_rate": panel_vat_rate,
                    "rule_other_vat_rate": other_vat_rate,
                })
                final.update(final_updates)

                technical_configuration["sections"].append({
                    "title": "Configuration pompage retenue",
                    "items": [
                        {"label": "Pompe", "value": f"{pump_cv:.1f} CV", "details": "Pompe déjà installée chez le client."},
                        {"label": "Panneaux", "value": f"{panels} × {panel_power_w:.0f} W", "details": "Règle HeliAntha appliquée."},
                        {"label": "Variateur", "value": f"{drive_power_kw:g} kW", "details": f"{format_phase(phase)} · {drive_brand}"},
                        {"label": "Structure", "value": f"{panels} × {float(structure_unit_price):.0f} DH", "details": "Tarif par panneau."},
                        {"label": "Coffret", "value": f"{float(coffret_unit_price):.0f} DH HT", "details": "Seuil pompage HeliAntha."},
                        {"label": "Câblage", "value": f"{panels} × {float(cabling_unit_price):.0f} DH", "details": "Tarif par panneau."},
                        {"label": "Installation", "value": f"{float(installation_unit_price):.0f} DH HT" if installation_mode == "fixed" else f"{panels} × {float(installation_unit_price):.0f} DH", "details": format_pricing_mode(installation_mode)},
                        {"label": "TVA panneaux", "value": format_percent(panel_vat_rate), "details": "Appliquee aux panneaux uniquement."},
                        {"label": "TVA autres", "value": format_percent(other_vat_rate), "details": "Appliquee aux autres postes."},
                    ],
                })
                calculation_blocks.append(self._calc_block("Règle HeliAntha appliquée", [
                    self._calc_item("Pompe existante", pump_cv, "CV", decimals=1, formula=f"Pompe renseignée = {self._format_decimal(pump_cv, 1)} CV", source=resolved_sources["pump_power_cv"]),
                    self._calc_item("Panneaux retenus", panels, "panneaux", decimals=0, formula=f"Configuration HeliAntha = {panels} panneaux"),
                    self._calc_item("Puissance panneau", panel_power_w, "W", decimals=0, formula=f"Règle HeliAntha = {self._format_decimal(panel_power_w, 0)} W", source=resolved_sources["pv_panel_default_w"]),
                    self._calc_item("Variateur retenu", drive_power_kw, "kW", formula=f"Règle HeliAntha = {self._format_decimal(drive_power_kw)} kW", source=resolved_sources["pumping_drive_power_kw"]),
                ]))
                calculation_blocks.append(self._calc_block("Configuration tarifaire", [
                    self._calc_item("Structure", structure_unit_price, "DH / panneau", formula=f"{panels} × {self._format_decimal(structure_unit_price, 0)} DH"),
                    self._calc_item("Coffret", coffret_unit_price, "DH HT", formula=f"Tranche pompe = {format_phase(phase)}"),
                    self._calc_item("Câblage et accessoires", cabling_unit_price, "DH / panneau", formula=f"{panels} × {self._format_decimal(cabling_unit_price, 0)} DH"),
                    self._calc_item("Installation", installation_unit_price, "DH HT", formula=f"{format_pricing_mode(installation_mode)}"),
                    self._calc_item("TVA panneaux", panel_vat_rate, "%", decimals=0, formula=f"{format_percent(panel_vat_rate)} sur les panneaux"),
                    self._calc_item("TVA autres", other_vat_rate, "%", decimals=0, formula=f"{format_percent(other_vat_rate)} sur les autres postes"),
                ]))
                compat_items["configuration"] = {
                    "status": "compatible",
                    "checks": [{"status": "passed", "message": "Configuration HeliAntha appliquée."}],
                    "warnings": [],
                    "details": {},
                }
                reliability = self._apply_reliability_adjustments(
                    self._reliability("pumping", data, [("water_need", 16), ("hours", 10), ("city", 10)]),
                    [("Règle HeliAntha", 2, "passed"), ("Catalogue vérifié", 0, "ok")],
                )
                intermediate_updates["catalogue_selection_completed"] = True
                intermediate_updates["catalogue_status"] = "compatible"
                intermediate_updates["pumping_rule_key"] = pump_rule_key
                intermediate_updates["pumping_rule_title"] = final.get("pumping_rule_title") or pump_rule_key
                intermediate_updates["catalogue_reliability_score"] = reliability["score"]

            if not pump_rule_key:
                pump_selection = selector.select_pump(
                    float(final.get("pump_power_kw") or 0),
                    flow_m3_h=as_float(final.get("flow_m3_h")),
                    hmt_m=as_float(final.get("hmt_m")),
                )
                selections["pump"] = pump_selection
                pump_product = pump_selection.get("selected_product")
                drive_selection = selector.select_pump_drive(pump_product, float(final.get("pump_power_kw") or 0))
                selections["pump_drive"] = drive_selection
                drive_product = drive_selection.get("selected_product")
                pump_eff_source = cfg.product_value_or_parameter(
                    pump_product,
                    ("pump_efficiency", "efficiency_percent", "efficiency"),
                    "pump_efficiency",
                    cfg.p("pump_efficiency", 0.48),
                )
                drive_eff_source = cfg.product_value_or_parameter(
                    drive_product,
                    ("drive_efficiency", "efficiency"),
                    "pump_drive_efficiency",
                    cfg.p("pump_drive_efficiency", 0.95),
                )
                resolved_sources["pump_efficiency"] = self._resolved_source(
                    "Rendement pompe utilise",
                    pump_eff_source,
                    display_kind="percent",
                    key="pump_efficiency",
                    category="Pompage",
                    role="Produit ou valeur de secours",
                )
                resolved_sources["pump_drive_efficiency"] = self._resolved_source(
                    "Rendement variateur utilise",
                    drive_eff_source,
                    display_kind="percent",
                    key="pump_drive_efficiency",
                    category="Pompage",
                    role="Produit ou valeur de secours",
                )
                panel_selection = selector.select_panel(float(final.get("pv_target_kwp") or final.get("pv_power_kwp") or 0))
                selections["panel"] = panel_selection
                panel_product = panel_selection.get("selected_product") or cfg.panel()
                panel_power_source = cfg.product_value_or_parameter(
                    panel_product,
                    "power_w",
                    "pv_panel_default_w",
                    float(final.get("panel_power_w") or cfg.p("pv_panel_default_w", 590)),
                )
                panels = int(panel_selection.get("quantity") or final.get("panels") or 0)
                installed_kwp = panels * panel_power_source["value"] / WATTS_PER_KILOWATT if panels else float(final.get("pv_power_kwp") or 0)
                final_updates.update({
                    "panel_power_w": panel_power_source["value"],
                    "panels": panels or final.get("panels"),
                    "pv_power_kwp": installed_kwp or final.get("pv_power_kwp"),
                    "installed_power_kwp": installed_kwp or final.get("pv_power_kwp"),
                })
                resolved_sources["pv_panel_default_w"] = self._resolved_source(
                    "Puissance panneau utilisee",
                    panel_power_source,
                    display_kind="power_w",
                    key="pv_panel_default_w",
                    category="Photovoltaique",
                    role="Produit ou valeur de secours",
                )
                maybe_support("protection_dc", "protections", "Protection DC du champ photovoltaique.", tokens=("dc",))
                maybe_support("protection_motor", "protections", "Protection moteur et variateur.")
                maybe_support("cable_dc", "cables", "Cable DC photovoltaique de liaison.")
                maybe_support("cable_motor", "cables", "Cable moteur / variateur.")
                maybe_support("structure", "structures", "Support des modules photovoltaiques.", quantity=max(1, panels))
                compat_items["pump_drive"] = drive_selection.get("compatibility") or {}
                technical_configuration["sections"].append({
                    "title": "Configuration pompage retenue",
                    "items": [
                        {"label": "Pompe retenue", "value": self._product_label(pump_product), "details": "; ".join(pump_selection.get("reasons") or [])},
                        {"label": "Variateur retenu", "value": self._product_label(drive_product), "details": "; ".join(drive_selection.get("reasons") or [])},
                        {"label": "Panneau retenu", "value": self._product_label(panel_product), "details": "; ".join(panel_selection.get("reasons") or [])},
                    ],
                })

        elif project == "ev":
            charger_selection = selector.select_ev_charger(
                float(final.get("charger_power_kw") or 0),
                available_power_kw=float(final.get("available_power_kw") or 0),
                phases=str(data.get("phases") or final.get("phases") or "").lower(),
                quantity=max(1, ceil(float(data.get("chargers") or 1))),
            )
            selections["ev_charger"] = charger_selection
            charger_product = charger_selection.get("selected_product")
            final_updates["charger_power_kw"] = float((charger_product or {}).get("power_kw") or final.get("charger_power_kw") or 0)
            maybe_support("ev_protection", "protections", "Protection dediee a la borne EV.", tokens=("ac", "ev"))
            maybe_support("ev_cable", "cables", "Cable borne EV.")
            compat_items["ev_network"] = charger_selection.get("compatibility") or {}
            technical_configuration["sections"].append({
                "title": "Configuration borne EV retenue",
                "items": [
                    {"label": "Borne retenue", "value": self._product_label(charger_product), "details": "; ".join(charger_selection.get("reasons") or [])},
                ],
            })

        elif project == "thermal":
            tank_selection = selector.select_thermal_tank(float(final.get("tank_capacity_l") or 0))
            collector_selection = selector.select_thermal_collector(int(final.get("collectors") or 1))
            selections["thermal_tank"] = tank_selection
            selections["thermal_collector"] = collector_selection
            maybe_support("thermal_structure", "structures", "Support du systeme solaire thermique.")
            technical_configuration["sections"].append({
                "title": "Configuration thermique retenue",
                "items": [
                    {"label": "Ballon retenu", "value": self._product_label(tank_selection.get('selected_product')), "details": "; ".join(tank_selection.get("reasons") or [])},
                    {"label": "Capteur retenu", "value": self._product_label(collector_selection.get('selected_product')), "details": "; ".join(collector_selection.get("reasons") or [])},
                ],
            })

        for component, selection in selections.items():
            warnings_list.extend(selection.get("warnings") or [])
            reliability_adjustments.extend(self._selection_reliability_adjustments(component, selection))

        compatibility = self._compatibility_summary(compat_items)
        technical_configuration["sections"].append({
            "title": "Compatibilite catalogue",
            "items": [
                {
                    "label": key,
                    "value": self._compatibility_label(value.get("status")),
                    "details": self._compatibility_note(value),
                }
                for key, value in compat_items.items()
            ],
        })
        calculation_blocks.append(self._calc_block("Compatibilite catalogue", [
            self._calc_item(key.replace("_", " ").title(), self._compatibility_label(value.get("status")), note=self._compatibility_note(value))
            for key, value in compat_items.items()
        ]))
        intermediate_updates["catalogue_selection_completed"] = True
        intermediate_updates["catalogue_status"] = compatibility.get("status")
        return {
            "product_selections": selections,
            "warnings": warnings_list,
            "resolved_sources": resolved_sources,
            "reliability_adjustments": reliability_adjustments,
            "calculation_blocks": calculation_blocks,
            "reasoning_steps": reasoning_steps,
            "technical_configuration": technical_configuration,
            "compatibility": compatibility,
            "final_updates": final_updates,
            "intermediate_updates": intermediate_updates,
        }

    @staticmethod
    def _product_label(product: dict[str, Any] | None) -> str:
        if not product:
            return "A confirmer"
        label = " ".join(
            part for part in (str(product.get("brand") or "").strip(), str(product.get("model") or "").strip())
            if part
        ).strip()
        return label or product.get("reference") or "Produit catalogue"

    @staticmethod
    def _compatibility_label(status: str | None) -> str:
        return {
            "compatible": "Compatible",
            "compatible_with_warning": "Compatible avec reserve",
            "manual_validation_required": "Validation manuelle requise",
            "incompatible": "Incompatible",
        }.get(status or "", "A confirmer")

    @staticmethod
    def _compatibility_note(result: dict[str, Any]) -> str:
        for item in result.get("checks") or []:
            if item.get("status") in {"failed", "manual", "warning"}:
                return str(item.get("message") or "")
        if result.get("warnings"):
            return str(result["warnings"][0].get("message") or "")
        return "Verification enregistree."

    @staticmethod
    def _dedupe_warnings(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique = []
        seen = set()
        for item in warnings:
            signature = repr((
                item.get("code"),
                item.get("message"),
                item.get("value"),
                item.get("parameter"),
                item.get("recommendation"),
            ))
            if signature in seen:
                continue
            seen.add(signature)
            unique.append(item)
        return unique

    def _compatibility_summary(self, items: dict[str, Any]) -> dict[str, Any]:
        if not items:
            return {"status": "manual_validation_required", "items": {}, "warnings": []}
        order = {"compatible": 0, "compatible_with_warning": 1, "manual_validation_required": 2, "incompatible": 3}
        status = max((item.get("status") or "manual_validation_required" for item in items.values()), key=lambda value: order.get(value, 2))
        warnings_list = []
        for item in items.values():
            warnings_list.extend(item.get("warnings") or [])
        return {"status": status, "items": items, "warnings": self._dedupe_warnings(warnings_list)}

    def _selection_reliability_adjustments(
        self,
        component: str,
        selection: dict[str, Any],
    ) -> list[tuple[str, int, str] | None]:
        product = selection.get("selected_product") or {}
        label = component.replace("_", " ")
        if not product:
            return [(f"{label} sans produit catalogue", -8, "missing")]
        adjustments: list[tuple[str, int, str] | None] = []
        if selection.get("status") == "manual_validation_required":
            adjustments.append((f"{label} a valider manuellement", -4, "warning"))
        elif selection.get("status") == "compatible_with_warning":
            adjustments.append((f"{label} avec reserve", -2, "warning"))
        if product.get("demo"):
            adjustments.append((f"{label} prepare par HeliAntha", -4, "fallback"))
        stock_value = product.get("stock")
        if stock_value not in (None, "") and float(stock_value or 0) <= 0:
            adjustments.append((f"{label} stock a confirmer", -2, "warning"))
        return adjustments

    @staticmethod
    def _pumping_range_rule(rows: list[dict[str, Any]], pump_cv: float, phase: str | None = None) -> dict[str, Any] | None:
        candidates = []
        for row in rows:
            if int(row.get("active", 1) or 0) != 1:
                continue
            min_cv = float(row.get("min_cv") or 0)
            max_cv = float(row.get("max_cv") or 0)
            if pump_cv + 1e-9 < min_cv or pump_cv - 1e-9 > max_cv:
                continue
            rule_phase = str(row.get("phase") or "").strip().lower()
            if phase and rule_phase and rule_phase != str(phase).strip().lower():
                continue
            candidates.append(row)
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda row: (
                int(row.get("sort_order") or 0),
                float(row.get("min_cv") or 0),
                float(row.get("max_cv") or 0),
                str(row.get("title") or row.get("rule_key") or ""),
            ),
        )[0]

    @staticmethod
    def _manual_rule_selection(
        component: str,
        *,
        category: str,
        quantity: float,
        unit_price_ht: float | int | None,
        reference: str,
        brand: str,
        model: str,
        description: str,
        role: str,
        financial_category: str,
        vat_rate: float | int | None,
        source_reference: str = "",
        source_name: str = "HeliAntha",
        technical_specs: dict[str, Any] | None = None,
        source_type: str = "heliantha",
        price_status: str | None = None,
        status: str = "compatible",
        selection_score: int = 100,
        reasons: list[str] | None = None,
        selected_product: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        qty = float(quantity or 0)
        if qty.is_integer():
            qty = int(qty)
        if selected_product is not None:
            product = deepcopy(selected_product)
            unit_price = float(unit_price_ht if unit_price_ht is not None else product.get("sale_price") or 0)
        else:
            unit_price = float(unit_price_ht or 0)
            product = {
                "reference": reference,
                "category": category,
                "brand": brand,
                "model": model,
                "description": description,
                "sale_price": unit_price,
                "unit": "piece",
                "demo": False,
                "preferred": False,
                "priority": 0,
                "technical_specs": deepcopy(technical_specs or {}),
                "source_type": source_type,
                "source_name": source_name,
                "source_reference": source_reference,
                "_rule_generated": True,
            }
        return {
            "component": component,
            "selected_product": product,
            "quantity": qty,
            "selection_score": selection_score,
            "reasons": list(reasons or []),
            "rejected_candidates": [],
            "warnings": [],
            "compatibility": {"status": status, "checks": [], "warnings": [], "details": {}},
            "status": status,
            "metrics": {},
            "financial_category": financial_category,
            "vat_rate": vat_rate,
            "source_type": source_type,
            "source_name": source_name,
            "source_reference": source_reference,
            "price_status": price_status or ("catalog_price" if unit_price > 0 else "to_confirm"),
        }

    @staticmethod
    def _resolved_source(
        label: str,
        source: dict[str, Any],
        display_kind: str = "",
        unit: str = "",
        key: str = "",
        category: str = "",
        role: str = "",
    ) -> dict[str, Any]:
        source_type = source.get("source_type") or "demo"
        display_source_type = "heliantha" if source_type == "demo" else source_type
        source_meta = SOURCE_TYPES.get(display_source_type, SOURCE_TYPES["heliantha"])
        display_value = format_display_value({
            "value": source.get("value"),
            "display_kind": display_kind or source.get("display_kind") or "",
            "unit": unit or source.get("unit") or "",
        })
        return {
            "label": label,
            "key": key or source.get("key") or "",
            "category": category or source.get("category") or "",
            "role": role,
            "value": source.get("value"),
            "unit": unit or source.get("unit") or "",
            "display_value": display_value,
            "source_type": display_source_type,
            "source_label": source_meta["label"],
            "source_badge": source_meta["badge"],
            "source_name": source.get("source_name") or source_meta["label"],
            "source_reference": source.get("source_reference") or "",
        }

    def _constant_source(
        self,
        label: str,
        value: float,
        code_reference: str,
        display_kind: str = "",
        unit: str = "",
        role: str = "Constante scientifique",
    ) -> dict[str, Any]:
        return self._resolved_source(
            label,
            {
                "key": code_reference,
                "value": value,
                "unit": unit,
                "source_type": "physical_constant",
                "source_name": "Constante scientifique du code",
                "source_reference": code_reference,
            },
            display_kind=display_kind,
            unit=unit,
            role=role,
        )

    @staticmethod
    def _format_decimal(value: float, decimals: int = 2) -> str:
        return f"{value:.{decimals}f}"

    def _value_text(self, value: float | str, unit: str = "", decimals: int = 2) -> str:
        if isinstance(value, str):
            return value
        suffix = f" {unit}" if unit else ""
        return f"{self._format_decimal(float(value), decimals)}{suffix}"

    def _calc_item(
        self,
        label: str,
        value: float | str,
        unit: str = "",
        *,
        decimals: int = 2,
        formula: str = "",
        note: str = "",
        source: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        item = {
            "label": label,
            "value": self._value_text(value, unit, decimals),
            "formula": formula,
            "note": note,
        }
        if source:
            item["source_badge"] = source.get("source_badge") or ""
            item["source_name"] = source.get("source_name") or ""
            item["source_reference"] = source.get("source_reference") or ""
        return item

    @staticmethod
    def _calc_block(title: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        return {"title": title, "items": [item for item in items if item]}

    @staticmethod
    def _apply_reliability_adjustments(
        reliability: dict[str, Any],
        adjustments: list[tuple[str, int, str] | None],
    ) -> dict[str, Any]:
        adjusted = deepcopy(reliability)
        items = list(adjusted.get("items") or [])
        if items and items[-1].get("label") == "Score":
            items.pop()
        score = int(adjusted.get("score") or 0)
        for adjustment in adjustments:
            if not adjustment:
                continue
            label, points, status = adjustment
            items.append({"label": label, "points": points, "status": status})
            score += points
        score = max(35, min(96, score))
        items.append({"label": "Score", "points": score, "status": "total"})
        adjusted["score"] = score
        adjusted["items"] = items
        return adjusted

    def _pv_target_bundle(self, theoretical_kwp: float, panel: dict[str, Any], cfg: ContextView) -> dict[str, Any]:
        pv_margin_source = cfg.parameter_source("pv_safety_margin", 0.15)
        panel_power_source = cfg.product_value_or_parameter(panel, "power_w", "pv_panel_default_w", 590)
        panel_w = max(panel_power_source["value"], 1)
        pv_target_kwp = theoretical_kwp * (1 + pv_margin_source["value"])
        panel_count_theoretical = pv_target_kwp * WATTS_PER_KILOWATT / panel_w
        panels = max(1, ceil(panel_count_theoretical))
        installed_kwp = panels * panel_w / WATTS_PER_KILOWATT
        return {
            "pv_margin_source": pv_margin_source,
            "panel_power_source": panel_power_source,
            "panel_w": panel_w,
            "pv_target_kwp": pv_target_kwp,
            "panel_count_theoretical": panel_count_theoretical,
            "panels": panels,
            "installed_kwp": installed_kwp,
        }

    def _pumping(self, d: dict[str, Any], cfg: ContextView) -> CalculationResult:
        water = max(number(d, "water_need", 20), 1)
        hours = max(number(d, "hours", 6), 1)
        depth = number(d, "depth", number(d, "dynamic_level", 40))
        static_level = number(d, "static_level", 0)
        dynamic_level = number(d, "dynamic_level", depth)
        reservoir_height = number(d, "reservoir_height", number(d, "elevation", 10))
        distance = number(d, "distance", 30)
        city = text(d, "city")
        hydraulic_losses_source = cfg.parameter_source("pump_hydraulic_losses_rate", 0.10)
        pump_safety_source = cfg.parameter_source("pump_safety_factor", 0.20)
        psh_source = cfg.psh_source(city)
        pump_efficiency_source = cfg.parameter_source("pump_efficiency", 0.48)
        drive_efficiency_source = cfg.parameter_source("pump_drive_efficiency", 0.95)
        flow = water / hours
        base_hmt = max(dynamic_level or depth, depth) + reservoir_height
        hydraulic_losses = distance * 0.03 + base_hmt * hydraulic_losses_source["value"]
        hmt = base_hmt + hydraulic_losses
        hydraulic_kw = (flow / SECONDS_PER_HOUR) * WATER_DENSITY * GRAVITY * hmt / WATTS_PER_KILOWATT
        existing_pump_kw = number(d, "existing_pump_kw", 0)
        existing_pump_cv = normalize_pump_cv(d.get("existing_pump_cv") or d.get("pump_power_cv") or d.get("pump_cv"))
        pump_rule = cfg.pumping_rule("pump_configuration", pump_cv=existing_pump_cv) if existing_pump_cv else None
        if existing_pump_cv:
            if not pump_rule:
                raise ValidationError("Cette puissance nécessite une configuration personnalisée HeliAntha.")
            panel_count = int(float(pump_rule.get("panel_count") or 0))
            panel_power_w = float(pump_rule.get("panel_power_w") or cfg.p("pv_panel_default_w", 590))
            drive_power_kw = float(pump_rule.get("drive_power_kw") or 0)
            pump_power_kw = round(existing_pump_cv * 0.7355, 2)
            panel_kwp = panel_count * panel_power_w / WATTS_PER_KILOWATT
            panel_vat_rate = next(
                (float(row.get("vat_rate") or 0.10) for row in cfg.pumping_rule_rows("vat_pricing") if str(row.get("applies_to") or "") == "panels"),
                0.10,
            )
            other_vat_rate = next(
                (float(row.get("vat_rate") or 0.20) for row in cfg.pumping_rule_rows("vat_pricing") if str(row.get("applies_to") or "") == "others"),
                0.20,
            )
            final = {
                "pump_power_kw": pump_power_kw,
                "pump_power_cv": existing_pump_cv,
                "existing_pump_cv": existing_pump_cv,
                "pumping_rule_key": pump_rule.get("rule_key"),
                "pumping_rule_title": pump_rule.get("title"),
                "pumping_rule_source_type": pump_rule.get("source_type") or "heliantha",
                "pumping_rule_source_name": pump_rule.get("source_name") or "HeliAntha",
                "pumping_rule_source_reference": pump_rule.get("source_reference") or "",
                "pv_theoretical_kwp": panel_kwp,
                "pv_target_kwp": panel_kwp,
                "pv_power_kwp": panel_kwp,
                "panel_power_w": panel_power_w,
                "panel_count_theoretical": panel_count,
                "panels": panel_count,
                "installed_power_kwp": panel_kwp,
                "solar_drive_kw": drive_power_kw,
                "drive_brand": pump_rule.get("drive_brand") or "",
                "phase": pump_rule.get("phase") or "",
                "rule_panel_vat_rate": panel_vat_rate,
                "rule_other_vat_rate": other_vat_rate,
                "pump_rule_mode": "existing_pump_cv",
            }
            pump_vat_source = cfg.pumping_rule("vat_pricing", applies_to="panels") or {"vat_rate": panel_vat_rate}
            other_vat_source = cfg.pumping_rule("vat_pricing", applies_to="others") or {"vat_rate": other_vat_rate}
            resolved_sources = {
                "pump_power_cv": self._resolved_source(
                    "Puissance pompe existante",
                    {
                        "key": "existing_pump_cv",
                        "value": existing_pump_cv,
                        "display_kind": "cv",
                        "unit": "CV",
                        "source_type": "heliantha",
                        "source_name": "Donnée client",
                        "source_reference": "existing_pump_cv",
                    },
                    display_kind="cv",
                    unit="CV",
                    key="existing_pump_cv",
                    category="Pompage",
                    role="Donnée client",
                ),
                "pumping_rule": self._resolved_source(
                    "Règle HeliAntha de pompage",
                    {
                        "key": pump_rule.get("rule_key"),
                        "value": panel_count,
                        "display_kind": "text",
                        "unit": "",
                        "source_type": pump_rule.get("source_type") or "heliantha",
                        "source_name": pump_rule.get("source_name") or "HeliAntha",
                        "source_reference": pump_rule.get("source_reference") or pump_rule.get("rule_key"),
                    },
                    display_kind="text",
                    key=str(pump_rule.get("rule_key") or "pumping_rule"),
                    category="Pompage",
                    role="Règle HeliAntha",
                ),
                "pv_panel_default_w": self._resolved_source(
                    "Puissance panneau utilisée",
                    {
                        "key": "pumping_rule_panel_power",
                        "value": panel_power_w,
                        "display_kind": "power_w",
                        "unit": "W",
                        "source_type": "heliantha",
                        "source_name": "Règle HeliAntha",
                        "source_reference": pump_rule.get("rule_key"),
                    },
                    display_kind="power_w",
                    unit="W",
                    key="pumping_rule_panel_power",
                    category="Photovoltaique",
                    role="Règle HeliAntha",
                ),
                "pumping_drive_power_kw": self._resolved_source(
                    "Puissance variateur retenue",
                    {
                        "key": "pumping_rule_drive_power",
                        "value": drive_power_kw,
                        "display_kind": "power_kw",
                        "unit": "kW",
                        "source_type": "heliantha",
                        "source_name": "Règle HeliAntha",
                        "source_reference": pump_rule.get("rule_key"),
                    },
                    display_kind="power_kw",
                    unit="kW",
                    key="pumping_rule_drive_power",
                    category="Pompage",
                    role="Règle HeliAntha",
                ),
                "pump_rule_vat_panels": self._resolved_source(
                    "TVA panneaux pompage",
                    pump_vat_source,
                    display_kind="percent",
                    key="vat-panels",
                    category="Tarification",
                    role="Règle HeliAntha",
                ),
                "pump_rule_vat_others": self._resolved_source(
                    "TVA autres postes pompage",
                    other_vat_source,
                    display_kind="percent",
                    key="vat-others",
                    category="Tarification",
                    role="Règle HeliAntha",
                ),
            }
            metrics = [
                {"label": "Pompe existante", "value": f"{existing_pump_cv:.1f} CV"},
                {"label": "Puissance solaire", "value": f"{panel_kwp:.2f} kWc"},
                {"label": "Panneaux", "value": f"{panel_count} x {panel_power_w:.0f} W"},
                {"label": "Variateur", "value": f"{drive_power_kw:.1f} kW"},
                {"label": "Phase", "value": format_phase(pump_rule.get("phase"))},
            ]
            calculation_blocks = [
                self._calc_block("Règle HeliAntha appliquée", [
                    self._calc_item("Pompe existante", existing_pump_cv, "CV", formula=f"Pompe renseignée = {self._format_decimal(existing_pump_cv, 1)} CV", source=resolved_sources["pump_power_cv"]),
                    self._calc_item("Panneaux retenus", panel_count, "panneaux", decimals=0, formula=f"Configuration HeliAntha = {panel_count} panneaux"),
                    self._calc_item("Puissance panneau", panel_power_w, "W", decimals=0, formula=f"Règle HeliAntha = {self._format_decimal(panel_power_w, 0)} W", source=resolved_sources["pv_panel_default_w"]),
                    self._calc_item("Variateur retenu", drive_power_kw, "kW", formula=f"Règle HeliAntha = {self._format_decimal(drive_power_kw)} kW", source=resolved_sources["pumping_drive_power_kw"]),
                ]),
                self._calc_block("Configuration solaire", [
                    self._calc_item("Puissance solaire", panel_kwp, "kWp", formula=f"{panel_count} x {self._format_decimal(panel_power_w, 0)} / 1000 = {self._format_decimal(panel_kwp)} kWp"),
                    self._calc_item("Phase", format_phase(pump_rule.get("phase")), formula=f"Phase retenue = {format_phase(pump_rule.get('phase'))}"),
                    self._calc_item("Marque", str(pump_rule.get("drive_brand") or "HeliAntha"), formula=f"Marque retenue = {str(pump_rule.get('drive_brand') or 'HeliAntha')}"),
                ]),
            ]
            reliability = self._apply_reliability_adjustments(
                self._reliability("pumping", d, [("pump_existing", 8), ("existing_pump_cv", 18)]),
                [
                    ("Pompage règle HeliAntha", 2, "passed"),
                    ("Panneaux catalogue vérifiés", 0, "ok"),
                ],
            )
            return CalculationResult(
                "pumping",
                "Pompage solaire",
                f"Configuration préparée pour une pompe existante de {existing_pump_cv:g} CV.",
                dict(d),
                ["Configuration issue de la règle HeliAntha pour une pompe existante connue en CV.", "Les derniers détails techniques restent figés dans le devis."],
                {},
                {
                    "pv_energy_theoretical_kwp": panel_kwp,
                    "pv_power_theoretical_kwp": panel_kwp,
                    "pv_power_with_margin_kwp": panel_kwp,
                    "panel_count_theoretical": panel_count,
                    "pumping_rule_key": pump_rule.get("rule_key"),
                    "pumping_rule_title": pump_rule.get("title"),
                    "calculation_blocks": calculation_blocks,
                },
                [],
                final,
                [],
                CALCULATOR_VERSIONS["PumpCalculator"],
                metrics,
                reliability,
                self._steps([
                    ("Pompe existante", f"{existing_pump_cv:.1f} CV", "Puissance fournie par le client."),
                    ("Règle HeliAntha", pump_rule.get("title") or "Configuration", "Table de correspondance active."),
                    ("Panneaux retenus", f"{panel_count} x {panel_power_w:.0f} W", "Configuration solaire enregistrée."),
                    ("Variateur retenu", f"{drive_power_kw:.1f} kW", "Puissance de variateur associée."),
                    ("Phase", format_phase(pump_rule.get("phase")), "Configuration électrique."),
                ]),
                resolved_sources,
                "pumping",
            )
        pump = None
        drive = None
        for _ in range(2):
            theoretical_kw = hydraulic_kw / max(pump_efficiency_source["value"] * drive_efficiency_source["value"], 0.1)
            pump_kw = existing_pump_kw or round_up(max(theoretical_kw * (1 + pump_safety_source["value"]), 0.75), 0.5)
            pump = cfg.product("pumps", "power_kw", pump_kw)
            drive = cfg.product("drives", "power_kw", pump_kw * 1.1) or cfg.product("drives")
            pump_efficiency_source = cfg.product_value_or_parameter(
                pump,
                ("efficiency", "pump_efficiency"),
                "pump_efficiency",
                pump_efficiency_source["value"],
            )
            drive_efficiency_source = cfg.product_value_or_parameter(
                drive,
                ("efficiency", "drive_efficiency", "pump_drive_efficiency"),
                "pump_drive_efficiency",
                drive_efficiency_source["value"],
            )
        theoretical_kw = hydraulic_kw / max(pump_efficiency_source["value"] * drive_efficiency_source["value"], 0.1)
        pump_kw = existing_pump_kw or round_up(max(theoretical_kw * (1 + pump_safety_source["value"]), 0.75), 0.5)
        psh = psh_source["value"]
        pump_energy = pump_kw * hours
        pv_ratio_source = cfg.parameter_source("pv_performance_ratio", 0.80)
        pv_energy_theoretical = pump_energy / max(psh * pv_ratio_source["value"], 0.1)
        pv_base_required_kwp = max(pv_energy_theoretical, pump_kw)
        panel = cfg.panel()
        pv_bundle = self._pv_target_bundle(pv_base_required_kwp, panel, cfg)
        panel_power_source = pv_bundle["panel_power_source"]
        panel_w = pv_bundle["panel_w"]
        panels = pv_bundle["panels"]
        pv_kwp = pv_bundle["installed_kwp"]
        pv_target_kwp = pv_bundle["pv_target_kwp"]
        equipment = [self._line(panel, panels, "Champ photovoltaïque")]
        if pump and not existing_pump_kw:
            equipment.append(self._line(pump, 1, "Pompe recommandée"))
        if drive:
            equipment.append(self._line(drive, 1, "Variateur solaire"))
        warnings = []
        if existing_pump_kw:
            warnings.append(warning("PUMP_EXISTING", "info", "Le client possède déjà une pompe : le dimensionnement utilise la puissance fournie.", "existing_pump_kw", existing_pump_kw, "Vérifier la plaque signalétique avant commande."))
        if not d.get("depth") and not d.get("dynamic_level"):
            warnings.append(warning("PUMP_DEPTH_ESTIMATED", "warning", "La profondeur/niveau dynamique est estimé.", "depth", depth, "Mesurer le forage pour fiabiliser la HMT."))
        if not city:
            warnings.append(warning("CITY_MISSING", "warning", "La ville n'est pas renseignée : productible solaire par défaut utilisé.", "city", "", "Renseigner la localisation du projet."))
        elif psh_source["source_type"] != "local_data":
            warnings.append(warning("PSH_FALLBACK_USED", "warning", "Aucune donnée locale d'ensoleillement n'a été trouvée pour cette ville : la valeur de secours est utilisée.", "city", city, "Prévoir une donnée locale HeliAntha ou une mesure site."))
        if pump_efficiency_source["source_type"] != "manufacturer":
            warnings.append(warning("PUMP_EFFICIENCY_FALLBACK_USED", "warning", "Le rendement de pompe provient d'une valeur de secours et non d'une fiche produit précise.", "pump_efficiency", pump_efficiency_source["value"], "Renseigner le rendement réel de la pompe si disponible."))
        if drive_efficiency_source["source_type"] != "manufacturer":
            warnings.append(warning("DRIVE_EFFICIENCY_FALLBACK_USED", "info", "Le rendement du variateur provient d'une valeur de secours globale.", "pump_drive_efficiency", drive_efficiency_source["value"], "Renseigner le rendement réel du variateur si disponible."))
        if panel_power_source["source_type"] != "manufacturer":
            warnings.append(warning("PV_PANEL_FALLBACK_USED", "warning", "Aucun panneau catalogue précis n'a été utilisé : le calcul s'appuie sur une puissance panneau de secours.", "pv_panel_default_w", panel_power_source["value"], "Vérifier le catalogue avant validation finale."))
        if pump is None and not existing_pump_kw:
            warnings.append(warning("PUMP_CATALOG_MISSING", "critical", "Aucune pompe catalogue n'a été trouvée pour cette puissance cible.", "pump_power_kw", pump_kw, "Compléter le catalogue pompes."))
        elif pump and not existing_pump_kw and float(pump.get("power_kw") or 0) + 1e-6 < pump_kw:
            warnings.append(warning("PUMP_CATALOG_LIMIT", "warning", "La pompe catalogue disponible est inférieure à la puissance calculée.", "pump_power_kw", pump_kw, "Prévoir une pompe supérieure ou compléter le catalogue."))
        if drive is None:
            warnings.append(warning("DRIVE_CATALOG_MISSING", "warning", "Aucun variateur catalogue compatible n'a été trouvé.", "pump_power_kw", pump_kw, "Compléter le catalogue variateurs."))
        elif float(drive.get("power_kw") or 0) + 1e-6 < pump_kw:
            warnings.append(warning("DRIVE_CATALOG_LIMIT", "warning", "Le variateur catalogue disponible est inférieur à la puissance pompe calculée.", "pump_power_kw", pump_kw, "Prévoir un variateur supérieur ou compléter le catalogue."))
        if panels >= 40:
            warnings.append(warning("PV_PANEL_COUNT_HIGH", "warning", "Le nombre de panneaux retenu est élevé pour un projet de pompage.", "panels", panels, "Vérifier les hypothèses hydrauliques et le productible solaire."))
        final = {
            "water_need_m3_day": water,
            "flow_m3_h": flow,
            "static_level_m": static_level,
            "dynamic_level_m": dynamic_level,
            "reservoir_height_m": reservoir_height,
            "horizontal_distance_m": distance,
            "hydraulic_losses_m": hydraulic_losses,
            "hmt_m": hmt,
            "hydraulic_power_kw": hydraulic_kw,
            "pump_theoretical_kw": theoretical_kw,
            "pump_power_kw": pump_kw,
            "pv_energy_theoretical_kwp": pv_energy_theoretical,
            "pv_theoretical_kwp": pv_base_required_kwp,
            "pv_target_kwp": pv_target_kwp,
            "pv_power_kwp": pv_kwp,
            "pv_loss_method": "performance_ratio_only",
            "pv_performance_ratio_used": pv_ratio_source["value"],
            "pv_safety_margin_used": pv_bundle["pv_margin_source"]["value"],
            "panel_power_w": panel_w,
            "panel_count_theoretical": pv_bundle["panel_count_theoretical"],
            "panels": panels,
            "installed_power_kwp": pv_kwp,
            "solar_drive_kw": float(drive.get("power_kw") or pump_kw * 1.2) if drive else round_up(pump_kw * 1.2, 0.5),
            "protections": "Coffret DC, sectionneur, parafoudre et protection pompe à valider.",
            "cabling": "Câble solaire DC et câble pompe dimensionnés après visite.",
        }
        metrics = [
            {"label": "Besoin eau", "value": f"{water:.0f} m³/j"},
            {"label": "HMT estimée", "value": f"{hmt:.0f} m"},
            {"label": "Débit cible", "value": f"{flow:.1f} m³/h"},
            {"label": "Pompe retenue", "value": f"{pump_kw:.1f} kW"},
            {"label": "Champ PV", "value": f"{pv_kwp:.2f} kWc"},
            {"label": "Modules", "value": f"{panels} × {panel_w:.0f} W"},
        ]
        used_keys = [
            "pump_hydraulic_losses_rate",
            "pump_safety_factor",
            "pump_efficiency",
            "pump_drive_efficiency",
            "pv_performance_ratio",
            "pv_safety_margin",
        ]
        if psh_source["source_type"] != "local_data":
            used_keys.append("productible_default_psh")
        if panel_power_source["source_reference"] == "pv_panel_default_w":
            used_keys.append("pv_panel_default_w")
        resolved_sources = {
            "pump_hydraulic_losses_rate": self._resolved_source(
                "Pertes hydrauliques estimées",
                hydraulic_losses_source,
                display_kind="percent",
                key="pump_hydraulic_losses_rate",
                category="Pompage",
                role="Règle HeliAntha",
            ),
            "pump_safety_factor": self._resolved_source(
                "Marge de sécurité pompage",
                pump_safety_source,
                display_kind="percent",
                key="pump_safety_factor",
                category="Pompage",
                role="Règle HeliAntha",
            ),
            "pump_efficiency": self._resolved_source(
                "Rendement pompe utilisé",
                pump_efficiency_source,
                display_kind="percent",
                key="pump_efficiency",
                category="Pompage",
                role="Produit ou valeur de secours",
            ),
            "pump_drive_efficiency": self._resolved_source(
                "Rendement variateur utilisé",
                drive_efficiency_source,
                display_kind="percent",
                key="pump_drive_efficiency",
                category="Pompage",
                role="Produit ou valeur de secours",
            ),
            "pv_performance_ratio": self._resolved_source(
                "Performance globale photovoltaïque",
                pv_ratio_source,
                display_kind="percent",
                key="pv_performance_ratio",
                category="Photovoltaïque",
                role="Paramètre de secours",
            ),
            "pv_safety_margin": self._resolved_source(
                "Marge de dimensionnement photovoltaïque",
                pv_bundle["pv_margin_source"],
                display_kind="percent",
                key="pv_safety_margin",
                category="Photovoltaïque",
                role="Règle HeliAntha",
            ),
            "productible_default_psh": self._resolved_source(
                "Ensoleillement utilisé",
                psh_source,
                display_kind="psh",
                key="productible_default_psh",
                category="Photovoltaïque",
                role="Donnée locale ou secours",
            ),
            "pv_panel_default_w": self._resolved_source(
                "Puissance panneau utilisée",
                panel_power_source,
                display_kind="power_w",
                key="pv_panel_default_w",
                category="Photovoltaïque",
                role="Produit ou valeur de secours",
            ),
            "gravity": self._constant_source(
                "Gravité terrestre utilisée",
                GRAVITY,
                "app.constants.GRAVITY",
                display_kind="gravity",
                unit="m/s2",
            ),
            "water_density": self._constant_source(
                "Densité de l'eau utilisée",
                WATER_DENSITY,
                "app.constants.WATER_DENSITY",
                display_kind="density",
                unit="kg/m3",
            ),
        }
        reliability = self._apply_reliability_adjustments(
            self._reliability("pumping", d, [("water_need", 16), ("hours", 10), ("depth", 16), ("elevation", 10), ("distance", 8), ("city", 10)]),
            [
                ("PSH de secours", -5, "fallback") if psh_source["source_type"] != "local_data" else None,
                ("Panneau de secours", -5, "fallback") if panel_power_source["source_type"] != "manufacturer" else None,
                ("Rendement pompe de secours", -4, "fallback") if pump_efficiency_source["source_type"] != "manufacturer" else None,
            ],
        )
        calculation_blocks = [
            self._calc_block("Besoin client", [
                self._calc_item("Besoin en eau", water, "m3/j", formula=f"Besoin saisi = {self._format_decimal(water)} m3/j"),
                self._calc_item("Heures de pompage", hours, "h/j", formula=f"Pompage prévu = {self._format_decimal(hours)} h/j"),
                self._calc_item("Débit cible", flow, "m3/h", formula=f"{self._format_decimal(water)} / {self._format_decimal(hours)} = {self._format_decimal(flow)} m3/h"),
            ]),
            self._calc_block("Calcul hydraulique", [
                self._calc_item("HMT de base", base_hmt, "m", formula=f"Max niveau dynamique/profondeur + hauteur réservoir = {self._format_decimal(base_hmt)} m"),
                self._calc_item("Pertes hydrauliques", hydraulic_losses, "m", formula=f"{self._format_decimal(distance)} x 0.03 + {self._format_decimal(base_hmt)} x {self._format_decimal(hydraulic_losses_source['value'])} = {self._format_decimal(hydraulic_losses)} m", source=resolved_sources["pump_hydraulic_losses_rate"]),
                self._calc_item("HMT totale", hmt, "m", formula=f"{self._format_decimal(base_hmt)} + {self._format_decimal(hydraulic_losses)} = {self._format_decimal(hmt)} m"),
                self._calc_item("Puissance hydraulique", hydraulic_kw, "kW", formula=f"({self._format_decimal(flow)} / 3600) x 1000 x 9.81 x {self._format_decimal(hmt)} / 1000 = {self._format_decimal(hydraulic_kw)} kW"),
                self._calc_item("Puissance pompe théorique", theoretical_kw, "kW", formula=f"{self._format_decimal(hydraulic_kw)} / ({self._format_decimal(pump_efficiency_source['value'])} x {self._format_decimal(drive_efficiency_source['value'])}) = {self._format_decimal(theoretical_kw)} kW"),
                self._calc_item("Puissance pompe cible", pump_kw, "kW", formula=f"{self._format_decimal(theoretical_kw)} x {self._format_decimal(1 + pump_safety_source['value'])} = {self._format_decimal(pump_kw)} kW", source=resolved_sources["pump_safety_factor"]),
            ]),
            self._calc_block("Données locales", [
                self._calc_item("PSH utilisée", psh, "h/j", formula=f"PSH = {self._format_decimal(psh)} h/j", source=resolved_sources["productible_default_psh"]),
                self._calc_item("Performance globale PV", pv_ratio_source["value"] * 100, "%", formula=f"PR = {self._format_decimal(pv_ratio_source['value'] * 100)} %", source=resolved_sources["pv_performance_ratio"]),
                self._calc_item("Marge PV", pv_bundle["pv_margin_source"]["value"] * 100, "%", formula=f"Marge PV = {self._format_decimal(pv_bundle['pv_margin_source']['value'] * 100)} %", source=resolved_sources["pv_safety_margin"]),
                self._calc_item("Puissance panneau utilisée", panel_power_source["value"], "W", decimals=0, formula=f"Panneau = {self._format_decimal(panel_power_source['value'], 0)} W", source=resolved_sources["pv_panel_default_w"]),
            ]),
            self._calc_block("Calcul photovoltaïque", [
                self._calc_item("Énergie pompe journalière", pump_energy, "kWh/j", formula=f"{self._format_decimal(pump_kw)} x {self._format_decimal(hours)} = {self._format_decimal(pump_energy)} kWh/j"),
                self._calc_item("Puissance PV théorique énergie", pv_energy_theoretical, "kWp", formula=f"{self._format_decimal(pump_energy)} / ({self._format_decimal(psh)} x {self._format_decimal(pv_ratio_source['value'])}) = {self._format_decimal(pv_energy_theoretical)} kWp"),
                self._calc_item("Base PV retenue", pv_base_required_kwp, "kWp", formula=f"max({self._format_decimal(pv_energy_theoretical)}, {self._format_decimal(pump_kw)}) = {self._format_decimal(pv_base_required_kwp)} kWp"),
                self._calc_item("Puissance PV cible", pv_target_kwp, "kWp", formula=f"{self._format_decimal(pv_base_required_kwp)} x {self._format_decimal(1 + pv_bundle['pv_margin_source']['value'])} = {self._format_decimal(pv_target_kwp)} kWp"),
                self._calc_item("Nombre théorique de panneaux", pv_bundle["panel_count_theoretical"], "", formula=f"{self._format_decimal(pv_target_kwp * 1000)} / {self._format_decimal(panel_power_source['value'], 0)} = {self._format_decimal(pv_bundle['panel_count_theoretical'])}"),
                self._calc_item("Nombre retenu", panels, "panneaux", decimals=0, formula=f"Arrondi supérieur de {self._format_decimal(pv_bundle['panel_count_theoretical'])} = {panels}"),
                self._calc_item("Puissance installée", pv_kwp, "kWp", formula=f"{panels} x {self._format_decimal(panel_power_source['value'], 0)} / 1000 = {self._format_decimal(pv_kwp)} kWp"),
            ]),
        ]
        return CalculationResult(
            "pumping",
            "Pompage solaire",
            f"Une solution conçue pour délivrer environ {water:g} m³ d'eau par jour.",
            dict(d),
            ["Rendements et pertes hydrauliques provisoires.", "La correction globale photovoltaïque est actuellement portée par le Performance Ratio seul.", "Validation terrain nécessaire avant devis définitif."],
            cfg.used_parameters(used_keys),
            {
                "base_hmt_m": base_hmt,
                "hydraulic_losses_m": hydraulic_losses,
                "pump_energy_kwh_day": pump_energy,
                "pv_energy_theoretical_kwp": pv_energy_theoretical,
                "pv_power_theoretical_kwp": pv_base_required_kwp,
                "pv_power_with_margin_kwp": pv_target_kwp,
                "panel_count_theoretical": pv_bundle["panel_count_theoretical"],
                "calculation_blocks": calculation_blocks,
            },
            warnings,
            final,
            equipment,
            CALCULATOR_VERSIONS["PumpCalculator"],
            metrics,
            reliability,
            self._steps([
                ("Besoin journalier en eau", f"{water:.2f} m³/j", "Saisie client ou valeur provisoire."),
                ("HMT", f"{hmt:.1f} m", "Niveau dynamique + hauteur réservoir + pertes de charge."),
                ("Puissance hydraulique", f"{hydraulic_kw:.2f} kW", "ρ × g × débit × HMT."),
                ("Puissance pompe", f"{pump_kw:.2f} kW", "Puissance hydraulique / rendements + marge."),
                ("Champ PV", f"{pv_kwp:.2f} kWc", "Besoin énergie / (PSH × PR), base mini instantanée, puis marge PV."),
                ("Equipement", f"{panels} panneaux et pompe {pump_kw:.1f} kW", "Sélection catalogue actif."),
            ]),
            resolved_sources,
            "pumping",
        )

    def _offgrid(self, d: dict[str, Any], cfg: ContextView) -> CalculationResult:
        daily = max(number(d, "daily_kwh", 8), 1)
        autonomy_source = cfg.parameter_source("autonomy_default_days", 1)
        autonomy = max(number(d, "autonomy", autonomy_source["value"]), 0.25)
        peak = max(number(d, "peak_kw", daily / 5), 0.5)
        city = text(d, "city")
        battery_margin_source = cfg.parameter_source("battery_capacity_margin", 0.10)
        inverter_peak_source = cfg.parameter_source("inverter_peak_factor", 1.25)
        pv_ratio_source = cfg.parameter_source("pv_performance_ratio", 0.80)
        psh_source = cfg.psh_source(city)
        battery_product = cfg.product("batteries")
        battery_dod_source = cfg.parameter_source("battery_dod", 0.80)
        battery_efficiency_source = cfg.parameter_source("battery_efficiency", 0.93)
        for _ in range(2):
            battery_theoretical = daily * autonomy / max(
                battery_dod_source["value"] * battery_efficiency_source["value"],
                0.1,
            )
            battery_required = battery_theoretical * (1 + battery_margin_source["value"])
            battery_product = cfg.product("batteries", "capacity_kwh", min(battery_required, 10.24)) or cfg.product("batteries")
            battery_dod_source = cfg.product_value_or_parameter(
                battery_product,
                ("depth_of_discharge", "dod", "battery_dod"),
                "battery_dod",
                battery_dod_source["value"],
            )
            battery_efficiency_source = cfg.product_value_or_parameter(
                battery_product,
                ("round_trip_efficiency", "efficiency", "battery_efficiency"),
                "battery_efficiency",
                battery_efficiency_source["value"],
            )
        battery_theoretical = daily * autonomy / max(
            battery_dod_source["value"] * battery_efficiency_source["value"],
            0.1,
        )
        battery_required = battery_theoretical * (1 + battery_margin_source["value"])
        battery_product = cfg.product("batteries", "capacity_kwh", min(battery_required, 10.24)) or cfg.product("batteries")
        battery_unit = float(battery_product.get("capacity_kwh") or 5.12) if battery_product else 5.12
        battery_qty = max(1, ceil(battery_required / battery_unit))
        battery_commercial = battery_qty * battery_unit
        psh = psh_source["value"]
        pv_theoretical = daily / max(psh * pv_ratio_source["value"], 0.1)
        panel = cfg.panel()
        pv_bundle = self._pv_target_bundle(pv_theoretical, panel, cfg)
        panel_power_source = pv_bundle["panel_power_source"]
        panels = pv_bundle["panels"]
        pv_kwp = pv_bundle["installed_kwp"]
        pv_target_kwp = pv_bundle["pv_target_kwp"]
        inverter_kw = round_up(peak * inverter_peak_source["value"], 0.5)
        inverter = cfg.product("inverters", "power_kw", inverter_kw, "hybride") or cfg.product("inverters", "power_kw", inverter_kw)
        equipment = [self._line(panel, panels, "Champ photovoltaïque")]
        if battery_product:
            equipment.append(self._line(battery_product, battery_qty, "Stockage batterie"))
        if inverter:
            equipment.append(self._line(inverter, 1, "Onduleur/chargeur"))
        warnings = []
        if not d.get("daily_kwh"):
            warnings.append(warning("CONSUMPTION_ESTIMATED", "warning", "La consommation quotidienne est estimée.", "daily_kwh", daily, "Faire un relevé détaillé des appareils."))
        if not city:
            warnings.append(warning("CITY_MISSING", "warning", "La ville n'est pas renseignée : productible solaire par défaut utilisé.", "city", "", "Renseigner la localisation du projet."))
        elif psh_source["source_type"] != "local_data":
            warnings.append(warning("PSH_FALLBACK_USED", "warning", "Aucune donnée locale d'ensoleillement n'a été trouvée pour cette ville : la valeur de secours est utilisée.", "city", city, "Prévoir une donnée locale HeliAntha ou une mesure site."))
        if panel_power_source["source_type"] != "manufacturer":
            warnings.append(warning("PV_PANEL_FALLBACK_USED", "warning", "Aucun panneau catalogue précis n'a été utilisé : le calcul s'appuie sur une puissance panneau de secours.", "pv_panel_default_w", panel_power_source["value"], "Vérifier le catalogue avant validation finale."))
        if battery_dod_source["source_type"] != "manufacturer":
            warnings.append(warning("BATTERY_DOD_FALLBACK_USED", "info", "La part utilisable batterie vient d'une valeur globale de secours et non d'une batterie produit.", "battery_dod", battery_dod_source["value"], "Utiliser la fiche technique de la batterie retenue si disponible."))
        if battery_product is None:
            warnings.append(warning("BATTERY_CATALOG_MISSING", "critical", "Aucune batterie catalogue n'est disponible pour matérialiser le besoin calculé.", "battery_required_kwh", battery_required, "Compléter le catalogue batteries."))
        elif battery_commercial + 1e-6 < battery_required:
            warnings.append(warning("BATTERY_CATALOG_LIMIT", "warning", "La batterie catalogue retenue reste inférieure à la capacité cible calculée.", "battery_required_kwh", battery_required, "Prévoir une solution catalogue supérieure."))
        if inverter is None:
            warnings.append(warning("INVERTER_CATALOG_MISSING", "critical", "Aucun onduleur catalogue compatible n'a été trouvé.", "inverter_calculated_kw", inverter_kw, "Compléter le catalogue onduleurs."))
        elif float(inverter.get("power_kw") or 0) + 1e-6 < inverter_kw:
            warnings.append(warning("INVERTER_CATALOG_LIMIT", "warning", "L'onduleur catalogue disponible est inférieur à la puissance minimale calculée.", "inverter_calculated_kw", inverter_kw, "Prévoir un modèle supérieur ou compléter le catalogue."))
        if panels >= 40:
            warnings.append(warning("PV_PANEL_COUNT_HIGH", "warning", "Le nombre de panneaux retenu est élevé pour une installation Off-Grid.", "panels", panels, "Vérifier les hypothèses de consommation, de site et d'autonomie."))
        final = {
            "daily_consumption_kwh": daily,
            "energy_reference_kwh_day": daily,
            "autonomy_days": autonomy,
            "battery_dod": battery_dod_source["value"],
            "battery_efficiency": battery_efficiency_source["value"],
            "battery_theoretical_kwh": battery_theoretical,
            "battery_target_kwh": battery_required,
            "battery_commercial_kwh": battery_commercial,
            "pv_theoretical_kwp": pv_theoretical,
            "pv_target_kwp": pv_target_kwp,
            "pv_power_kwp": pv_kwp,
            "pv_loss_method": "performance_ratio_only",
            "pv_performance_ratio_used": pv_ratio_source["value"],
            "pv_safety_margin_used": pv_bundle["pv_margin_source"]["value"],
            "psh_used": psh,
            "panel_power_w": panel_power_source["value"],
            "panel_count_theoretical": pv_bundle["panel_count_theoretical"],
            "panels": panels,
            "peak_load_kw": peak,
            "inverter_calculated_kw": inverter_kw,
            "inverter_selected_kw": float(inverter.get("power_kw") or inverter_kw) if inverter else inverter_kw,
            "protections": "Protections DC/AC, batterie et terre prévues au chiffrage.",
            "cabling": "Sections à confirmer selon distances réelles.",
            "battery_configuration": f"{battery_qty} module(s) × {battery_unit:.2f} kWh",
        }
        metrics = [
            {"label": "Besoin de référence", "value": f"{daily:.1f} kWh/j"},
            {"label": "Champ PV", "value": f"{pv_kwp:.2f} kWc"},
            {"label": "Modules", "value": f"{panels} × {panel_power_source['value']:.0f} W"},
            {"label": "Batterie retenue", "value": f"{battery_commercial:.1f} kWh"},
            {"label": "Onduleur", "value": f"{final['inverter_selected_kw']:.1f} kW"},
            {"label": "Autonomie", "value": f"{autonomy:g} jour(s)"},
        ]
        used_keys = [
            "pv_performance_ratio",
            "pv_safety_margin",
            "battery_capacity_margin",
            "inverter_peak_factor",
            "autonomy_default_days",
        ]
        if battery_dod_source["source_reference"] == "battery_dod":
            used_keys.append("battery_dod")
        if battery_efficiency_source["source_reference"] == "battery_efficiency":
            used_keys.append("battery_efficiency")
        if psh_source["source_type"] != "local_data":
            used_keys.append("productible_default_psh")
        if panel_power_source["source_reference"] == "pv_panel_default_w":
            used_keys.append("pv_panel_default_w")
        resolved_sources = {
            "autonomy_default_days": self._resolved_source(
                "Autonomie batterie utilisée",
                autonomy_source,
                display_kind="duration_days",
                key="autonomy_default_days",
                category="Batteries",
                role="Règle HeliAntha",
            ),
            "battery_dod": self._resolved_source(
                "Part utilisable batterie utilisée",
                battery_dod_source,
                display_kind="percent",
                key="battery_dod",
                category="Batteries",
                role="Produit ou valeur de secours",
            ),
            "battery_efficiency": self._resolved_source(
                "Rendement batterie utilisé",
                battery_efficiency_source,
                display_kind="percent",
                key="battery_efficiency",
                category="Batteries",
                role="Produit ou valeur de secours",
            ),
            "battery_capacity_margin": self._resolved_source(
                "Marge de sécurité batterie",
                battery_margin_source,
                display_kind="percent",
                key="battery_capacity_margin",
                category="Batteries",
                role="Règle HeliAntha",
            ),
            "pv_performance_ratio": self._resolved_source(
                "Performance globale photovoltaïque",
                pv_ratio_source,
                display_kind="percent",
                key="pv_performance_ratio",
                category="Photovoltaïque",
                role="Paramètre de secours",
            ),
            "pv_safety_margin": self._resolved_source(
                "Marge de dimensionnement photovoltaïque",
                pv_bundle["pv_margin_source"],
                display_kind="percent",
                key="pv_safety_margin",
                category="Photovoltaïque",
                role="Règle HeliAntha",
            ),
            "productible_default_psh": self._resolved_source(
                "Ensoleillement utilisé",
                psh_source,
                display_kind="psh",
                key="productible_default_psh",
                category="Photovoltaïque",
                role="Donnée locale ou secours",
            ),
            "pv_panel_default_w": self._resolved_source(
                "Puissance panneau utilisée",
                panel_power_source,
                display_kind="power_w",
                key="pv_panel_default_w",
                category="Photovoltaïque",
                role="Produit ou valeur de secours",
            ),
            "inverter_peak_factor": self._resolved_source(
                "Marge de puissance de l'onduleur",
                inverter_peak_source,
                display_kind="multiplier_margin",
                key="inverter_peak_factor",
                category="Onduleurs",
                role="Règle HeliAntha",
            ),
        }
        reliability = self._apply_reliability_adjustments(
            self._reliability("offgrid", d, [("daily_kwh", 22), ("peak_kw", 16), ("autonomy", 10), ("city", 10)]),
            [
                ("PSH de secours", -5, "fallback") if psh_source["source_type"] != "local_data" else None,
                ("Panneau de secours", -5, "fallback") if panel_power_source["source_type"] != "manufacturer" else None,
                ("DoD batterie de secours", -4, "fallback") if battery_dod_source["source_type"] != "manufacturer" else None,
            ],
        )
        calculation_blocks = [
            self._calc_block("Besoin client", [
                self._calc_item("Énergie AC journalière", daily, "kWh/j", formula=f"Besoin saisi = {self._format_decimal(daily)} kWh/j"),
                self._calc_item("Autonomie demandée", autonomy, "jour(s)", decimals=2, formula=f"Autonomie retenue = {self._format_decimal(autonomy)} jour(s)", source=resolved_sources["autonomy_default_days"]),
                self._calc_item("Puissance simultanée", peak, "kW", formula=f"Puissance retenue = {self._format_decimal(peak)} kW"),
            ]),
            self._calc_block("Données locales", [
                self._calc_item("PSH utilisée", psh, "h/j", formula=f"PSH = {self._format_decimal(psh)} h/j", source=resolved_sources["productible_default_psh"]),
                self._calc_item("Performance globale PV", pv_ratio_source["value"] * 100, "%", formula=f"PR = {self._format_decimal(pv_ratio_source['value'] * 100)} %", source=resolved_sources["pv_performance_ratio"]),
                self._calc_item("Marge PV", pv_bundle["pv_margin_source"]["value"] * 100, "%", formula=f"Marge PV = {self._format_decimal(pv_bundle['pv_margin_source']['value'] * 100)} %", source=resolved_sources["pv_safety_margin"]),
                self._calc_item("Puissance panneau utilisée", panel_power_source["value"], "W", decimals=0, formula=f"Panneau = {self._format_decimal(panel_power_source['value'], 0)} W", source=resolved_sources["pv_panel_default_w"]),
            ]),
            self._calc_block("Calcul photovoltaïque", [
                self._calc_item("Besoin énergétique de référence", daily, "kWh/j", formula=f"Référence PV = {self._format_decimal(daily)} kWh/j"),
                self._calc_item("Puissance PV théorique", pv_theoretical, "kWp", formula=f"{self._format_decimal(daily)} / ({self._format_decimal(psh)} x {self._format_decimal(pv_ratio_source['value'])}) = {self._format_decimal(pv_theoretical)} kWp"),
                self._calc_item("Puissance PV cible", pv_target_kwp, "kWp", formula=f"{self._format_decimal(pv_theoretical)} x {self._format_decimal(1 + pv_bundle['pv_margin_source']['value'])} = {self._format_decimal(pv_target_kwp)} kWp"),
                self._calc_item("Nombre théorique de panneaux", pv_bundle["panel_count_theoretical"], "", formula=f"{self._format_decimal(pv_target_kwp * 1000)} / {self._format_decimal(panel_power_source['value'], 0)} = {self._format_decimal(pv_bundle['panel_count_theoretical'])}"),
                self._calc_item("Nombre retenu", panels, "panneaux", decimals=0, formula=f"Arrondi supérieur de {self._format_decimal(pv_bundle['panel_count_theoretical'])} = {panels}"),
                self._calc_item("Puissance installée", pv_kwp, "kWp", formula=f"{panels} x {self._format_decimal(panel_power_source['value'], 0)} / 1000 = {self._format_decimal(pv_kwp)} kWp"),
            ]),
            self._calc_block("Calcul batterie", [
                self._calc_item("Part utilisable utilisée", battery_dod_source["value"] * 100, "%", formula=f"DoD = {self._format_decimal(battery_dod_source['value'] * 100)} %", source=resolved_sources["battery_dod"]),
                self._calc_item("Rendement batterie utilisé", battery_efficiency_source["value"] * 100, "%", formula=f"Rendement = {self._format_decimal(battery_efficiency_source['value'] * 100)} %", source=resolved_sources["battery_efficiency"]),
                self._calc_item("Capacité théorique", battery_theoretical, "kWh", formula=f"{self._format_decimal(daily)} x {self._format_decimal(autonomy)} / ({self._format_decimal(battery_dod_source['value'])} x {self._format_decimal(battery_efficiency_source['value'])}) = {self._format_decimal(battery_theoretical)} kWh"),
                self._calc_item("Capacité cible", battery_required, "kWh", formula=f"{self._format_decimal(battery_theoretical)} x {self._format_decimal(1 + battery_margin_source['value'])} = {self._format_decimal(battery_required)} kWh", source=resolved_sources["battery_capacity_margin"]),
                self._calc_item("Capacité commerciale retenue", battery_commercial, "kWh", formula=f"{battery_qty} x {self._format_decimal(battery_unit)} = {self._format_decimal(battery_commercial)} kWh"),
            ]),
            self._calc_block("Calcul onduleur", [
                self._calc_item("Puissance minimale onduleur", inverter_kw, "kW", formula=f"{self._format_decimal(peak)} x {self._format_decimal(inverter_peak_source['value'])} = {self._format_decimal(inverter_kw)} kW", source=resolved_sources["inverter_peak_factor"]),
                self._calc_item("Onduleur retenu", final["inverter_selected_kw"], "kW", formula=f"Catalogue >= {self._format_decimal(inverter_kw)} kW"),
            ]),
        ]
        return CalculationResult(
            "offgrid",
            "Installation autonome Off-Grid",
            f"Production et stockage dimensionnés pour environ {daily:g} kWh consommés par jour.",
            dict(d),
            ["Calcul provisoire avec batteries lithium LFP.", "La correction globale photovoltaïque est actuellement portée par le Performance Ratio seul.", "Les charges critiques doivent être confirmées avant commande."],
            cfg.used_parameters(used_keys),
            {
                "energy_reference_kwh_day": daily,
                "battery_required_kwh": battery_required,
                "battery_unit_kwh": battery_unit,
                "pv_theoretical_kwp": pv_theoretical,
                "pv_target_kwp": pv_target_kwp,
                "panel_count_theoretical": pv_bundle["panel_count_theoretical"],
                "inverter_calculated_kw": inverter_kw,
                "calculation_blocks": calculation_blocks,
            },
            warnings,
            final,
            equipment,
            CALCULATOR_VERSIONS["OffGridCalculator"],
            metrics,
            reliability,
            self._steps([
                ("Consommation", f"{daily:.2f} kWh/j", "Donnée client ou estimation."),
                ("Performance PV", f"{pv_ratio_source['value']:.0%}", "Le PR porte la correction globale PV de cette version."),
                ("Batterie", f"{battery_commercial:.2f} kWh", "Besoin × autonomie / DOD / rendement + marge."),
                ("PV", f"{pv_kwp:.2f} kWc", "Besoin / (PSH × PR), puis marge PV."),
                ("Onduleur", f"{final['inverter_selected_kw']:.1f} kW", "Puissance simultanée × coefficient sécurité."),
                ("Equipement", f"{panels} panneaux, {battery_qty} batterie(s)", "Sélection catalogue actif."),
            ]),
            resolved_sources,
            "offgrid",
        )

    def _ongrid(self, d: dict[str, Any], cfg: ContextView) -> CalculationResult:
        monthly = max(number(d, "monthly_kwh", 500), 50)
        city = text(d, "city")
        roof_area = number(d, "roof_area", 0)
        day_profile = text(d, "day_profile", "journée").lower()
        psh_source = cfg.psh_source(city)
        pv_ratio_source = cfg.parameter_source("pv_performance_ratio", 0.80)
        annual_consumption = monthly * 12
        target_coverage = 0.75 if "nuit" not in day_profile else 0.55
        target_annual = annual_consumption * target_coverage
        productible_per_kwp = psh_source["value"] * 365 * pv_ratio_source["value"]
        pv_theoretical = target_annual / max(productible_per_kwp, 1)
        panel = cfg.panel()
        pv_bundle = self._pv_target_bundle(pv_theoretical, panel, cfg)
        panel_power_source = pv_bundle["panel_power_source"]
        panel_w = pv_bundle["panel_w"]
        panel_area = float((panel.get("technical_specs") or {}).get("surface_m2", 2.6))
        panels = pv_bundle["panels"]
        pv_target_kwp = pv_bundle["pv_target_kwp"]
        max_panels_by_area = ceil(roof_area / panel_area) if roof_area else panels
        warnings = []
        if roof_area and panels > max_panels_by_area:
            warnings.append(warning("ROOF_AREA_LIMIT", "warning", "La surface disponible semble insuffisante pour le nombre de panneaux calculé.", "roof_area", roof_area, "Vérifier la toiture ou réduire la puissance retenue."))
            panels = max(1, max_panels_by_area)
        if not city:
            warnings.append(warning("CITY_MISSING", "warning", "La localisation n'est pas renseignée.", "city", "", "Renseigner la ville pour améliorer le productible."))
        elif psh_source["source_type"] != "local_data":
            warnings.append(warning("PSH_FALLBACK_USED", "warning", "Aucune donnée locale d'ensoleillement n'a été trouvée pour cette ville : la valeur de secours est utilisée.", "city", city, "Prévoir une donnée locale HeliAntha ou une mesure site."))
        if panel_power_source["source_type"] != "manufacturer":
            warnings.append(warning("PV_PANEL_FALLBACK_USED", "warning", "Aucun panneau catalogue précis n'a été utilisé : le calcul s'appuie sur une puissance panneau de secours.", "pv_panel_default_w", panel_power_source["value"], "Vérifier le catalogue avant validation finale."))
        pv_kwp = panels * panel_w / 1000
        inverter = cfg.product("inverters", "power_kw", pv_kwp, "on-grid") or cfg.product("inverters", "power_kw", pv_kwp)
        annual_production = round(pv_kwp * productible_per_kwp)
        coverage = min(95, round(annual_production / annual_consumption * 100))
        savings = round(annual_production * 1.35)
        if inverter is None:
            warnings.append(warning("INVERTER_CATALOG_MISSING", "critical", "Aucun onduleur catalogue compatible n'a été trouvé.", "pv_power_kwp", pv_kwp, "Compléter le catalogue onduleurs."))
        elif float(inverter.get("power_kw") or 0) + 1e-6 < pv_kwp:
            warnings.append(warning("INVERTER_CATALOG_LIMIT", "warning", "L'onduleur catalogue disponible est inférieur à la puissance photovoltaïque retenue.", "pv_power_kwp", pv_kwp, "Prévoir un modèle supérieur ou compléter le catalogue."))
        if panels >= 40:
            warnings.append(warning("PV_PANEL_COUNT_HIGH", "warning", "Le nombre de panneaux retenu est élevé pour une installation On-Grid.", "panels", panels, "Vérifier les hypothèses de consommation, de site et de surface."))
        equipment = [self._line(panel, panels, "Champ photovoltaïque")]
        if inverter:
            equipment.append(self._line(inverter, 1, "Onduleur réseau"))
        final = {
            "monthly_consumption_kwh": monthly,
            "annual_consumption_kwh": annual_consumption,
            "consumption_profile": day_profile,
            "roof_area_m2": roof_area,
            "location": city,
            "solar_potential_psh": psh_source["value"],
            "productible_kwh_kwp_year": productible_per_kwp,
            "pv_theoretical_kwp": pv_theoretical,
            "pv_target_kwp": pv_target_kwp,
            "pv_power_kwp": pv_kwp,
            "pv_loss_method": "performance_ratio_only",
            "pv_performance_ratio_used": pv_ratio_source["value"],
            "pv_safety_margin_used": pv_bundle["pv_margin_source"]["value"],
            "panel_power_w": panel_w,
            "panel_count_theoretical": pv_bundle["panel_count_theoretical"],
            "panels": panels,
            "inverter_selected_kw": float(inverter.get("power_kw") or pv_kwp) if inverter else round_up(pv_kwp, 0.5),
            "annual_production_kwh": annual_production,
            "energy_coverage_percent": coverage,
            "estimated_savings_dh_year": savings,
            "protections": "Coffrets DC/AC, parafoudre, sectionneur et mise à la terre.",
            "cabling": "Câblage DC/AC dimensionné après métrés.",
        }
        metrics = [
            {"label": "Puissance retenue", "value": f"{pv_kwp:.2f} kWc"},
            {"label": "Modules", "value": f"{panels} × {panel_w:.0f} W"},
            {"label": "Production estimée", "value": f"{annual_production:,} kWh/an".replace(",", " ")},
            {"label": "Couverture", "value": f"{coverage} %"},
            {"label": "Economie indicative", "value": f"{savings:,.0f} DH/an".replace(",", " ")},
            {"label": "Onduleur", "value": f"{final['inverter_selected_kw']:.1f} kW"},
        ]
        used_keys = ["pv_performance_ratio", "pv_safety_margin"]
        if psh_source["source_type"] != "local_data":
            used_keys.append("productible_default_psh")
        if panel_power_source["source_reference"] == "pv_panel_default_w":
            used_keys.append("pv_panel_default_w")
        resolved_sources = {
            "productible_default_psh": self._resolved_source(
                "Ensoleillement utilisé",
                psh_source,
                display_kind="psh",
                key="productible_default_psh",
                category="Photovoltaïque",
                role="Donnée locale ou secours",
            ),
            "pv_performance_ratio": self._resolved_source(
                "Performance globale photovoltaïque",
                pv_ratio_source,
                display_kind="percent",
                key="pv_performance_ratio",
                category="Photovoltaïque",
                role="Paramètre de secours",
            ),
            "pv_safety_margin": self._resolved_source(
                "Marge de dimensionnement photovoltaïque",
                pv_bundle["pv_margin_source"],
                display_kind="percent",
                key="pv_safety_margin",
                category="Photovoltaïque",
                role="Règle HeliAntha",
            ),
            "pv_panel_default_w": self._resolved_source(
                "Puissance panneau utilisée",
                panel_power_source,
                display_kind="power_w",
                key="pv_panel_default_w",
                category="Photovoltaïque",
                role="Produit ou valeur de secours",
            ),
        }
        reliability = self._apply_reliability_adjustments(
            self._reliability("ongrid", d, [("monthly_kwh", 24), ("city", 14), ("roof_area", 14), ("bill", 8)]),
            [
                ("PSH de secours", -5, "fallback") if psh_source["source_type"] != "local_data" else None,
                ("Panneau de secours", -5, "fallback") if panel_power_source["source_type"] != "manufacturer" else None,
            ],
        )
        calculation_blocks = [
            self._calc_block("Besoin client", [
                self._calc_item("Consommation mensuelle", monthly, "kWh/mois", formula=f"Consommation saisie = {self._format_decimal(monthly)} kWh/mois"),
                self._calc_item("Consommation annuelle", annual_consumption, "kWh/an", formula=f"{self._format_decimal(monthly)} x 12 = {self._format_decimal(annual_consumption)} kWh/an"),
                self._calc_item("Couverture cible", target_coverage * 100, "%", formula=f"Couverture cible = {self._format_decimal(target_coverage * 100)} %"),
                self._calc_item("Besoin solaire cible", target_annual, "kWh/an", formula=f"{self._format_decimal(annual_consumption)} x {self._format_decimal(target_coverage)} = {self._format_decimal(target_annual)} kWh/an"),
            ]),
            self._calc_block("Données locales", [
                self._calc_item("PSH utilisée", psh_source["value"], "h/j", formula=f"PSH = {self._format_decimal(psh_source['value'])} h/j", source=resolved_sources["productible_default_psh"]),
                self._calc_item("Performance globale PV", pv_ratio_source["value"] * 100, "%", formula=f"PR = {self._format_decimal(pv_ratio_source['value'] * 100)} %", source=resolved_sources["pv_performance_ratio"]),
                self._calc_item("Marge PV", pv_bundle["pv_margin_source"]["value"] * 100, "%", formula=f"Marge PV = {self._format_decimal(pv_bundle['pv_margin_source']['value'] * 100)} %", source=resolved_sources["pv_safety_margin"]),
                self._calc_item("Puissance panneau utilisée", panel_power_source["value"], "W", decimals=0, formula=f"Panneau = {self._format_decimal(panel_power_source['value'], 0)} W", source=resolved_sources["pv_panel_default_w"]),
            ]),
            self._calc_block("Calcul photovoltaïque", [
                self._calc_item("Productible annuel par kWp", productible_per_kwp, "kWh/kWp/an", formula=f"{self._format_decimal(psh_source['value'])} x 365 x {self._format_decimal(pv_ratio_source['value'])} = {self._format_decimal(productible_per_kwp)}"),
                self._calc_item("Puissance PV théorique", pv_theoretical, "kWp", formula=f"{self._format_decimal(target_annual)} / {self._format_decimal(productible_per_kwp)} = {self._format_decimal(pv_theoretical)} kWp"),
                self._calc_item("Puissance PV cible", pv_target_kwp, "kWp", formula=f"{self._format_decimal(pv_theoretical)} x {self._format_decimal(1 + pv_bundle['pv_margin_source']['value'])} = {self._format_decimal(pv_target_kwp)} kWp"),
                self._calc_item("Nombre théorique de panneaux", pv_bundle["panel_count_theoretical"], "", formula=f"{self._format_decimal(pv_target_kwp * 1000)} / {self._format_decimal(panel_power_source['value'], 0)} = {self._format_decimal(pv_bundle['panel_count_theoretical'])}"),
                self._calc_item("Nombre retenu", panels, "panneaux", decimals=0, formula=f"Arrondi supérieur de {self._format_decimal(pv_bundle['panel_count_theoretical'])} = {panels}"),
                self._calc_item("Puissance installée", pv_kwp, "kWp", formula=f"{panels} x {self._format_decimal(panel_power_source['value'], 0)} / 1000 = {self._format_decimal(pv_kwp)} kWp"),
            ]),
            self._calc_block("Calcul onduleur", [
                self._calc_item("Onduleur retenu", final["inverter_selected_kw"], "kW", formula=f"Catalogue >= {self._format_decimal(pv_kwp)} kWc"),
                self._calc_item("Production annuelle estimée", annual_production, "kWh/an", formula=f"{self._format_decimal(pv_kwp)} x {self._format_decimal(productible_per_kwp)} = {annual_production:.0f} kWh/an"),
                self._calc_item("Economie estimée", savings, "DH/an", formula=f"{annual_production:.0f} x 1.35 = {savings:.0f} DH/an", decimals=0),
            ]),
        ]
        return CalculationResult(
            "ongrid",
            "Installation solaire On-Grid",
            "Une centrale dimensionnée depuis la consommation et le potentiel solaire disponible.",
            dict(d),
            ["Objectif provisoire d'autoconsommation selon le profil indiqué.", "La correction globale photovoltaïque est actuellement portée par le Performance Ratio seul.", "Le tarif d'économie est indicatif."],
            cfg.used_parameters(used_keys),
            {
                "target_coverage": target_coverage,
                "target_annual_kwh": target_annual,
                "productible_per_kwp": productible_per_kwp,
                "pv_theoretical_kwp": pv_theoretical,
                "pv_target_kwp": pv_target_kwp,
                "panel_count_theoretical": pv_bundle["panel_count_theoretical"],
                "max_panels_by_area": max_panels_by_area,
                "calculation_blocks": calculation_blocks,
            },
            warnings,
            final,
            equipment,
            CALCULATOR_VERSIONS["OnGridCalculator"],
            metrics,
            reliability,
            self._steps([
                ("Consommation mensuelle", f"{monthly:.0f} kWh/mois", "Donnée client."),
                ("Consommation annuelle", f"{annual_consumption:.0f} kWh/an", "Mensuel × 12."),
                ("Besoin solaire cible", f"{target_annual:.0f} kWh/an", "Couverture cible selon profil."),
                ("Puissance PV théorique", f"{pv_theoretical:.2f} kWc", "Besoin cible / productible."),
                ("Marge PV", f"{pv_bundle['pv_margin_source']['value']:.0%}", "Application unique de la marge PV."),
                ("Nombre panneaux", f"{panels}", "Puissance cible / puissance panneau, arrondi supérieur."),
                ("Equipement", f"Onduleur {final['inverter_selected_kw']:.1f} kW", "Sélection catalogue actif."),
            ]),
            resolved_sources,
            "ongrid",
        )

    def _hybrid(self, d: dict[str, Any], cfg: ContextView) -> CalculationResult:
        result = self._offgrid(d, cfg)
        priority_kwh = number(d, "priority_kwh", result.final_results["daily_consumption_kwh"] * 0.65)
        result.project = "hybrid"
        result.title = "Installation solaire hybride"
        result.summary = "Solaire, réseau et batterie coordonnés pour les charges prioritaires."
        result.calculation_version = CALCULATOR_VERSIONS["HybridCalculator"]
        result.offer_profile = "hybrid"
        result.final_results["priority_loads"] = text(d, "objective", "Charges prioritaires")
        result.final_results["priority_energy_kwh"] = priority_kwh
        result.final_results["battery_sizing_basis_kwh_day"] = result.final_results["daily_consumption_kwh"]
        result.metrics.append({"label": "Charges prioritaires", "value": f"{priority_kwh:.1f} kWh/j"})
        result.assumptions.append("Mode hybride provisoire basé sur le dimensionnement Off-Grid adapté aux charges prioritaires.")
        result.warnings.append(warning("HYBRID_STORAGE_SIMPLIFIED", "info", "Le stockage hybride reste actuellement dimensionné sur la consommation journalière globale. Les charges prioritaires sont affichées mais ne pilotent pas encore seules la batterie.", "priority_kwh", priority_kwh, "Une future version séparera plus finement consommation totale et charges secourues."))
        result.intermediate_results["priority_energy_kwh"] = priority_kwh
        result.intermediate_results["hybrid_storage_limit"] = "battery_sizing_uses_total_daily_consumption"
        blocks = list(result.intermediate_results.get("calculation_blocks") or [])
        blocks.append(self._calc_block("Limite actuelle du mode hybride", [
            self._calc_item("Charges prioritaires affichées", priority_kwh, "kWh/j", formula=f"Valeur retenue = {self._format_decimal(priority_kwh)} kWh/j"),
            self._calc_item("Base actuelle de dimensionnement batterie", result.final_results["daily_consumption_kwh"], "kWh/j", formula=f"Le calcul batterie reste base sur {self._format_decimal(result.final_results['daily_consumption_kwh'])} kWh/j", note="La separation stricte entre consommation totale et charges secourues sera une evolution future."),
        ]))
        result.intermediate_results["calculation_blocks"] = blocks
        result.reasoning_steps.append({
            "input": "Charges prioritaires",
            "rule": "Energie prioritaire estimée ou saisie",
            "intermediate_result": f"{priority_kwh:.2f} kWh/j",
            "coefficient": "",
            "technical_decision": "Configuration hybride avec secours batterie",
            "selected_equipment": "Onduleur hybride et stockage",
        })
        return result

    def _thermal(self, d: dict[str, Any], cfg: ContextView) -> CalculationResult:
        people = max(ceil(number(d, "people", 4)), 1)
        building = text(d, "building", "Maison")
        city = text(d, "city")
        liters_source = cfg.parameter_source("thermal_liters_per_person", 50)
        inlet_source = cfg.parameter_source("thermal_inlet_temp", 15)
        target_source = cfg.parameter_source("thermal_target_temp", 55)
        losses_source = cfg.parameter_source("thermal_losses", 0.20)
        collector_liters_source = cfg.parameter_source("thermal_collector_liters", 150)
        daily_liters = number(d, "daily_hot_water_l", people * liters_source["value"])
        target = target_source["value"]
        inlet = inlet_source["value"]
        delta = max(target - inlet, 1)
        energy_kwh = daily_liters * delta * WATER_HEAT_WH_PER_LITER_C / 1000
        corrected = energy_kwh * (1 + losses_source["value"])
        tank_required = max(daily_liters, people * liters_source["value"])
        tank = cfg.product("thermal", "capacity_l", tank_required, "ballon solaire") or cfg.product("thermal", "capacity_l", tank_required)
        tank_capacity = float(tank.get("capacity_l") or ceil(tank_required / 50) * 50) if tank else ceil(tank_required / 50) * 50
        collector = cfg.product("thermal", subcategory="capteur")
        collectors = max(1, ceil(tank_capacity / collector_liters_source["value"]))
        equipment = []
        if tank:
            equipment.append(self._line(tank, 1, "Ballon solaire"))
        if collector:
            equipment.append(self._line(collector, collectors, "Capteurs solaires thermiques"))
        warnings = []
        if not d.get("people") and not d.get("daily_hot_water_l"):
            warnings.append(warning("HOT_WATER_ESTIMATED", "warning", "Le besoin en eau chaude est estimé depuis le nombre d'occupants par défaut.", "people", people, "Confirmer le profil d'utilisation."))
        final = {
            "building_type": building,
            "people": people,
            "daily_hot_water_l": daily_liters,
            "target_temperature_c": target,
            "inlet_temperature_c": inlet,
            "daily_energy_kwh": energy_kwh,
            "losses": losses_source["value"],
            "corrected_energy_kwh": corrected,
            "tank_capacity_l": tank_capacity,
            "collectors": collectors,
            "collector_surface_m2": collectors * float((collector or {}).get("technical_specs", {}).get("surface_m2", 2)),
            "location": city,
            "backup": text(d, "backup", "Appoint électrique à confirmer"),
            "required_material": "Ballon, capteurs, support, raccordement hydraulique, régulation et appoint.",
        }
        metrics = [
            {"label": "Besoin ECS", "value": f"{daily_liters:.0f} L/j"},
            {"label": "Ballon retenu", "value": f"{tank_capacity:.0f} L"},
            {"label": "Capteurs", "value": f"{collectors}"},
            {"label": "Surface capteurs", "value": f"{final['collector_surface_m2']:.1f} m²"},
            {"label": "Energie utile", "value": f"{corrected:.1f} kWh/j"},
            {"label": "Bâtiment", "value": building},
        ]
        resolved_sources = {
            "thermal_liters_per_person": self._resolved_source(
                "Besoin d'eau chaude par personne",
                liters_source,
                display_kind="liters_per_day",
                key="thermal_liters_per_person",
                category="Thermique",
                role="Règle HeliAntha",
            ),
            "thermal_inlet_temp": self._resolved_source(
                "Température d'eau froide utilisée",
                inlet_source,
                display_kind="temperature",
                key="thermal_inlet_temp",
                category="Thermique",
                role="Donnée locale ou secours",
            ),
            "thermal_target_temp": self._resolved_source(
                "Température d'eau chaude visée",
                target_source,
                display_kind="temperature",
                key="thermal_target_temp",
                category="Thermique",
                role="Règle HeliAntha",
            ),
            "thermal_losses": self._resolved_source(
                "Pertes thermiques estimées",
                losses_source,
                display_kind="percent",
                key="thermal_losses",
                category="Thermique",
                role="Règle HeliAntha",
            ),
            "thermal_collector_liters": self._resolved_source(
                "Capacité couverte par capteur utilisée",
                collector_liters_source,
                display_kind="liters",
                key="thermal_collector_liters",
                category="Thermique",
                role="Valeur de secours",
            ),
        }
        return CalculationResult(
            "thermal",
            "Chauffe-eau solaire",
            f"Une production d'eau chaude adaptée à {people} personne(s).",
            dict(d),
            ["Calcul thermique provisoire basé sur un besoin ECS par personne.", "L'appoint dépendra de l'installation existante."],
            cfg.used_parameters(["thermal_liters_per_person", "thermal_inlet_temp", "thermal_target_temp", "thermal_losses", "thermal_collector_liters"]),
            {"delta_temperature_c": delta, "daily_energy_kwh": energy_kwh, "corrected_energy_kwh": corrected, "tank_required_l": tank_required},
            warnings,
            final,
            equipment,
            CALCULATOR_VERSIONS["SolarThermalCalculator"],
            metrics,
            self._reliability("thermal", d, [("people", 18), ("building", 10), ("city", 8), ("daily_hot_water_l", 14)]),
            self._steps([
                ("Occupants", f"{people}", "Saisie ou valeur par défaut."),
                ("Besoin ECS", f"{daily_liters:.0f} L/j", "Occupants × litres/personne."),
                ("Energie", f"{corrected:.2f} kWh/j", "Volume × écart température + pertes."),
                ("Ballon", f"{tank_capacity:.0f} L", "Capacité commerciale catalogue."),
                ("Capteurs", f"{collectors}", "Capacité ballon / couverture par capteur."),
            ]),
            resolved_sources,
            "thermal",
        )

    def _ev(self, d: dict[str, Any], cfg: ContextView) -> CalculationResult:
        vehicle = text(d, "vehicle", "Véhicule à confirmer")
        battery = max(number(d, "vehicle_battery", 50), 10)
        car_ac_max = max(number(d, "vehicle_ac_max", number(d, "ac_max_power", 22)), 3.7)
        daily_km = number(d, "daily_km", 50)
        consumption = max(number(d, "consumption_kwh_100km", 17), 8)
        available = max(number(d, "available_power", 7.4), 1)
        requested = number(d, "charger_power", 0)
        phases = text(d, "phases", text(d, "installation_type", "monophasée")).lower()
        distance = max(number(d, "distance", 10), 1)
        charge_efficiency_source = cfg.parameter_source("ev_charge_efficiency", 0.90)
        safety_source = cfg.parameter_source("ev_safety_factor", 0.10)
        phase_limit = 7.4 if "tri" not in phases else 22
        feasible_power = min(available, car_ac_max, phase_limit)
        choices = [7.4, 11, 22]
        possible = [p for p in choices if p <= feasible_power + 0.01]
        recommended = requested or (possible[-1] if possible else 7.4)
        if requested:
            retained = min(requested, max(feasible_power, 3.7), 22)
            retained = min(choices, key=lambda p: abs(p - retained))
        else:
            retained = possible[-1] if possible else 7.4
        charger = cfg.product("ev_chargers", "power_kw", retained)
        daily_energy = daily_km * consumption / 100
        recharge_time = battery * 0.8 / max(min(retained, available, car_ac_max) * charge_efficiency_source["value"], 0.1)
        recommended_available = retained * (1 + safety_source["value"])
        warnings = []
        if requested and requested > feasible_power:
            warnings.append(warning("EV_POWER_NOT_FEASIBLE", "warning", "La puissance de borne demandée dépasse la puissance compatible avec le véhicule ou l'installation.", "charger_power", requested, "Prévoir adaptation électrique ou retenir une borne plus faible."))
        if retained > available:
            warnings.append(warning("EV_AVAILABLE_POWER_LOW", "critical", "La puissance disponible est insuffisante pour la borne retenue.", "available_power", available, "Contrôle électrique obligatoire avant devis."))
        elif available + 1e-6 < recommended_available:
            warnings.append(warning("EV_SAFETY_MARGIN_LOW", "warning", "La puissance électrique disponible est inférieure à la puissance recommandée pour cette borne avec la marge de sécurité configurée.", "available_power", available, "Vérification électrique recommandée avant validation de la borne."))
        if charger is None:
            warnings.append(warning("EV_CATALOG_MISSING", "warning", "Aucune borne catalogue exacte n'a été trouvée pour cette puissance.", "charger_power", retained, "Compléter le catalogue bornes EV."))
        equipment = []
        if charger:
            equipment.append(self._line(charger, max(1, ceil(number(d, "chargers", 1))), "Borne de recharge AC"))
        final = {
            "vehicle": vehicle,
            "vehicle_battery_kwh": battery,
            "vehicle_ac_max_kw": car_ac_max,
            "daily_km": daily_km,
            "consumption_kwh_100km": consumption,
            "daily_energy_kwh": daily_energy,
            "available_power_kw": available,
            "requested_power_kw": requested,
            "theoretical_recommended_kw": recommended,
            "charger_power_kw": retained,
            "recommended_available_power_kw": recommended_available,
            "ev_safety_factor_used": safety_source["value"],
            "recharge_time_h": recharge_time,
            "phases": "Triphasée" if "tri" in phases else "Monophasée",
            "distance_panel_charger_m": distance,
            "cable": f"Câble borne EV sur environ {distance:g} m",
            "protection": "Disjoncteur différentiel dédié, coffret et mise à la terre.",
            "accessories": "Support, signalétique et mise en service.",
        }
        metrics = [
            {"label": "Borne retenue", "value": f"{retained:g} kW AC"},
            {"label": "Puissance disponible", "value": f"{available:g} kW"},
            {"label": "Véhicule", "value": vehicle},
            {"label": "Recharge 20-100 %", "value": f"≈ {recharge_time:.1f} h"},
            {"label": "Distance", "value": f"{distance:g} m"},
            {"label": "Alimentation", "value": final["phases"]},
        ]
        resolved_sources = {
            "ev_charge_efficiency": self._resolved_source(
                "Rendement de recharge utilisé",
                charge_efficiency_source,
                display_kind="percent",
                key="ev_charge_efficiency",
                category="Borne EV",
                role="Valeur de secours",
            ),
            "ev_safety_factor": self._resolved_source(
                "Marge de sécurité EV disponible",
                safety_source,
                display_kind="percent",
                key="ev_safety_factor",
                category="Borne EV",
                role="Règle HeliAntha",
            ),
        }
        reliability = self._apply_reliability_adjustments(
            self._reliability("ev", d, [("vehicle_battery", 14), ("available_power", 18), ("distance", 10), ("vehicle", 8), ("charger_power", 6)]),
            [
                ("Marge EV non respectee", -4, "warning") if available + 1e-6 < recommended_available and available + 1e-6 >= retained else None,
            ],
        )
        calculation_blocks = [
            self._calc_block("Besoin client", [
                self._calc_item("Batterie véhicule", battery, "kWh", formula=f"Capacité retenue = {self._format_decimal(battery)} kWh"),
                self._calc_item("Puissance demandée", requested or retained, "kW", formula=f"Demande retenue = {self._format_decimal(requested or retained)} kW"),
                self._calc_item("Puissance disponible", available, "kW", formula=f"Puissance disponible = {self._format_decimal(available)} kW"),
            ]),
            self._calc_block("Vérification électrique", [
                self._calc_item("Limite compatible", feasible_power, "kW", formula=f"min({self._format_decimal(available)}, {self._format_decimal(car_ac_max)}, {self._format_decimal(phase_limit)}) = {self._format_decimal(feasible_power)} kW"),
                self._calc_item("Borne retenue", retained, "kW", formula=f"Famille retenue = {self._format_decimal(retained)} kW"),
                self._calc_item("Marge de sécurité", safety_source["value"] * 100, "%", formula=f"Marge EV = {self._format_decimal(safety_source['value'] * 100)} %", source=resolved_sources["ev_safety_factor"]),
                self._calc_item("Puissance disponible recommandée", recommended_available, "kW", formula=f"{self._format_decimal(retained)} x {self._format_decimal(1 + safety_source['value'])} = {self._format_decimal(recommended_available)} kW"),
            ]),
            self._calc_block("Recharge et equipement", [
                self._calc_item("Energie quotidienne de conduite", daily_energy, "kWh/j", formula=f"{self._format_decimal(daily_km)} x {self._format_decimal(consumption)} / 100 = {self._format_decimal(daily_energy)} kWh/j"),
                self._calc_item("Rendement de recharge", charge_efficiency_source["value"] * 100, "%", formula=f"Rendement = {self._format_decimal(charge_efficiency_source['value'] * 100)} %", source=resolved_sources["ev_charge_efficiency"]),
                self._calc_item("Temps de recharge 20-100 %", recharge_time, "h", formula=f"{self._format_decimal(battery * 0.8)} / ({self._format_decimal(min(retained, available, car_ac_max))} x {self._format_decimal(charge_efficiency_source['value'])}) = {self._format_decimal(recharge_time)} h"),
                self._calc_item("Borne catalogue retenue", charger.get("model", "Borne EV") if charger else "A confirmer", formula=f"Selection catalogue autour de {self._format_decimal(retained)} kW"),
            ]),
        ]
        return CalculationResult(
            "ev",
            "Borne de recharge véhicule électrique",
            "Une borne AC adaptée au véhicule, au lieu et à l'alimentation disponible.",
            dict(d),
            ["Compatibilité véhicule et installation à vérifier sur site.", "Puissances 7,4 / 11 / 22 kW traitées comme familles de bornes AC."],
            cfg.used_parameters(["ev_charge_efficiency", "ev_safety_factor"]),
            {
                "phase_limit_kw": phase_limit,
                "feasible_power_kw": feasible_power,
                "daily_energy_kwh": daily_energy,
                "charge_efficiency": charge_efficiency_source["value"],
                "recommended_available_power_kw": recommended_available,
                "calculation_blocks": calculation_blocks,
            },
            warnings,
            final,
            equipment,
            CALCULATOR_VERSIONS["EVChargerCalculator"],
            metrics,
            reliability,
            self._steps([
                ("Batterie véhicule", f"{battery:.1f} kWh", "Donnée véhicule."),
                ("Puissance compatible", f"{feasible_power:.1f} kW", "Minimum entre véhicule, réseau et phases."),
                ("Borne retenue", f"{retained:g} kW", "Famille de borne compatible la plus proche."),
                ("Marge EV", f"{safety_source['value']:.0%}", "Vérification de la puissance disponible recommandée."),
                ("Durée recharge", f"{recharge_time:.1f} h", "80 % batterie / puissance utile."),
                ("Equipement", charger.get("model", "Borne EV") if charger else "Borne EV", "Sélection catalogue actif."),
            ]),
            resolved_sources,
            "ev",
        )

    def _iot(self, d: dict[str, Any], cfg: ContextView) -> CalculationResult:
        sensors = max(ceil(number(d, "sensors", 4)), 1)
        warnings = [warning("IOT_OUT_OF_SCOPE", "info", "IoT est temporairement hors périmètre de cette version.", "project", "iot", "Reprendre ce module lors d'une phase dédiée.")]
        return CalculationResult(
            "iot",
            "IoT & systèmes embarqués",
            "Module conservé dans le code mais non développé dans cette phase.",
            dict(d),
            ["Hors périmètre version actuelle."],
            {},
            {"sensors": sensors},
            warnings,
            {"sensors": sensors},
            [],
            CALCULATOR_VERSIONS["IoTCalculator"],
            [{"label": "Statut", "value": "Hors périmètre"}],
            {"score": 0, "items": [{"label": "Hors périmètre", "points": 0, "status": "info"}]},
            self._steps([("Projet", "IoT", "Conservé mais masqué temporairement.")]),
            {},
            "iot",
        )

    def _offers(self, technical: CalculationResult, cfg: ContextView) -> list[dict[str, Any]]:
        variants = self._variant_specs(technical)
        offers = []
        for variant in variants:
            equipment = self._variant_equipment(technical.selected_equipment, technical.offer_profile, variant["level"])
            financial = self.pricing.breakdown(technical.project, equipment, cfg, technical.travel_km)
            offers.append({
                "name": variant["name"],
                "level": variant["level"],
                "recommended": variant["recommended"],
                "description": variant["description"],
                "technical_difference": variant["technical_difference"],
                "ht": financial["total_ht"],
                "vat": financial["vat"],
                "ttc": financial["total_ttc"],
                "selected_equipment": equipment,
                "financial_breakdown": financial,
            })
        return offers

    @staticmethod
    def _variant_specs(technical: CalculationResult) -> list[dict[str, Any]]:
        if technical.project == "iot":
            return [{
                "name": "Etude technique",
                "level": "optimal",
                "recommended": True,
                "description": "Module hors périmètre de cette version.",
                "technical_difference": "Aucun chiffrage automatique.",
            }]
        text_by_profile = {
            "offgrid": (
                "Autonomie minimale valide avec capacité commerciale réduite si possible.",
                "Configuration recommandée avec autonomie demandée.",
                "Réserve renforcée avec capacité batterie/PV augmentée.",
            ),
            "hybrid": (
                "Secours concentré sur les charges prioritaires.",
                "Equilibre réseau, solaire et batterie recommandé.",
                "Autonomie renforcée pour coupures plus longues.",
            ),
            "ongrid": (
                "Puissance PV réduite en conservant une cohérence d'autoconsommation.",
                "Dimensionnement recommandé depuis la consommation client.",
                "Production renforcée si surface et budget le permettent.",
            ),
            "pumping": (
                "Champ PV minimal autour de la pompe retenue.",
                "Dimensionnement recommandé avec marge de pompage.",
                "Champ PV renforcé pour meilleurs débits en conditions difficiles.",
            ),
            "thermal": (
                "Ballon/capteurs minimum adaptés au besoin estimé.",
                "Configuration équilibrée pour usage quotidien.",
                "Réserve renforcée pour confort et usage intensif.",
            ),
            "ev": (
                "Borne compatible au plus proche de la puissance disponible.",
                "Borne recommandée pour le véhicule et l'installation.",
                "Pré-équipement renforcé si l'installation le permet.",
            ),
        }
        essential, optimal, performance = text_by_profile.get(technical.offer_profile, text_by_profile["ongrid"])
        return [
            {"name": "Essentiel", "level": "essential", "recommended": False, "description": "Le nécessaire, avec un budget maîtrisé.", "technical_difference": essential},
            {"name": "Optimal", "level": "optimal", "recommended": True, "description": "Le meilleur équilibre performance et sérénité.", "technical_difference": optimal},
            {"name": "Performance", "level": "performance", "recommended": False, "description": "Plus de réserve et une évolutivité renforcée.", "technical_difference": performance},
        ]

    @staticmethod
    def _variant_equipment(equipment: list[dict[str, Any]], profile: str, level: str) -> list[dict[str, Any]]:
        adjusted = deepcopy(equipment)
        if level == "optimal":
            return adjusted
        for item in adjusted:
            category = item.get("category")
            if item.get("price_status") == "to_confirm" and item.get("product_id") is None:
                continue
            qty = float(item.get("quantity", 1) or 1)
            if level == "essential":
                if profile in {"offgrid", "hybrid"} and category == "batteries":
                    item["quantity"] = max(1, qty - 1)
                elif category == "panels" and qty > 2:
                    item["quantity"] = max(1, qty - 1)
                elif profile == "ev" and category == "ev_chargers":
                    item["quantity"] = qty
            elif level == "performance":
                if category in {"batteries", "panels"}:
                    item["quantity"] = qty + 1
                elif profile in {"pumping", "ev"} and category in {"drives", "ev_chargers"}:
                    item["quantity"] = qty
        for item in adjusted:
            item["total_price"] = round(float(item.get("quantity", 1)) * float(item.get("unit_price", 0)), 2)
        return adjusted

    def _pv_from_daily(self, daily_kwh: float, city: str, cfg: ContextView) -> tuple[float, int, dict[str, Any]]:
        theoretical = self._pv_theoretical(daily_kwh, city, cfg)
        panel = cfg.panel()
        pv_bundle = self._pv_target_bundle(theoretical, panel, cfg)
        return pv_bundle["installed_kwp"], pv_bundle["panels"], panel

    def _pv_theoretical(self, daily_kwh: float, city: str, cfg: ContextView) -> float:
        return daily_kwh / max(self._psh(city, cfg) * cfg.p("pv_performance_ratio", 0.80), 0.1)

    @staticmethod
    def _psh(city: str, cfg: ContextView) -> float:
        return cfg.psh_source(city)["value"]

    @staticmethod
    def _line(product: dict[str, Any], quantity: float, role: str) -> dict[str, Any]:
        unit_price = float(product.get("sale_price") or 0)
        return {
            "reference": product.get("reference", ""),
            "category": product.get("category", ""),
            "subcategory": product.get("subcategory", ""),
            "brand": product.get("brand", ""),
            "model": product.get("model", ""),
            "description": product.get("description", ""),
            "role": role,
            "quantity": quantity,
            "unit": product.get("unit", "piece"),
            "unit_price": unit_price,
            "total_price": round(quantity * unit_price),
            "technical_specs": deepcopy(product.get("technical_specs") or {}),
            "power_w": product.get("power_w"),
            "power_kw": product.get("power_kw"),
            "capacity_kwh": product.get("capacity_kwh"),
            "capacity_l": product.get("capacity_l"),
            "warranty": product.get("warranty", ""),
        }

    @staticmethod
    def _steps(raw_steps: list[tuple[str, str, str]]) -> list[dict[str, Any]]:
        return [
            {
                "input": item,
                "rule": rule,
                "intermediate_result": result,
                "coefficient": "",
                "technical_decision": "Retenir une configuration commerciale cohérente.",
                "selected_equipment": "",
            }
            for item, result, rule in raw_steps
        ]

    @staticmethod
    def _reliability(project: str, data: dict[str, Any], weighted_fields: list[tuple[str, int]]) -> dict[str, Any]:
        items = [{"label": f"Base {project}", "points": 35, "status": "base"}]
        score = 35
        for key, points in weighted_fields:
            if data.get(key):
                score += points
                items.append({"label": key, "points": points, "status": "present"})
            else:
                penalty = min(8, max(3, points // 3))
                score -= penalty
                items.append({"label": f"{key} manquant", "points": -penalty, "status": "missing"})
        score = max(35, min(96, score))
        items.append({"label": "Score", "points": score, "status": "total"})
        return {"score": score, "items": items}

    @staticmethod
    def _versions(project: str) -> dict[str, str]:
        versions = {
            "SolarCalculator": CALCULATOR_VERSIONS["SolarCalculator"],
            "PricingEngine": CALCULATOR_VERSIONS["PricingEngine"],
            "ProductSelector": ProductSelector.version,
            "CompatibilityChecker": CALCULATOR_VERSIONS["CompatibilityChecker"],
            "BOMBuilder": BOMBuilder.version,
        }
        mapping = {
            "pumping": "PumpCalculator",
            "offgrid": "OffGridCalculator",
            "ongrid": "OnGridCalculator",
            "hybrid": "HybridCalculator",
            "thermal": "SolarThermalCalculator",
            "ev": "EVChargerCalculator",
            "iot": "IoTCalculator",
        }
        versions[mapping[project]] = CALCULATOR_VERSIONS[mapping[project]]
        return versions

    @staticmethod
    def _confidence_label(score: int) -> str:
        if score >= 85:
            return "Élevée"
        if score >= 65:
            return "À confirmer"
        return "Visite recommandée"
