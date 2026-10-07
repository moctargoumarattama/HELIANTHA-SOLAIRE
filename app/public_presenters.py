"""Client-facing quote presentation helpers for Phase 4 premium."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from .defaults import PROJECT_LABELS
from .tax import format_currency, line_vat_amount, money


MAIN_COMPONENT_ORDER = ("panels", "inverters", "batteries", "pumps", "drives", "structures")
PUMP_EXISTING_PUBLIC_KEYS_TO_HIDE = {
    "water_need_m3_day",
    "flow_m3_h",
    "static_level_m",
    "dynamic_level_m",
    "reservoir_height_m",
    "horizontal_distance_m",
    "hydraulic_losses_m",
    "hmt_m",
    "hydraulic_power_kw",
    "pump_theoretical_kw",
}
PUMP_EXISTING_PUBLIC_METRIC_KEYWORDS = (
    "débit",
    "debit",
    "hmt",
    "hauteur",
    "profondeur",
    "besoin en eau",
    "m³/j",
    "m3/j",
    "m³/h",
    "m3/h",
)
PUMP_RECOMMENDED_PUBLIC_KEYS = {
    "pump_rule_mode",
    "no_standard_pump",
    "standard_pump_message",
    "selected_pump_cv",
    "selected_outlet_diameter",
    "flow_m3_h",
    "hmt_m",
    "panels",
    "panel_power_w",
    "pv_power_kwp",
    "installed_power_kwp",
    "solar_drive_kw",
    "drive_brand",
    "phase",
    "solar_rule_defined",
}
PUMP_RECOMMENDED_METRIC_KEYWORDS_TO_HIDE = (
    "théorique",
    "rendement",
    "perte hydraulique",
    "marge pv",
    "fallback",
    "stock",
    "référence",
    "reference",
    "product_id",
    "pump_id",
)
PUBLIC_EQUIPMENT_KEYS = {
    "category",
    "financial_category",
    "component",
    "brand",
    "model",
    "description",
    "role",
    "quantity",
    "unit",
    "unit_price",
    "total_price",
    "price_status",
    "currency",
    "vat_rate",
    "power_w",
    "power_kw",
    "power_cv",
    "capacity_kwh",
    "capacity_l",
    "efficiency",
    "technology",
    "warranty",
    "datasheet_url",
}
PUBLIC_TECHNICAL_SPEC_KEYS = {
    "outlet_diameter",
    "power_hp",
    "power_kw",
    "power_w",
    "capacity_kwh",
    "capacity_l",
    "phase",
    "phases",
    "voltage_v",
    "nominal_voltage_v",
    "current_a",
    "technology",
}


def format_decimal_fr(value: Any, decimals: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "À confirmer lors de l'étude technique"
    text = f"{number:,.{decimals}f}"
    return text.replace(",", " ").replace(".", ",")


def format_money_fr(value: Any, currency: str = "DH", decimals: int = 2) -> str:
    try:
        if value is None:
            raise ValueError
        return format_currency(value, currency, decimals)
    except (TypeError, ValueError):
        return f"À confirmer {currency}".strip()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _line_public_amounts(row: dict[str, Any], *, original: dict[str, Any] | None = None) -> None:
    unit_ht = money(_safe_float(row.get("unit_price")))
    total_ht = money(_safe_float(row.get("total_price")))
    # Use the original pump's contractual TTC before private pricing metadata is removed.
    vat = line_vat_amount(original if original is not None else row)
    row["unit_price_ht"] = float(unit_ht)
    row["total_price_ht"] = float(total_ht)
    row["vat_amount"] = float(vat)
    row["total_price_ttc"] = float(money(total_ht + vat))
    row.pop("unit_price", None)
    row.pop("total_price", None)


def _sanitize_public_financial_breakdown(financial: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "project",
        "categories",
        "material_catalog_total",
        "total_ht",
        "vat_rate",
        "vat",
        "total_ttc",
        "currency",
        "pricing_version",
        "vat_breakdown",
        "contains_demo_prices",
        "is_final_price",
    }
    return {key: deepcopy(value) for key, value in (financial or {}).items() if key in allowed}


def _sanitize_public_equipment(
    equipment: list[dict[str, Any]],
    *,
    project: str,
    final: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    final = final or {}
    sanitized = []
    for item in equipment or []:
        category = str(item.get("category") or "").strip()
        row = {key: deepcopy(item.get(key)) for key in PUBLIC_EQUIPMENT_KEYS if key in item}
        specs = item.get("technical_specs") or {}
        safe_specs = {
            key: deepcopy(value)
            for key, value in specs.items()
            if key in PUBLIC_TECHNICAL_SPEC_KEYS
        }
        outlet = safe_specs.get("outlet_diameter") or item.get("outlet_diameter")
        if project == "pumping" and category == "pumps":
            outlet = outlet or final.get("selected_outlet_diameter")
        if outlet:
            row["outlet_diameter"] = outlet
            safe_specs["outlet_diameter"] = outlet
        if project == "pumping" and category == "pumps":
            row["brand"] = ""
            row["model"] = ""
            row["reference"] = ""
        row["technical_specs"] = safe_specs
        _line_public_amounts(row, original=item)
        sanitized.append(row)
    return sanitized


def company_profile(rows: list[dict[str, Any]]) -> dict[str, str]:
    profile = {row.get("key"): row.get("value", "") for row in rows}
    company_name = str(profile.get("company_name") or "HELIANTHA").strip().upper() or "HELIANTHA"
    website = str(profile.get("website") or "").strip()
    website_url = website if website.startswith(("http://", "https://")) else (f"https://{website}" if website else "")
    phone = str(profile.get("phone") or "").strip()
    whatsapp = str(profile.get("whatsapp") or "").strip()
    phone_url = "tel:" + re.sub(r"\s+", "", phone) if phone else ""
    whatsapp_url = "https://wa.me/" + re.sub(r"\D+", "", whatsapp) if whatsapp else ""
    legal_footer = str(profile.get("pdf_legal_footer") or "").strip()
    if "R.C." in legal_footer and ("Siege social" in legal_footer or "Tel." in legal_footer):
        legal_footer = "\n".join(
            line.strip()
            for line in legal_footer.splitlines()
            if line.strip().startswith(("R.C.", "RC", "Patente", "I.F.", "IF", "C.N.S.S.", "CNSS", "ICE"))
        ) or legal_footer
    return {
        "company_name": company_name,
        "phone": phone,
        "phone_url": phone_url,
        "whatsapp": whatsapp,
        "whatsapp_url": whatsapp_url,
        "email": profile.get("email", ""),
        "address": profile.get("address", "Maroc"),
        "website": website,
        "website_url": website_url,
        "location_url": profile.get("location_url", "https://maps.app.goo.gl/xAfGJugGUMye8oSX7"),
        "currency": profile.get("currency", "DH"),
        "pdf_bank_name": profile.get("pdf_bank_name", ""),
        "pdf_rib": profile.get("pdf_rib", ""),
        "pdf_iban": profile.get("pdf_iban", ""),
        "pdf_contact_name": profile.get("pdf_contact_name", ""),
        "pdf_social_links": profile.get("pdf_social_links", ""),
        "pdf_legal_footer": legal_footer,
    }


def compatibility_label(status: str | None) -> str:
    return {
        "compatible": "Configuration vérifiée",
        "compatible_with_warning": "Vérification finale HeliAntha",
        "manual_validation_required": "Vérification finale HeliAntha",
        "incompatible": "HeliAntha vérifiera la configuration",
    }.get(status or "", "HeliAntha finalise les derniers détails")


def compatibility_tone(status: str | None) -> str:
    return {
        "compatible": "ok",
        "compatible_with_warning": "warning",
        "manual_validation_required": "warning",
        "incompatible": "critical",
    }.get(status or "", "warning")


def client_warning_text(item: dict[str, Any]) -> str:
    code = str(item.get("code") or "")
    mapping = {
        "PV_PANEL_FALLBACK_USED": "Équipements proposés par HeliAntha.",
        "PV_STRING_VALIDATION_REQUIRED": "HeliAntha vérifiera le câblage final.",
        "PUMP_EFFICIENCY_FALLBACK_USED": "Pompe préparée pour la validation finale.",
        "DRIVE_EFFICIENCY_FALLBACK_USED": "Variateur préparé pour la validation finale.",
        "ROOF_AREA_LIMIT": "Implantation à vérifier sur site.",
        "PRODUCT_DATA_INCOMPLETE": "Détails techniques finalisés avant installation.",
        "DEMO_PRODUCT_SELECTED": "Référence finale confirmée par HeliAntha.",
        "CATALOG_STOCK_TO_CONFIRM": "Disponibilité vérifiée à la commande.",
        "PROTECTION_SIZING_REQUIRED": "Protections finalisées avant installation.",
        "CABLE_SIZING_REQUIRED": "Câblage finalisé avant installation.",
        "STRUCTURE_SELECTION_REQUIRED": "Support ajusté selon le site.",
        "PUMP_FLOW_VALIDATION_REQUIRED": "Débit vérifié selon le site.",
        "PUMP_HEAD_VALIDATION_REQUIRED": "HMT vérifiée lors de l’étude.",
        "PUMP_DRIVE_VALIDATION_REQUIRED": "Compatibilité vérifiée avant installation.",
        "NO_COMPATIBLE_PANEL": "HeliAntha proposera la meilleure référence.",
        "NO_COMPATIBLE_PUMP": "HeliAntha proposera la meilleure référence.",
        "NO_STANDARD_PUMP": "Aucune pompe standard ne couvre ce besoin. Une configuration HeliAntha personnalisée est nécessaire.",
        "NO_COMPATIBLE_DRIVE": "HeliAntha proposera la meilleure référence.",
        "HYBRID_STORAGE_SIMPLIFIED": "Stockage préparé pour votre projet.",
        "HOT_WATER_ESTIMATED": "Besoin préparé à partir de vos réponses.",
    }
    return mapping.get(code, str(item.get("message") or "HeliAntha finalise les derniers détails."))


def offer_signature(offer: dict[str, Any]) -> tuple[Any, ...]:
    equipment = tuple(
        sorted(
            (
                item.get("category"),
                item.get("reference"),
                float(item.get("quantity") or 0),
                float(item.get("total_price") or 0),
            )
            for item in (offer.get("selected_equipment") or [])
        )
    )
    return (
        float(money(offer.get("ttc"))),
        float(money(offer.get("ht"))),
        equipment,
    )


def _main_components(
    equipment: list[dict[str, Any]],
    *,
    project: str = "",
    final: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    final = final or {}
    ordered = sorted(
        equipment,
        key=lambda item: (
            MAIN_COMPONENT_ORDER.index(item.get("category")) if item.get("category") in MAIN_COMPONENT_ORDER else 99,
            item.get("role") or "",
        ),
    )
    result = []
    for item in ordered:
        category = item.get("category")
        if category not in MAIN_COMPONENT_ORDER:
            continue
        specs = item.get("technical_specs") or {}
        power_cv = item.get("power_cv") or specs.get("power_hp")
        outlet_diameter = specs.get("outlet_diameter") or item.get("outlet_diameter")
        if category == "pumps" and project == "pumping":
            outlet_diameter = outlet_diameter or final.get("selected_outlet_diameter")
        if category == "pumps" and project == "pumping":
            power_cv = power_cv or final.get("selected_pump_cv")
            title = f"Pompe solaire {format_decimal_fr(power_cv, 1)} CV" if power_cv else "Pompe solaire"
        else:
            title = " ".join(part for part in (item.get("brand"), item.get("model")) if part) or item.get("description") or "Matériel à confirmer"
        quantity = item.get("quantity") or 1
        power_kw = item.get("power_kw")
        power_w = item.get("power_w")
        raw_source_type = item.get("source_type") or item.get("source", {}).get("source_type") or ""
        summary = ""
        if category == "panels" and power_w:
            summary = f"{int(quantity)} × {format_decimal_fr(power_w, 0)} W"
        elif category == "pumps" and power_cv:
            summary = f"{format_decimal_fr(power_cv, 1)} CV"
            if outlet_diameter:
                summary = f"{summary} - Refoulement {outlet_diameter}"
        elif category == "batteries":
            capacity = item.get("capacity_kwh") or specs.get("capacity_kwh")
            total_capacity = _safe_float(capacity) * _safe_float(quantity, 1)
            summary = f"{int(quantity)} × {format_decimal_fr(capacity, 0)} kWh"
            if total_capacity:
                summary = f"{summary} - Total {format_decimal_fr(total_capacity, 0)} kWh"
        elif power_kw:
            summary = f"{format_decimal_fr(power_kw)} kW"
        elif category == "structures":
            summary = f"{int(quantity)} support(s)"
        else:
            summary = f"{int(quantity)} unité(s)"
        result.append({
            "category": category,
            "role": item.get("role") or category,
            "title": title,
            "summary": summary,
            "reference": "" if project == "pumping" else (item.get("reference") or ""),
            "quantity": quantity,
            "outlet_diameter": outlet_diameter or "",
            "source_type": "" if project == "pumping" and raw_source_type == "fallback" else ("heliantha" if raw_source_type == "demo" else raw_source_type),
        })
    return result[:6]


def _diagram_data(project: str, offer: dict[str, Any], final: dict[str, Any]) -> dict[str, Any]:
    components = {
        item["category"]: item
        for item in _main_components(offer.get("selected_equipment") or [], project=project, final=final)
    }
    diagram = {
        "project": project,
        "panel": components.get("panels"),
        "inverter": components.get("inverters"),
        "battery": components.get("batteries"),
        "pump": components.get("pumps"),
        "drive": components.get("drives"),
        "structure": components.get("structures"),
        "panel_count": final.get("panels"),
        "ongrid_panel_count": final.get("panel_count"),
        "installed_power_kwp": final.get("installed_power_kwp"),
        "string_layout": final.get("string_layout"),
        "flow_m3_h": final.get("flow_m3_h"),
        "hmt_m": final.get("hmt_m"),
    }
    if _is_existing_pump_public_mode(project, final):
        diagram.pop("flow_m3_h", None)
        diagram.pop("hmt_m", None)
    return diagram


def _is_existing_pump_public_mode(project: str, final: dict[str, Any]) -> bool:
    return project == "pumping" and str(final.get("pump_rule_mode") or "").strip().lower() == "existing_pump_cv"


def _is_recommended_pump_public_mode(project: str, final: dict[str, Any]) -> bool:
    return project == "pumping" and str(final.get("pump_rule_mode") or "").strip().lower() in {
        "recommended_curve",
        "no_standard_pump",
    }


def _sanitize_public_final_results(project: str, final: dict[str, Any]) -> dict[str, Any]:
    sanitized = deepcopy(final)
    if _is_existing_pump_public_mode(project, sanitized):
        for key in PUMP_EXISTING_PUBLIC_KEYS_TO_HIDE:
            sanitized.pop(key, None)
    elif _is_recommended_pump_public_mode(project, sanitized):
        sanitized = {
            key: value
            for key, value in sanitized.items()
            if key in PUMP_RECOMMENDED_PUBLIC_KEYS
        }
    return sanitized


def _sanitize_public_metrics(project: str, final: dict[str, Any], metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if _is_recommended_pump_public_mode(project, final):
        cleaned = []
        for item in metrics or []:
            blob = " ".join(str(item.get(key) or "") for key in ("label", "value", "note")).strip().lower()
            if any(keyword in blob for keyword in PUMP_RECOMMENDED_METRIC_KEYWORDS_TO_HIDE):
                continue
            cleaned.append(item)
        return cleaned
    if not _is_existing_pump_public_mode(project, final):
        return metrics
    cleaned = []
    for item in metrics or []:
        label = str(item.get("label") or "").strip().lower()
        value = str(item.get("value") or "").strip().lower()
        if any(keyword in label or keyword in value for keyword in PUMP_EXISTING_PUBLIC_METRIC_KEYWORDS):
            continue
        cleaned.append(item)
    return cleaned


def _normalize_offer(project: str, offer: dict[str, Any], final: dict[str, Any], currency: str) -> dict[str, Any]:
    normalized = deepcopy(offer)
    displayed_price = offer.get("ttc") if offer.get("ttc") is not None else offer.get("ht")
    normalized["price_label"] = format_money_fr(displayed_price, currency)
    normalized["price_ttc_label"] = format_money_fr(offer.get("ttc"), currency)
    normalized["price_ht_label"] = format_money_fr(offer.get("ht"), currency)
    normalized.pop("tax_basis_confirmation_required", None)
    normalized.pop("pump_price_tax_basis", None)
    normalized.pop("price_tax_note", None)
    if project in {"pumping", "photovoltaic", "hybrid"}:
        normalized["selected_equipment"] = _sanitize_public_equipment(
            offer.get("selected_equipment") or [],
            project=project,
            final=final,
        )
        normalized["financial_breakdown"] = _sanitize_public_financial_breakdown(offer.get("financial_breakdown") or {})
    normalized["main_components"] = _main_components(
        offer.get("selected_equipment") or [],
        project=project,
        final=final,
    )
    normalized["diagram"] = _diagram_data(project, offer, final)
    return normalized


def sanitize_calculation_result_for_public(result: dict[str, Any]) -> dict[str, Any]:
    """Return a client-safe calculate payload for public simulations."""

    cleaned = deepcopy(result)
    project = cleaned.get("project") or cleaned.get("project_type") or ""
    if project not in {"pumping", "photovoltaic", "hybrid"}:
        return cleaned

    final = _sanitize_public_final_results(project, cleaned.get("final_results") or {})
    cleaned["final_results"] = final
    cleaned["metrics"] = _sanitize_public_metrics(project, final, cleaned.get("metrics") or [])
    cleaned["selected_equipment"] = _sanitize_public_equipment(
        cleaned.get("selected_equipment") or [],
        project=project,
        final=final,
    )
    cleaned["financial_breakdown"] = _sanitize_public_financial_breakdown(cleaned.get("financial_breakdown") or {})
    currency = (cleaned.get("financial_breakdown") or {}).get("currency") or "DH"
    cleaned["offers"] = [
        _normalize_offer(project, offer, final, currency)
        for offer in (cleaned.get("offers") or [])
    ]
    for key in (
        "assumptions",
        "parameters_used",
        "intermediate_results",
        "calculation_blocks",
        "resolved_sources",
        "reasoning_steps",
        "calculation_detail",
        "technical_configuration",
        "compatibility",
        "product_selections",
        "bom",
        "technical_reference",
        "quote_snapshot",
    ):
        cleaned.pop(key, None)
    return cleaned


def build_public_quote_payload(quote: dict[str, Any], company: dict[str, str]) -> dict[str, Any]:
    result = quote.get("result") or {}
    final = result.get("final_results") or quote.get("calculation_detail", {}).get("final_results", {}) or {}
    final = _sanitize_public_final_results(quote.get("project", ""), final)
    compatibility = quote.get("compatibility") or quote.get("calculation_detail", {}).get("compatibility", {}) or {}
    metrics = _sanitize_public_metrics(quote.get("project", ""), final, result.get("metrics") or [])
    raw_offers = result.get("offers") or []
    unique_offers = []
    seen = set()
    for offer in raw_offers:
        signature = offer_signature(offer)
        if signature in seen:
            continue
        seen.add(signature)
        unique_offers.append(_normalize_offer(quote.get("project", ""), offer, final, company.get("currency", "DH")))
    if not unique_offers and raw_offers:
        unique_offers = [_normalize_offer(quote.get("project", ""), raw_offers[0], final, company.get("currency", "DH"))]

    selected_level = quote.get("selected_offer_level") or ""
    recommended_offer = next((offer for offer in unique_offers if offer.get("level") == selected_level), None)
    if not recommended_offer:
        recommended_offer = next((offer for offer in unique_offers if offer.get("recommended")), None)
    if not recommended_offer and unique_offers:
        recommended_offer = unique_offers[0]

    warnings = []
    seen_texts = set()
    for item in quote.get("calculation_detail", {}).get("warnings", []):
        code = str(item.get("code") or "").strip().upper()
        if _is_existing_pump_public_mode(quote.get("project", ""), final) and code.startswith("PUMP_"):
            continue
        if _is_recommended_pump_public_mode(quote.get("project", ""), final) and ("FALLBACK" in code or "STOCK" in code):
            continue
        text = client_warning_text(item)
        if text in seen_texts:
            continue
        seen_texts.add(text)
        warnings.append({
            "level": item.get("level", "warning"),
            "text": text,
        })

    confidence_items = []
    for item in (quote.get("reliability") or {}).get("items", []):
        label = str(item.get("label") or "").strip()
        if not label or label == "Score":
            continue
        points = int(item.get("points") or 0)
        confidence_items.append({
            "label": label,
            "points": points,
            "tone": "positive" if points >= 0 else "warning",
        })

    public_view = {
        "quote_number": quote.get("quote_number"),
        "simulation_label": f"Simulation {quote.get('quote_number')}",
        "created_at": quote.get("created_at", ""),
        "project": quote.get("project", ""),
        "project_label": PROJECT_LABELS.get(quote.get("project", ""), quote.get("project", "")),
        "title": result.get("title") or "",
        "summary": result.get("summary") or "",
        "metrics": metrics,
        "confidence": int(result.get("confidence") or (quote.get("reliability") or {}).get("score") or 0),
        "confidence_label": result.get("confidence_label") or "",
        "confidence_items": confidence_items,
        "warnings": warnings,
        "compatibility": {
            "status": compatibility.get("status", "manual_validation_required"),
            "label": compatibility_label(compatibility.get("status")),
            "tone": compatibility_tone(compatibility.get("status")),
        },
        "offers": unique_offers,
        "recommended_offer": recommended_offer,
        "has_multiple_offers": len(unique_offers) > 1,
        "final_results": final,
        "material_confirmation_required": any(
            item.get("source_type") in {"fallback", "manual_validation"}
            for item in (recommended_offer or {}).get("main_components", [])
        ),
        "contact": company,
        "selected_offer_level": selected_level,
        "visit_requests": quote.get("visit_requests") or [],
    }
    return public_view
