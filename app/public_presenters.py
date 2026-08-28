"""Client-facing quote presentation helpers for Phase 4 premium."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from .defaults import PROJECT_LABELS


MAIN_COMPONENT_ORDER = ("panels", "inverters", "batteries", "pumps", "drives", "thermal", "ev_chargers")


def format_decimal_fr(value: Any, decimals: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "À confirmer lors de l'étude technique"
    text = f"{number:,.{decimals}f}"
    return text.replace(",", " ").replace(".", ",")


def format_money_fr(value: Any, currency: str = "DH", decimals: int = 0) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return f"À confirmer {currency}".strip()
    text = f"{number:,.{decimals}f}"
    return f"{text.replace(',', ' ').replace('.', ',')} {currency}".strip()


def company_profile(rows: list[dict[str, Any]]) -> dict[str, str]:
    profile = {row.get("key"): row.get("value", "") for row in rows}
    company_name = str(profile.get("company_name") or "HELIANTHA").strip().upper() or "HELIANTHA"
    website = str(profile.get("website") or "").strip()
    website_url = website if website.startswith(("http://", "https://")) else (f"https://{website}" if website else "")
    phone = str(profile.get("phone") or "").strip()
    whatsapp = str(profile.get("whatsapp") or "").strip()
    return {
        "company_name": company_name,
        "phone": phone,
        "phone_url": f"tel:{re.sub(r'\s+', '', phone)}" if phone else "",
        "whatsapp": whatsapp,
        "whatsapp_url": f"https://wa.me/{re.sub(r'\D+', '', whatsapp)}" if whatsapp else "",
        "email": profile.get("email", ""),
        "address": profile.get("address", "Maroc"),
        "website": website,
        "website_url": website_url,
        "location_url": profile.get("location_url", "https://maps.app.goo.gl/xAfGJugGUMye8oSX7"),
        "quote_validity_days": profile.get("quote_validity_days", "15"),
        "currency": profile.get("currency", "DH"),
        "pdf_footer": profile.get("pdf_footer", ""),
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
        "PSH_FALLBACK_USED": "Données solaires prises en compte par HeliAntha.",
        "PV_PANEL_FALLBACK_USED": "Équipements proposés par HeliAntha.",
        "PV_STRING_VALIDATION_REQUIRED": "HeliAntha vérifiera le câblage final.",
        "BATTERY_DOD_FALLBACK_USED": "Réglage batterie préparé par HeliAntha.",
        "PUMP_EFFICIENCY_FALLBACK_USED": "Pompe préparée pour la validation finale.",
        "DRIVE_EFFICIENCY_FALLBACK_USED": "Variateur préparé pour la validation finale.",
        "EV_SAFETY_MARGIN_LOW": "HeliAntha vérifiera l’alimentation finale.",
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
        "EV_NETWORK_VALIDATION_REQUIRED": "Borne validée avec l’installation.",
        "NO_COMPATIBLE_PANEL": "HeliAntha proposera la meilleure référence.",
        "NO_COMPATIBLE_BATTERY": "HeliAntha proposera la meilleure référence.",
        "NO_COMPATIBLE_INVERTER": "HeliAntha proposera la meilleure référence.",
        "NO_COMPATIBLE_PUMP": "HeliAntha proposera la meilleure référence.",
        "NO_COMPATIBLE_DRIVE": "HeliAntha proposera la meilleure référence.",
        "NO_COMPATIBLE_EV_CHARGER": "HeliAntha proposera la meilleure référence.",
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
        round(float(offer.get("ttc") or 0), 2),
        round(float(offer.get("ht") or 0), 2),
        equipment,
    )


def _main_components(equipment: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
        title = " ".join(part for part in (item.get("brand"), item.get("model")) if part) or item.get("description") or "Matériel à confirmer"
        quantity = item.get("quantity") or 1
        capacity = item.get("capacity_kwh")
        power_kw = item.get("power_kw")
        power_w = item.get("power_w")
        summary = ""
        if category == "panels" and power_w:
            summary = f"{int(quantity)} × {format_decimal_fr(power_w, 0)} W"
        elif category == "batteries" and capacity:
            summary = f"{int(quantity)} × {format_decimal_fr(capacity)} kWh"
        elif power_kw:
            summary = f"{format_decimal_fr(power_kw)} kW"
        elif capacity:
            summary = f"{format_decimal_fr(capacity)} kWh"
        elif item.get("capacity_l"):
            summary = f"{format_decimal_fr(item.get('capacity_l'), 0)} L"
        else:
            summary = f"{int(quantity)} unité(s)"
        result.append({
            "category": category,
            "role": item.get("role") or category,
            "title": title,
            "summary": summary,
            "reference": item.get("reference") or "",
            "quantity": quantity,
            "source_type": "heliantha" if (item.get("source_type") or item.get("source", {}).get("source_type") or "") == "demo" else (item.get("source_type") or item.get("source", {}).get("source_type") or ""),
        })
    return result[:6]


def _diagram_data(project: str, offer: dict[str, Any], final: dict[str, Any]) -> dict[str, Any]:
    components = {item["category"]: item for item in _main_components(offer.get("selected_equipment") or [])}
    return {
        "project": project,
        "panel": components.get("panels"),
        "inverter": components.get("inverters"),
        "battery": components.get("batteries"),
        "pump": components.get("pumps"),
        "drive": components.get("drives"),
        "charger": components.get("ev_chargers"),
        "thermal": components.get("thermal"),
        "panel_count": final.get("panels"),
        "flow_m3_h": final.get("flow_m3_h"),
        "hmt_m": final.get("hmt_m"),
        "autonomy_days": final.get("autonomy_days"),
    }


def _normalize_offer(project: str, offer: dict[str, Any], final: dict[str, Any], currency: str) -> dict[str, Any]:
    normalized = deepcopy(offer)
    normalized["price_ttc_label"] = format_money_fr(offer.get("ttc"), currency)
    normalized["price_ht_label"] = format_money_fr(offer.get("ht"), currency)
    normalized["main_components"] = _main_components(offer.get("selected_equipment") or [])
    normalized["diagram"] = _diagram_data(project, offer, final)
    return normalized


def build_public_quote_payload(quote: dict[str, Any], company: dict[str, str]) -> dict[str, Any]:
    result = quote.get("result") or {}
    final = result.get("final_results") or quote.get("calculation_detail", {}).get("final_results", {}) or {}
    compatibility = quote.get("compatibility") or quote.get("calculation_detail", {}).get("compatibility", {}) or {}
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
        "metrics": result.get("metrics") or [],
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
