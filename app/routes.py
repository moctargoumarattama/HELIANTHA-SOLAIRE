from copy import deepcopy
from datetime import datetime
from json import dumps as json_dumps
from pathlib import Path
from random import randint
import re
from urllib.parse import quote_plus
from uuid import uuid4

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    stream_with_context,
    url_for,
)
from werkzeug.http import quote_header_value

from .catalog import ProductValidationError, category_label, category_options, technical_fields_by_category
from .calculators import CalculationEngine, ValidationError
from .db import (
    dashboard_stats,
    authenticate_user,
    get_product,
    get_quote,
    get_primary_admin_user,
    get_user,
    get_quote_by_number,
    list_company_settings,
    list_pumping_solar_rules,
    list_ongrid_parameters,
    list_products,
    list_quotes,
    list_users,
    list_vat_rates,
    list_whatsapp_outbox,
    load_calculation_context,
    save_user,
    save_product,
    save_quote,
    save_quote_client_event,
    save_visit_request,
    create_pumping_solar_rule,
    delete_user,
    set_product_active,
    update_company_settings,
    update_ongrid_parameters,
    update_pumping_solar_rule,
    update_quote_selected_offer,
    update_quote_status,
    update_vat_rates,
)
from .defaults import PROJECT_LABELS, PUBLIC_PROJECTS
from .admin_quotes import ADMIN_QUOTE_STATUSES, display_quote_status, group_quotes_by_client
from .tax import (
    VAT_FIELDS,
    VAT_PROFILES,
    TaxValidationError,
    format_currency,
    line_vat_amount,
    money,
    parse_vat_percentage,
    vat_rate_for_component,
)
from .pumping_rules import (
    PUMPING_RULE_SECTIONS,
    format_cv,
    format_phase,
    format_power_kw,
    format_power_w,
    format_price,
    group_rules,
    normalize_pump_cv,
    parse_number,
)
from .public_presenters import build_public_quote_payload, company_profile, sanitize_calculation_result_for_public
from .services.anti_abuse import ASSISTANT_WAIT_MESSAGE
from .services.assistant_devis import AssistantDevisManager, extract_phase
from .services.ai_service import (
    can_use_quote_manager,
    chat_with_ollama,
    extract_quote_request,
    find_catalog_products,
    is_catalog_query,
    quick_assistant_response,
    quick_solar_power_response,
    sanitize_messages,
    stream_ollama_chat,
)
from .services.pump_selector import NO_STANDARD_PUMP_MESSAGE, curve_head_for_flow, select_pump_for_duty
from .services.pump_pricing import calculate_pump_sale_price
from .services.pdf_service import build_quote_pdf
from .services.whatsapp_service import (
    gateway_logout,
    get_gateway_qr,
    get_gateway_status,
    notify_quote_created,
    process_outbox,
    send_whatsapp_raw,
)
from .wizard_projects import engine_project_for, normalize_wizard_project
from .transport import TRANSPORT_DESCRIPTION, TRANSPORT_KEYS, TransportValidationError


bp = Blueprint("main", __name__)
bp.add_app_template_filter(format_currency)
engine = CalculationEngine()
assistant_devis_manager = AssistantDevisManager()
CATALOG_SORT_OPTIONS = [
    {"value": "catalog", "label": "Ordre catalogue"},
    {"value": "brand", "label": "Marque"},
    {"value": "price_asc", "label": "Prix croissant"},
    {"value": "price_desc", "label": "Prix decroissant"},
    {"value": "updated", "label": "Derniere mise a jour"},
]
HIDDEN_COMPANY_SETTING_KEYS = {
    "pdf_amount_note",
    "pdf_check_payee",
    "pdf_check_address",
    "pdf_contact_phone",
    "pdf_contact_email",
    "pdf_footer",
    "pdf_payment_terms",
    "quote_validity_days",
}

def _is_placeholder_equipment_line(item: dict) -> bool:
    text_blob = " ".join(
        str(item.get(field) or "")
        for field in ("reference", "brand", "model", "description", "role")
    ).lower()
    model_blob = str(item.get("model") or "").lower()
    description_blob = str(item.get("description") or "").lower()
    reference_blob = str(item.get("reference") or "").strip()
    quantity = float(item.get("quantity") or 0)
    unit_price = float(item.get("unit_price") or 0)
    total_price = float(item.get("total_price") or 0)
    return (
        item.get("price_status") == "to_confirm"
        and item.get("product_id") is None
        and total_price <= 0
        and unit_price <= 0
        and (
            not reference_blob
            or "confirm" in model_blob
            or "confirm" in description_blob
            or "confirm" in text_blob
        )
        and quantity > 0
    )


def _display_equipment_lines(lines):
    display_lines = []

    def clean_number(value, digits=1):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return ""
        if digits <= 0:
            return f"{number:.0f}"
        text = f"{number:.{digits}f}".rstrip("0").rstrip(".")
        return text

    def phase_short(value):
        label = str(value or "").strip().lower()
        if "tri" in label:
            return "tri"
        if "mono" in label:
            return "mono"
        return ""

    def simple_designation(row, specs):
        component = str(row.get("component") or "").strip().lower()
        category = str(row.get("category") or "").strip().lower()
        role = str(row.get("role") or "").strip().lower()

        if component == "transport" or category == "transport":
            return TRANSPORT_DESCRIPTION

        power_cv = row.get("power_cv") or specs.get("power_hp")
        if category == "pumps":
            cv_label = clean_number(power_cv, 1)
            outlet = str(specs.get("outlet_diameter") or row.get("outlet_diameter") or "").strip()
            designation = f"Pompe solaire {cv_label} CV" if cv_label else "Pompe solaire"
            return f"{designation} - Refoulement {outlet}" if outlet else designation

        power_w = row.get("power_w") or specs.get("power_w") or specs.get("panel_power_w")
        if component == "panel" or category == "panels":
            power_label = clean_number(power_w, 0)
            return f"Panneaux photovoltaïques {power_label} Wc" if power_label else "Panneaux photovoltaïques"

        capacity_kwh = row.get("capacity_kwh") or specs.get("capacity_kwh")
        if component == "battery" or category == "batteries":
            quantity = clean_number(row.get("quantity") or 1, 0) or "1"
            capacity_label = clean_number(capacity_kwh, 0)
            if capacity_label:
                total_label = clean_number(float(row.get("quantity") or 1) * float(capacity_kwh or 0), 0)
                return f"Stockage Lithium {quantity}x Batterie {capacity_label} kWh - Total {total_label} kWh"
            return "Stockage Lithium"

        power_kw = row.get("power_kw") or specs.get("power_kw")
        if component in {"pump_drive", "drive"} or category == "drives" or "variateur" in role:
            brand = str(row.get("brand") or "").strip()
            power_label = clean_number(power_kw, 1)
            phase_label = phase_short(row.get("model") or specs.get("phase") or specs.get("phases"))
            parts = ["Variateur"]
            if brand:
                parts.append(brand)
            if power_label:
                parts.append(f"{power_label} kW")
            if phase_label:
                parts.append(phase_label)
            return " ".join(parts)

        if component == "structure" or category == "structures" or "structure" in role:
            power_label = clean_number(power_w, 0)
            return f"Structure pour panneaux {power_label} Wc" if power_label else "Structure pour panneaux"

        if component == "coffret" or category == "protections" or "coffret" in role:
            phase_label = phase_short(row.get("model") or specs.get("phase") or specs.get("phases"))
            return f"Coffret de protection {phase_label}" if phase_label else "Coffret de protection"

        if component == "cabling_accessories" or category == "cables":
            return "Câblage et accessoires"

        if component == "installation" or category == "services" or "installation" in role:
            return "Installation et mise en service"

        return row.get("description") or row.get("model") or row.get("role") or "Élément du devis"

    for item in lines or []:
        if _is_placeholder_equipment_line(item):
            continue
        row = deepcopy(item)
        specs = row.get("technical_specs") or {}
        row["display_reference"] = ""
        row["display_designation"] = simple_designation(row, specs)
        unit_ht = money(row.get("unit_price") or 0)
        total_ht = money(row.get("total_price") or 0)
        vat_rate = float(row.get("vat_rate") or 0)
        row["display_unit_price_ht"] = float(unit_ht)
        row["display_total_price_ht"] = float(total_ht)
        row["display_vat_rate"] = f"{clean_number(vat_rate * 100, 1)} %"
        line_vat = line_vat_amount(row)
        row["display_vat_amount"] = float(line_vat)
        row["display_total_ttc"] = float(money(total_ht + line_vat))
        display_lines.append(row)
    return display_lines


def _financial_summary_rows(financial_breakdown: dict) -> list[dict]:
    categories = {
        item.get("key"): money(item.get("amount") or 0)
        for item in (financial_breakdown.get("categories") or [])
    }

    def total(*keys: str) -> float:
        return float(money(sum(categories.get(key, 0) for key in keys)))

    return [
        {"label": "Matériel", "amount": total("principal_equipment")},
        {"label": "Compléments", "amount": total("accessories", "protections", "cabling", "structure")},
        {"label": "Transport", "amount": total("transport")},
        {"label": "Pose", "amount": total("installation", "labor")},
        {"label": "Total HT", "amount": float(financial_breakdown.get("total_ht") or 0), "emphasis": True},
        {"label": "TVA", "amount": float(financial_breakdown.get("vat") or 0)},
        {"label": "Net à payer", "amount": float(financial_breakdown.get("total_ttc") or 0), "emphasis": True},
    ]


def _project_label_for_notification(project: str) -> str:
    return {
        "photovoltaic": "Installation solaire raccordee reseau",
        "pumping": "Pompage solaire",
    }.get(project, PROJECT_LABELS.get(project, "Projet Solaire"))


def _quote_pdf_filename(quote_number="", quote_id=None) -> str:
    official_number = str(quote_number or "").strip()
    if official_number:
        return f"Devis_{official_number}.pdf"
    fallback_id = str(quote_id or "client").strip()
    return f"Devis_HeliAntha_{fallback_id}.pdf"


def _notify_quote_created_safely(
    *,
    quote_id: int,
    project: str,
    contact: dict,
    data: dict,
    result: dict,
) -> None:
    if current_app.config.get("TESTING"):
        return
    try:
        settings = {row.get("key"): row.get("value", "") for row in list_company_settings()}
        notify_quote_created(
            {
                "client_name": contact.get("name") or "Client",
                "client_phone": contact.get("phone") or "",
                "city": data.get("city") or contact.get("location") or "",
                "project_type": _project_label_for_notification(project),
                "total_ttc": _money_label((result.get("financial_breakdown") or {}).get("total_ttc")),
                "pdf_url": url_for("main.public_quote_document_by_id", quote_id=quote_id),
                "pdf_filename": _quote_pdf_filename(result.get("quote_number") or result.get("reference"), quote_id),
                "whatsapp_gateway_url": settings.get("whatsapp_gateway_url"),
                "admin_whatsapp": settings.get("admin_whatsapp"),
                "app_base_url": settings.get("app_base_url"),
            },
            dispatch_immediately=False,
        )
    except Exception:
        current_app.logger.exception("WhatsApp quote notification failed")


def _quote_pdf_response(quote: dict):
    company = company_profile(list_company_settings())
    display_equipment_lines = _display_equipment_lines(quote.get("selected_equipment") or [])
    financial_summary_rows = _financial_summary_rows(quote.get("financial_breakdown") or {})
    pdf_bytes = build_quote_pdf(
        quote=quote,
        company=company,
        display_equipment_lines=display_equipment_lines,
        financial_summary_rows=financial_summary_rows,
    )
    filename = _quote_pdf_filename(quote.get("quote_number") or quote.get("reference"), quote.get("id"))
    response = current_app.response_class(pdf_bytes, mimetype="application/pdf")
    response.headers["Content-Disposition"] = f"inline; filename={quote_header_value(filename)}"
    response.headers["Content-Length"] = str(len(pdf_bytes))
    return response


def _quote_json_response(quote: dict):
    company = company_profile(list_company_settings())
    payload = build_public_quote_payload(quote, company)
    payload["quote_id"] = quote.get("id")
    payload["pdf_url"] = url_for("main.api_quote_document_by_id", quote_id=quote["id"])
    payload["document_url"] = payload["pdf_url"]
    payload["api_url"] = url_for("main.api_quote_by_id", quote_id=quote["id"])
    return jsonify(payload)


def _whatsapp_admin_settings() -> dict[str, str]:
    settings = {row.get("key"): row.get("value", "") for row in list_company_settings()}
    return {
        "gateway_url": settings.get("whatsapp_gateway_url") or "http://127.0.0.1:3001/send-message",
        "admin_whatsapp": settings.get("admin_whatsapp") or "",
        "app_base_url": settings.get("app_base_url") or "",
    }



@bp.before_app_request
def protect_admin():
    if not request.path.startswith("/admin"):
        return None
    if request.endpoint in {"main.admin_login"}:
        return None
    if session.get("admin_user"):
        return None
    return redirect(url_for("main.admin_login", next=request.full_path))


@bp.get("/")
def index():
    return jsonify(status="online", service="HeliAntha Engine API", version="2.0")


@bp.get("/politique-confidentialite")
def privacy_policy():
    return jsonify(error="Les pages publiques web ont ete retirees. Utilisez l'application Flutter."), 410


@bp.get("/assets/heliantha-terrain.jpeg")
@bp.get("/assets/helin.jpeg")
def brand_image():
    return send_file(Path(__file__).resolve().parent.parent / "helin.jpeg", mimetype="image/jpeg")


@bp.get("/health")
def health():
    return jsonify(status="ok", engine=engine.version)



@bp.post("/api/calculate")
def calculate():
    payload = request.get_json(silent=True) or {}
    project = normalize_wizard_project(payload.get("project_type") or payload.get("project") or "")
    if project not in {"pumping", "photovoltaic", "hybrid"}:
        return jsonify(error="Ce parcours est bientot disponible."), 410
    engine_project = engine_project_for(project)
    data = payload.get("data") or {}
    contact = payload.get("contact") or {}
    try:
        result = engine.calculate(engine_project, data, context=load_calculation_context())
    except ValidationError as exc:
        return jsonify(error=str(exc)), 400
    except Exception:
        current_app.logger.exception("HeliAntha calculate failed for project=%s", engine_project)
        return jsonify(error="Nous n'avons pas pu terminer l'étude. Vérifiez vos informations ou réessayez."), 500

    result["quote_number"] = f"HSQ-{datetime.now():%Y%m%d}-{randint(1000, 9999)}"
    result["created_at"] = datetime.now().strftime("%d/%m/%Y à %H:%M")
    result["project_type"] = project
    quote_id = save_quote(result["quote_number"], engine_project, data, contact, result)
    _notify_quote_created_safely(
        quote_id=quote_id,
        project=engine_project,
        contact=contact,
        data=data,
        result=result,
    )
    result["quote_id"] = quote_id
    result["quote_url"] = url_for("main.api_quote_by_id", quote_id=quote_id)
    result["pdf_url"] = url_for("main.api_quote_document_by_id", quote_id=quote_id)
    result["public_url"] = result["quote_url"]
    public_result = sanitize_calculation_result_for_public(result)
    return jsonify(public_result)


def _ai_text(data: dict, *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _ai_float(data: dict, *keys: str, default: float = 0.0) -> float:
    for key in keys:
        value = data.get(key)
        if value is None or value == "":
            continue
        try:
            return float(str(value).strip().replace(",", "."))
        except ValueError:
            continue
    return default


def _ai_phase(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"tri", "triphase", "triphasé", "triphasee", "three_phase"}:
        return "triphase"
    return "monophase"


def _money_label(value) -> str:
    try:
        return format_currency(value, decimals=0)
    except ValueError:
        return format_currency(0, decimals=0)


def _quote_summary(project: str, result: dict) -> str:
    final = result.get("final_results") or {}
    if project == "photovoltaic":
        power = final.get("installed_power_kwp") or final.get("target_kwp")
        panels = final.get("panel_count")
        if power:
            return f"Systeme solaire {float(power):.2f} kWc".replace(".", ",")
        if panels:
            return f"Systeme solaire {panels} panneaux"
        return "Systeme solaire On-Grid"
    if project == "hybrid":
        storage = final.get("battery_total_capacity_kwh")
        panels = final.get("panel_count")
        if storage:
            return f"Solaire hybride {float(storage):g} kWh lithium"
        if panels:
            return f"Solaire hybride {panels} panneaux"
        return "Solaire hybride avec batteries"
    pump_cv = final.get("selected_pump_cv") or final.get("pump_power_cv")
    if pump_cv:
        return f"Pompage solaire {float(pump_cv):g} CV"
    return "Solution pompage solaire"


def _result_kwc(final: dict) -> float | str:
    value = final.get("installed_power_kwp") or final.get("pv_power_kwp")
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return ""


def _result_panel_count(final: dict) -> int | str:
    value = final.get("panel_count") or final.get("panels")
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return ""


def _result_inverter_label(project: str, final: dict) -> str:
    if project == "pumping":
        power = final.get("solar_drive_kw")
        brand = str(final.get("drive_brand") or "").strip()
        if power:
            try:
                power_label = f"{float(power):g} kW"
            except (TypeError, ValueError):
                power_label = str(power)
            return " ".join(part for part in (brand, power_label) if part).strip()
        return brand

    power = final.get("inverter_power_kw")
    brand = str(final.get("inverter_brand") or "").strip()
    if power:
        try:
            power_label = f"{float(power):g} kW"
        except (TypeError, ValueError):
            power_label = str(power)
        return " ".join(part for part in (brand, power_label) if part).strip()
    return brand


def _create_official_quote(project: str, data: dict, contact: dict) -> dict:
    result = engine.calculate(project, data, context=load_calculation_context())
    quote_number = f"HSQ-{datetime.now():%Y%m%d}-{randint(1000, 9999)}"
    result["quote_number"] = quote_number
    result["created_at"] = datetime.now().strftime("%d/%m/%Y a %H:%M")
    result["project_type"] = project
    quote_id = save_quote(quote_number, project, data, contact, result)
    _notify_quote_created_safely(
        quote_id=quote_id,
        project=project,
        contact=contact,
        data=data,
        result=result,
    )
    final = result.get("final_results") or {}
    financial = result.get("financial_breakdown") or {}
    return {
        "id": quote_id,
        "ref": quote_number,
        "quote_number": quote_number,
        "total_ttc": _money_label(financial.get("total_ttc")),
        "kwc": _result_kwc(final),
        "panels": _result_panel_count(final),
        "inverter": _result_inverter_label(project, final),
        "system_summary": _quote_summary(project, result),
        "download_url": url_for("main.api_quote_document_by_id", quote_id=quote_id),
        "pdf_url": url_for("main.api_quote_document_by_id", quote_id=quote_id),
        "view_url": url_for("main.api_quote_by_id", quote_id=quote_id),
    }


def _assistant_quote_factory(project: str, data: dict, contact: dict) -> dict:
    try:
        return _create_official_quote(project, data, contact)
    except ValidationError as exc:
        return {"error": str(exc)}
    except Exception:
        current_app.logger.exception("Assistant deterministic quote generation failed")
        return {"error": "le calcul officiel n'a pas pu etre termine pour ces donnees."}


def _build_quote_from_ai_payload(raw_payload: dict) -> dict | None:
    mode = _ai_text(raw_payload, "mode", "project", "type").lower()
    city = _ai_text(raw_payload, "ville", "city", "location", "localisation")
    contact = {
        "name": _ai_text(raw_payload, "nom", "name", "client_name", "customer_name") or "Client chat",
        "phone": _ai_text(raw_payload, "telephone", "phone", "tel", "mobile"),
        "email": _ai_text(raw_payload, "email", "mail"),
        "location": city,
    }

    if mode in {"ongrid", "on_grid", "photovoltaic", "pv", "solaire"}:
        project = "photovoltaic"
        data = {
            "meter_type": _ai_text(raw_payload, "meter_type", "compteur", "type_compteur", "compteur_type") or "numerique",
            "phase": _ai_phase(_ai_text(raw_payload, "phase", "reseau", "network")),
            "monthly_consumption_kwh": _ai_float(
                raw_payload,
                "monthly_consumption_kwh",
                "monthly_kwh",
                "consommation",
                "consommation_mensuelle",
                "kwh",
            ),
            "city": city,
        }
    elif mode in {"hybrid", "hybride", "batterie", "batteries", "stockage", "solaire_batterie", "solaire_avec_batterie"}:
        project = "hybrid"
        phase = extract_phase(_ai_text(raw_payload, "phase", "reseau", "network"))
        voltage = _ai_float(raw_payload, "voltage_v", "voltage", "tension", default=220)
        if phase == "triphase" or voltage in {380, 400}:
            raise ValidationError(
                "Votre branchement est triphase. Notre configurateur hybride traite actuellement "
                "le 220 V monophase ; un conseiller doit valider votre solution triphasee."
            )
        data = {
            "monthly_consumption_kwh": _ai_float(
                raw_payload,
                "monthly_consumption_kwh",
                "monthly_kwh",
                "consommation",
                "consommation_mensuelle",
                "kwh",
            ),
            "phase": "monophase",
            "voltage_v": 220,
            "city": city,
        }
    elif mode in {"pumping", "pompage", "pump"}:
        project = "pumping"
        data = {
            "pump_existing": False,
            "flow_m3_h": _ai_float(raw_payload, "flow_m3_h", "debit", "débit", "debit_m3_h"),
            "hmt_m": _ai_float(raw_payload, "hmt_m", "hmt", "profondeur", "depth", "hauteur"),
            "city": city,
        }
    else:
        return None

    return _create_official_quote(project, data, contact)


def _quote_from_ready_marker(payload: dict) -> dict | None:
    if not isinstance(payload, dict):
        return None
    if not payload.get("ref") or not (payload.get("pdf_url") or payload.get("download_url")):
        return None
    return {
        "id": payload.get("id"),
        "ref": payload.get("ref"),
        "quote_number": payload.get("ref"),
        "total_ttc": str(payload.get("total_ttc") or ""),
        "kwc": payload.get("kwc", ""),
        "panels": payload.get("panels", ""),
        "inverter": payload.get("inverter", ""),
        "system_summary": str(payload.get("system_summary") or "Devis HeliAntha"),
        "download_url": str(payload.get("pdf_url") or payload.get("download_url") or ""),
        "pdf_url": str(payload.get("pdf_url") or payload.get("download_url") or ""),
        "view_url": str(payload.get("view_url") or ""),
    }


def _assistant_payload_from_content(content: str) -> dict:
    clean_content, quote_payload = extract_quote_request(content)
    response_payload = {"role": "assistant", "content": clean_content or str(content or "").strip()}
    if quote_payload:
        quote = _quote_from_ready_marker(quote_payload)
        if not quote:
            try:
                quote = _build_quote_from_ai_payload(quote_payload)
            except ValidationError as exc:
                response_payload["content"] = str(exc)
                quote = None
            except Exception:
                current_app.logger.exception("Assistant quote generation failed")
                quote = None
        if quote:
            response_payload["quote_ready"] = True
            response_payload["quote"] = quote
            if not response_payload["content"]:
                response_payload["content"] = "Votre devis officiel est pret. Vous pouvez le telecharger ci-dessous."
    return response_payload


def _ndjson(payload: dict) -> str:
    return json_dumps(payload, ensure_ascii=False) + "\n"


def _assistant_with_products(payload: dict, products: list[dict]) -> dict:
    """Attach verified catalogue facts to every final response, including quotes."""
    if products and not payload.get("suggested_products"):
        payload["suggested_products"] = products
    return payload


@bp.before_request
def _limit_assistant_messages():
    if request.endpoint not in {"main.assistant_chat", "main.assistant_chat_stream"}:
        return None
    # The WSGI peer address honors any trusted proxy configured by deployment.
    # Never trust a client-supplied forwarding header here.
    retry_after = current_app.extensions["assistant_quota"].retry_after(
        request.remote_addr or "unknown"
    )
    if retry_after:
        return jsonify(
            role="assistant", content=ASSISTANT_WAIT_MESSAGE, error=ASSISTANT_WAIT_MESSAGE
        ), 429, {"Retry-After": str(retry_after)}
    return None


@bp.post("/api/assistant/chat")
def assistant_chat():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Payload JSON requis."), 400
    try:
        messages = sanitize_messages(payload.get("messages"))
    except ValueError:
        return jsonify(error="messages doit etre une liste non vide."), 400
    products = find_catalog_products(messages)
    catalog_query = is_catalog_query(messages)
    devis_response = None
    if not catalog_query and can_use_quote_manager(messages):
        devis_response = assistant_devis_manager.handle(messages, quote_factory=_assistant_quote_factory)
    if devis_response and devis_response.handled:
        return jsonify(_assistant_with_products(
            _assistant_payload_from_content(devis_response.content), products
        ))
    quick_response = quick_solar_power_response(messages, products=products)
    if quick_response is None and not catalog_query:
        quick_response = quick_assistant_response(messages)
    if quick_response:
        return jsonify(_assistant_with_products(quick_response, products))
    assistant_response = chat_with_ollama(messages, products=products)
    result = _assistant_payload_from_content(assistant_response.get("content", ""))
    return jsonify(_assistant_with_products(result, products))


@bp.post("/api/assistant/chat/stream")
def assistant_chat_stream():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Payload JSON requis."), 400
    try:
        messages = sanitize_messages(payload.get("messages"))
    except ValueError:
        return jsonify(error="messages doit etre une liste non vide."), 400

    products = find_catalog_products(messages)
    catalog_query = is_catalog_query(messages)
    devis_response = None
    if not catalog_query and can_use_quote_manager(messages):
        devis_response = assistant_devis_manager.handle(messages, quote_factory=_assistant_quote_factory)
    if devis_response and devis_response.handled:
        return Response(
            _ndjson({"type": "final", **_assistant_with_products(
                _assistant_payload_from_content(devis_response.content), products
            )}),
            mimetype="application/x-ndjson",
        )

    quick_response = quick_solar_power_response(messages, products=products)
    if quick_response is None and not catalog_query:
        quick_response = quick_assistant_response(messages)
    if quick_response:
        stream_payload = _assistant_with_products(dict(quick_response), products)
        return Response(_ndjson({"type": "final", **stream_payload}), mimetype="application/x-ndjson")

    @stream_with_context
    def generate():
        full_content = ""
        pending_visible = ""
        marker = "<<<DEVIS_DATA:"
        marker_tail = len(marker) - 1
        suppress_tag = False

        for chunk in stream_ollama_chat(messages, products=products):
            if not chunk:
                continue
            full_content += chunk
            if suppress_tag:
                continue

            pending_visible += chunk
            marker_index = pending_visible.find(marker)
            if marker_index >= 0:
                before_marker = pending_visible[:marker_index]
                if before_marker:
                    yield _ndjson({"type": "token", "content": before_marker})
                pending_visible = ""
                suppress_tag = True
                continue

            safe_length = max(0, len(pending_visible) - marker_tail)
            if safe_length:
                visible = pending_visible[:safe_length]
                pending_visible = pending_visible[safe_length:]
                yield _ndjson({"type": "token", "content": visible})

        if pending_visible and not suppress_tag:
            yield _ndjson({"type": "token", "content": pending_visible})

        result = _assistant_payload_from_content(full_content)
        yield _ndjson({"type": "final", **_assistant_with_products(result, products)})

    return Response(generate(), mimetype="application/x-ndjson")


@bp.get("/api/quotes/<int:quote_id>")
def api_quote_by_id(quote_id):
    quote = get_quote(quote_id)
    if not quote:
        abort(404)
    save_quote_client_event(quote["id"], quote["quote_number"], "api_view", request.args.get("from", "api"))
    return _quote_json_response(quote)


@bp.get("/api/quotes/by-number/<quote_number>")
def api_quote_by_number(quote_number):
    quote = get_quote_by_number(quote_number)
    if not quote:
        abort(404)
    save_quote_client_event(quote["id"], quote["quote_number"], "api_view", request.args.get("from", "api"))
    return _quote_json_response(quote)


@bp.get("/api/quotes/<int:quote_id>/document.pdf")
def api_quote_document_by_id(quote_id):
    quote = get_quote(quote_id)
    if not quote:
        abort(404)
    return _quote_pdf_response(quote)


@bp.get("/devis/<int:quote_id>")
def public_quote_by_id(quote_id):
    quote = get_quote(quote_id)
    if not quote:
        abort(404)
    save_quote_client_event(quote["id"], quote["quote_number"], "api_view", request.args.get("from", "direct"))
    return _quote_json_response(quote)


@bp.get("/devis/<int:quote_id>/pdf")
def public_quote_print_by_id(quote_id):
    quote = get_quote(quote_id)
    if not quote:
        abort(404)
    return _quote_pdf_response(quote)


@bp.get("/devis/<int:quote_id>/document.pdf")
def public_quote_document_by_id(quote_id):
    quote = get_quote(quote_id)
    if not quote:
        abort(404)
    return _quote_pdf_response(quote)


@bp.get("/simulation/<quote_number>")
def public_quote(quote_number):
    quote = get_quote_by_number(quote_number)
    if not quote:
        abort(404)
    save_quote_client_event(quote["id"], quote["quote_number"], "api_view", request.args.get("from", "direct"))
    return _quote_json_response(quote)


@bp.get("/simulation/<quote_number>/predevis")
def public_quote_print(quote_number):
    quote = get_quote_by_number(quote_number)
    if not quote:
        abort(404)
    save_quote_client_event(quote["id"], quote["quote_number"], "pdf_view", "predevis")
    return _quote_pdf_response(quote)


@bp.post("/api/simulations/<quote_number>/select-offer")
def select_public_offer(quote_number):
    quote = get_quote_by_number(quote_number)
    if not quote:
        return jsonify(error="Simulation introuvable."), 404
    payload = request.get_json(silent=True) or {}
    level = str(payload.get("level", "")).strip().lower()
    offers = quote.get("result", {}).get("offers") or []
    allowed = {str(item.get("level", "")).strip().lower() for item in offers}
    if level not in allowed:
        return jsonify(error="Offre non reconnue."), 400
    update_quote_selected_offer(quote["id"], level)
    save_quote_client_event(quote["id"], quote["quote_number"], "offer_selected", level)
    return jsonify(ok=True, level=level)


@bp.post("/api/simulations/<quote_number>/visit")
def create_visit_request(quote_number):
    quote = get_quote_by_number(quote_number)
    if not quote:
        return jsonify(error="Simulation introuvable."), 404
    payload = request.get_json(silent=True) or {}
    phone = str(payload.get("phone", "")).strip()
    address = str(payload.get("address", "")).strip()
    if not phone or not address:
        return jsonify(error="Le téléphone et l'adresse sont nécessaires pour programmer une visite."), 400
    visit_payload = {
        "preferred_date": str(payload.get("preferred_date", "")).strip(),
        "time_slot": str(payload.get("time_slot", "")).strip(),
        "address": address,
        "phone": phone,
        "comment": str(payload.get("comment", "")).strip(),
        "requested_by": "Client",
    }
    save_visit_request(quote["id"], quote["quote_number"], visit_payload)
    save_quote_client_event(quote["id"], quote["quote_number"], "visit_requested", visit_payload.get("preferred_date", ""))
    return jsonify(ok=True, message="Votre demande de visite a bien été enregistrée.")


@bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if email:
            user = authenticate_user(email, password)
            if user:
                session["admin_user"] = user["username"]
                return redirect(request.args.get("next") or url_for("main.admin_dashboard"))
            error = "Email ou mot de passe incorrect."
        elif password == current_app.config["ADMIN_PASSWORD"]:
            primary = get_primary_admin_user()
            session["admin_user"] = (primary or {}).get("username") or "direction@heliantha.ma"
            return redirect(request.args.get("next") or url_for("main.admin_dashboard"))
        else:
            error = "Mot de passe incorrect."
    return render_template("admin/login.html", error=error)


@bp.post("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("main.admin_login"))


@bp.get("/admin/")
def admin_dashboard():
    return render_template(
        "admin/dashboard.html",
        stats=dashboard_stats(),
        project_labels=PROJECT_LABELS,
        display_quote_status=display_quote_status,
    )


def _method_decimal(value, digits=1):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    text = f"{number:,.{digits}f}"
    text = text.replace(",", " ").replace(".", ",")
    if digits == 1 and text.endswith(",0"):
        return text[:-2]
    return text


def _method_pump_power(product):
    specs = product.get("technical_specs") or {}
    return normalize_pump_cv(specs.get("power_hp") or product.get("power_hp"))


def _method_pump_outlet_diameter(product):
    specs = product.get("technical_specs") or {}
    return str(specs.get("outlet_diameter") or product.get("outlet_diameter") or "").strip()


def _method_pump_sale_parameters(context):
    rule = next(
        (
            dict(row)
            for row in (context.get("pumping_solar_rules") or {}).values()
            if row.get("rule_type") == "pump_sale_parameters" and int(row.get("active", 1) or 0) == 1
        ),
        {},
    )
    coefficient_1 = float(rule.get("coefficient_1") or 0.5)
    coefficient_2 = float(rule.get("coefficient_2") or 1.3)
    vat_rate = float(vat_rate_for_component(context, "pumping", "pump"))
    return {
        "coefficient_1": coefficient_1,
        "coefficient_2": coefficient_2,
        "vat_rate": vat_rate,
        "coefficient_1_label": _method_decimal(coefficient_1, 2),
        "coefficient_2_label": _method_decimal(coefficient_2, 2),
        "vat_rate_label": f"{_method_decimal(vat_rate * 100, 1)} %",
        "formula_label": "TTC = PT x coefficient 1 x coefficient 2",
    }


def _method_pump_sale(product, sale_parameters):
    return calculate_pump_sale_price(
        product.get("sale_price"),
        sale_parameters["coefficient_1"],
        sale_parameters["coefficient_2"],
        sale_parameters["vat_rate"],
    )


def _method_pump_curve(product):
    points = product.get("pump_curve_points") or []
    return [
        {
            "flow_m3_h": float(point.get("flow_m3_h") or 0),
            "hmt_m": float(point.get("hmt_m") or 0),
            "flow_label": f"{_method_decimal(point.get('flow_m3_h'), 1)} m³/h",
            "hmt_label": f"{_method_decimal(point.get('hmt_m'), 1)} m",
        }
        for point in points
        if point.get("flow_m3_h") is not None and point.get("hmt_m") is not None
    ]


def _method_active_curve_pumps(context):
    pumps = []
    for product in context.get("products") or []:
        if product.get("category") != "pumps" or int(product.get("active", 1) or 0) != 1:
            continue
        curve = _method_pump_curve(product)
        power_hp = _method_pump_power(product)
        if not curve or power_hp <= 0:
            continue
        pumps.append({
            **product,
            "_method_power_hp": power_hp,
            "_method_outlet_diameter": _method_pump_outlet_diameter(product),
            "_method_curve": curve,
        })
    return sorted(
        pumps,
        key=lambda item: (
            item["_method_power_hp"],
            float(item.get("sale_price") or 0),
            str(item.get("brand") or ""),
            str(item.get("model") or ""),
        ),
    )


def _method_pump_rules(context):
    rules = [
        dict(rule)
        for rule in (context.get("pumping_solar_rules") or {}).values()
        if rule.get("rule_type") == "pump_configuration" and int(rule.get("active", 1) or 0) == 1
    ]
    return sorted(
        rules,
        key=lambda rule: (
            float(rule.get("pump_cv") or 0),
            int(rule.get("sort_order") or 0),
            str(rule.get("title") or ""),
        ),
    )


def _method_rule_for_cv(context, pump_cv):
    target = normalize_pump_cv(pump_cv)
    for rule in _method_pump_rules(context):
        if abs(normalize_pump_cv(rule.get("pump_cv")) - target) <= 1e-9:
            return rule
    return None


def _method_interval_label(duty):
    if not duty:
        return "Hors courbe"
    start = duty.get("interval_start_m3_h")
    end = duty.get("interval_end_m3_h")
    if abs(float(start) - float(end)) <= 1e-9:
        return f"{_method_decimal(start, 1)} m³/h"
    return f"{_method_decimal(start, 1)} → {_method_decimal(end, 1)} m³/h"


def _method_policy_label(policy):
    return {
        "exact_catalogue_point": "Point exact de la courbe catalogue.",
        "conservative_interval_no_interpolation": "Débit situé entre deux points : le moteur utilise l'intervalle réel et retient la HMT la plus prudente, sans interpolation.",
    }.get(str(policy or ""), "Débit hors courbe enregistrée.")


def _method_candidates(pumps, flow_m3_h, hmt_m, sale_parameters):
    candidates = []
    variant_counts = {}
    for pump in pumps:
        cv = pump["_method_power_hp"]
        variant_counts[cv] = variant_counts.get(cv, 0) + 1
        duty = curve_head_for_flow(pump["_method_curve"], flow_m3_h)
        available_hmt = float(duty.get("available_hmt_m") or 0) if duty else None
        compatible = duty is not None and available_hmt is not None and available_hmt + 1e-9 >= hmt_m
        if compatible:
            status = "Compatible"
            status_tone = "ok"
            reason = "Couvre le débit et la HMT demandés."
        elif duty:
            status = "Insuffisant"
            status_tone = "bad"
            reason = f"HMT disponible inférieure à {_method_decimal(hmt_m, 1)} m."
        else:
            status = "Hors courbe"
            status_tone = "muted"
            reason = "Le débit demandé n'est pas couvert par les points enregistrés."
        sale = _method_pump_sale(pump, sale_parameters)
        candidates.append({
            "product_id": pump.get("id"),
            "reference": pump.get("reference"),
            "cv": cv,
            "cv_label": format_cv(cv),
            "variant_index": variant_counts[cv],
            "outlet_diameter": pump.get("_method_outlet_diameter") or "—",
            "interval_label": _method_interval_label(duty),
            "hmt_label": f"{_method_decimal(available_hmt, 1)} m" if available_hmt is not None else "—",
            "status": status,
            "status_tone": status_tone,
            "compatible": compatible,
            "internal_pt": sale["internal_pt"],
            "internal_pt_label": format_price(sale["internal_pt"]),
            "sale_ht": sale["price_ht"],
            "sale_ht_label": format_price(sale["price_ht"]),
            "sale_ttc": sale["price_ttc"],
            "sale_ttc_label": format_price(sale["price_ttc"]),
            "reason": reason,
        })
    return candidates


def _method_solar_config(rule):
    if not rule:
        return None
    panels = int(float(rule.get("panel_count") or 0))
    panel_power_w = float(rule.get("panel_power_w") or 0)
    drive_power_kw = float(rule.get("drive_power_kw") or 0)
    pv_kwp = panels * panel_power_w / 1000 if panels and panel_power_w else 0
    return {
        "pump_cv_label": format_cv(rule.get("pump_cv")),
        "panels_label": f"{panels} × {format_power_w(panel_power_w)}",
        "pv_kwp_label": f"{_method_decimal(pv_kwp, 2)} kWp",
        "drive_label": f"{rule.get('drive_brand') or 'Variateur'} {format_power_kw(drive_power_kw)}",
        "phase_label": format_phase(rule.get("phase")),
    }


def _method_decision(selection, candidates, rule):
    if not selection:
        for candidate in candidates:
            candidate["is_selected"] = False
            if candidate.get("status") == "Insuffisant":
                candidate["filter_type"] = "insufficient"
            elif candidate.get("status") == "Hors courbe":
                candidate["filter_type"] = "out_of_curve"
            else:
                candidate["filter_type"] = "compatible_eliminated"
        return {
            "status": "no_standard_pump",
            "title": "Aucune pompe standard ne couvre ce besoin.",
            "lines": [
                NO_STANDARD_PUMP_MESSAGE,
                "Les candidats évalués sont hors courbe ou insuffisants pour le couple Débit + HMT demandé.",
                "Aucun fallback et aucun CV automatique ne sont utilisés.",
            ],
        }
    selected_cv = float(selection["selected_pump_cv"])
    compatible = [candidate for candidate in candidates if candidate["compatible"]]
    lower_insufficient = [
        candidate
        for candidate in candidates
        if candidate["cv"] < selected_cv and not candidate["compatible"]
    ]
    same_cv_compatible = [
        candidate
        for candidate in compatible
        if abs(candidate["cv"] - selected_cv) <= 1e-9
    ]
    selected_product = selection.get("product") or {}
    selected_candidate = next(
        (
            candidate
            for candidate in same_cv_compatible
            if (
                candidate.get("product_id") and candidate.get("product_id") == selected_product.get("id")
            )
            or (
                candidate.get("reference") and candidate.get("reference") == selected_product.get("reference")
            )
        ),
        same_cv_compatible[0] if same_cv_compatible else None,
    )
    compatible_cvs = []
    for candidate in compatible:
        if not any(abs(candidate["cv"] - existing) <= 1e-9 for existing in compatible_cvs):
            compatible_cvs.append(candidate["cv"])
    lines = []
    if lower_insufficient:
        lower_labels = []
        for candidate in lower_insufficient:
            if candidate["cv_label"] not in lower_labels:
                lower_labels.append(candidate["cv_label"])
        lines.append(f"Les puissances inférieures ({', '.join(lower_labels)}) ne couvrent pas le besoin.")
    if compatible_cvs:
        lines.append(
            "Les pompes compatibles sont : "
            + ", ".join(format_cv(cv) for cv in compatible_cvs)
            + "."
        )
    lines.append("La règle HeliAntha retient la plus petite puissance CV suffisante.")
    if len(same_cv_compatible) > 1:
        lines.append(
            f"{len(same_cv_compatible)} solutions {format_cv(selected_cv)} couvrent le besoin ; "
            "le PT interne Admin le plus faible les départage."
        )
    if not rule:
        lines.append("La configuration solaire HeliAntha correspondante n'est pas encore définie.")
    else:
        lines.append("Le CV retenu est envoyé vers la règle solaire HeliAntha active.")
    lines.append(f"→ {format_cv(selected_cv)} retenu.")

    for candidate in candidates:
        is_sel = bool(
            selected_candidate
            and (
                candidate is selected_candidate
                or (
                    candidate.get("product_id")
                    and candidate.get("product_id") == selected_candidate.get("product_id")
                    and candidate.get("variant_index") == selected_candidate.get("variant_index")
                )
            )
        )
        candidate["is_selected"] = is_sel
        if is_sel:
            candidate["filter_type"] = "selected"
            candidate["reason"] = f"Solution retenue : plus petite puissance ({candidate['cv_label']}) couvrant le besoin au meilleur PT interne ({candidate['internal_pt_label']})."
        elif candidate.get("compatible"):
            candidate["filter_type"] = "compatible_eliminated"
            if abs(candidate["cv"] - selected_cv) <= 1e-9:
                candidate["reason"] = f"Couvre le besoin en {candidate['cv_label']}, mais PT interne ({candidate['internal_pt_label']}) supérieur à la variante retenue ({selected_candidate['internal_pt_label'] if selected_candidate else ''})."
            elif candidate["cv"] > selected_cv:
                candidate["reason"] = f"Couvre le besoin, mais puissance plus élevée ({candidate['cv_label']} vs {selected_candidate['cv_label'] if selected_candidate else format_cv(selected_cv)} retenu)."
            else:
                candidate["reason"] = "Couvre le débit et la HMT demandés."
        elif candidate.get("status") == "Insuffisant":
            candidate["filter_type"] = "insufficient"
        else:
            candidate["filter_type"] = "out_of_curve"

    return {
        "status": "selected",
        "title": f"{format_cv(selected_cv)} retenu",
        "selected_cv": selected_cv,
        "selected_cv_label": format_cv(selected_cv),
        "selected_pt_label": format_price(selection.get("current_price")),
        "selected_sale_ht_label": (selected_candidate or {}).get("sale_ht_label") or "—",
        "selected_sale_ttc_label": (selected_candidate or {}).get("sale_ttc_label") or "—",
        "selected_outlet_diameter": (selected_candidate or {}).get("outlet_diameter") or "",
        "solar_rule_missing": not bool(rule),
        "lines": lines,
    }


def _method_performance_groups(pumps, sale_parameters):
    groups = []
    by_cv = {}
    for pump in pumps:
        by_cv.setdefault(pump["_method_power_hp"], []).append(pump)
    for cv, variants in sorted(by_cv.items()):
        group = {"cv": cv, "cv_label": format_cv(cv), "variants": []}
        for index, pump in enumerate(variants, start=1):
            specs = pump.get("technical_specs") or {}
            sale = _method_pump_sale(pump, sale_parameters)
            group["variants"].append({
                "label": f"Variante technique {index}",
                "outlet_diameter": pump.get("_method_outlet_diameter") or "—",
                "power_kw": format_power_kw(pump.get("power_kw") or specs.get("power_kw")),
                "voltage": f"{_method_decimal(pump.get('voltage') or specs.get('voltage_v'), 0)} V" if (pump.get("voltage") or specs.get("voltage_v")) not in (None, "") else "—",
                "current": f"{_method_decimal(pump.get('current_amp') or specs.get('current_a'), 1)} A" if (pump.get("current_amp") or specs.get("current_a")) not in (None, "") else "—",
                "internal_pt": format_price(sale["internal_pt"]),
                "sale_ht": format_price(sale["price_ht"]),
                "sale_ttc": format_price(sale["price_ttc"]),
                "points": pump["_method_curve"],
            })
        groups.append(group)
    return groups


def _pumping_method_view(flow_value="", hmt_value=""):
    context = load_calculation_context()
    sale_parameters = _method_pump_sale_parameters(context)
    pumps = _method_active_curve_pumps(context)
    pump_rules = _method_pump_rules(context)
    summary = {
        "pump_count": len(pumps),
        "cv_count": len({pump["_method_power_hp"] for pump in pumps}),
        "curve_point_count": sum(len(pump["_method_curve"]) for pump in pumps),
    }
    analysis = None
    error = ""
    submitted = bool(str(flow_value).strip() or str(hmt_value).strip())
    if submitted:
        flow = parse_number(flow_value, None)
        hmt = parse_number(hmt_value, None)
        if not flow or flow <= 0 or not hmt or hmt <= 0:
            error = "Saisissez un débit et une HMT strictement supérieurs à 0."
        else:
            selection = select_pump_for_duty(context.get("products") or [], flow, hmt)
            candidates = _method_candidates(pumps, flow, hmt, sale_parameters)
            selected_cv = float(selection["selected_pump_cv"]) if selection else None
            rule = _method_rule_for_cv(context, selected_cv) if selected_cv else None
            selected_duty = selection.get("duty") if selection else None
            decision = _method_decision(selection, candidates, rule)
            counts = {
                "total": len(candidates),
                "selected": sum(1 for c in candidates if c.get("is_selected")),
                "compatible_eliminated": sum(1 for c in candidates if c.get("filter_type") == "compatible_eliminated"),
                "insufficient": sum(1 for c in candidates if c.get("filter_type") == "insufficient"),
                "out_of_curve": sum(1 for c in candidates if c.get("filter_type") == "out_of_curve"),
            }
            analysis = {
                "flow_label": f"{_method_decimal(flow, 1)} m³/h",
                "hmt_label": f"{_method_decimal(hmt, 1)} m",
                "interval_label": _method_interval_label(selected_duty),
                "policy_label": _method_policy_label((selected_duty or {}).get("policy")),
                "candidates": candidates,
                "counts": counts,
                "decision": decision,
                "solar_config": _method_solar_config(rule),
            }
    return {
        "summary": summary,
        "flow_value": flow_value,
        "hmt_value": hmt_value,
        "analysis": analysis,
        "error": error,
        "pump_sale_parameters": sale_parameters,
        "performance_groups": _method_performance_groups(pumps, sale_parameters),
        "solar_rules": [
            {
                "cv": format_cv(rule.get("pump_cv")),
                "panels": f"{int(float(rule.get('panel_count') or 0))} × {format_power_w(rule.get('panel_power_w'))}",
                "drive": f"{rule.get('drive_brand') or 'Variateur'} {format_power_kw(rule.get('drive_power_kw'))}",
                "phase": format_phase(rule.get("phase")),
            }
            for rule in pump_rules
        ],
    }


@bp.get("/admin/pompage/methode")
def admin_pumping_method():
    view = _pumping_method_view(
        request.args.get("flow_m3_h", ""),
        request.args.get("hmt_m", ""),
    )
    return render_template("admin/pumping_method.html", **view)


@bp.get("/admin/devis")
def admin_quotes():
    groups = group_quotes_by_client(list_quotes(limit=None))
    return render_template(
        "admin/quotes.html",
        client_groups=groups,
        quote_count=sum(len(group["quotes"]) for group in groups),
        project_labels=PROJECT_LABELS,
        public_projects=PUBLIC_PROJECTS,
        statuses=ADMIN_QUOTE_STATUSES,
        filters=request.args,
    )


def _clean_phone_for_whatsapp(phone: str) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", str(phone))
    if not digits:
        return ""
    if digits.startswith("0") and len(digits) == 10:
        return "212" + digits[1:]
    if digits.startswith("212"):
        return digits
    if len(digits) == 9:
        return "212" + digits
    return digits


def _extract_vat_summary(financial_breakdown: dict) -> dict:
    fb = financial_breakdown or {}
    vat_10_ht = 0.0
    vat_10_amount = 0.0
    vat_20_ht = 0.0
    vat_20_amount = 0.0
    for item in (fb.get("vat_breakdown") or []):
        try:
            rate = float(item.get("vat_rate") or 0)
            ht = float(item.get("total_ht") or 0)
            vat = float(item.get("vat") or 0)
            if abs(rate - 0.10) < 0.01:
                vat_10_ht += ht
                vat_10_amount += vat
            elif abs(rate - 0.20) < 0.01:
                vat_20_ht += ht
                vat_20_amount += vat
        except (ValueError, TypeError):
            continue
    total_ht = float(fb.get("total_ht") or 0)
    total_vat = float(fb.get("vat") or 0)
    total_ttc = float(fb.get("total_ttc") or 0)
    return {
        "vat_10_ht": vat_10_ht,
        "vat_10_amount": vat_10_amount,
        "vat_20_ht": vat_20_ht,
        "vat_20_amount": vat_20_amount,
        "total_ht": total_ht,
        "total_vat": total_vat,
        "total_ttc": total_ttc,
        "has_breakdown": (vat_10_amount > 0 or vat_20_amount > 0),
    }


def _extract_quote_kpis(quote: dict, calculation_detail: dict, bom_lines: list) -> list[dict]:
    project = (quote.get("project") or "").lower()
    final_results = (calculation_detail or {}).get("final_results") or {}
    metrics_list = (quote.get("result") or {}).get("metrics") or []
    metrics = {m.get("label"): m.get("value") for m in metrics_list if isinstance(m, dict)}

    kpis = []

    # 1. Puissance PV
    pv_kwp = final_results.get("installed_power_kwp") or metrics.get("Puissance installee")
    panel_count = final_results.get("panel_count")
    panel_power_w = final_results.get("panel_power_w")

    if not pv_kwp:
        for line in (bom_lines or []):
            desc = (line.get("display_designation") or line.get("description") or line.get("role") or "").lower()
            if "panneau" in desc or "pv" in desc:
                qty = line.get("quantity") or 1
                pv_kwp = f"{qty} panneaux"
                break

    if pv_kwp:
        try:
            val_str = f"{float(pv_kwp):.2f} kWc"
        except (ValueError, TypeError):
            val_str = str(pv_kwp)
        sub_str = f"{panel_count} × {panel_power_w} W" if panel_count and panel_power_w else "Générateur photovoltaïque"
        kpis.append({"label": "Puissance Solaire", "value": val_str, "sub": sub_str, "icon": "☀️"})

    # 2. Inverter / Drive / Coeur de conversion
    inverter_kw = final_results.get("inverter_power_kw") or final_results.get("solar_drive_kw") or final_results.get("drive_power_kw")
    inverter_brand = final_results.get("inverter_brand") or final_results.get("drive_brand") or ""

    if inverter_kw:
        brand_label = f"{inverter_brand} " if inverter_brand else ""
        title = "Variateur Solaire" if "pump" in project else "Onduleur"
        phase_label = final_results.get("phase", "")
        kpis.append({
            "label": title,
            "value": f"{inverter_kw} kW",
            "sub": f"{brand_label}{phase_label}".strip() or "Conversion optimisée",
            "icon": "⚡",
        })
    elif metrics.get("Onduleur hybride"):
        kpis.append({"label": "Onduleur Hybride", "value": str(metrics.get("Onduleur hybride")), "sub": "Gestion réseau & batterie", "icon": "⚡"})
    elif metrics.get("Variateur de pompage"):
        kpis.append({"label": "Variateur Solaire", "value": str(metrics.get("Variateur de pompage")), "sub": "MPPT intégré", "icon": "⚡"})

    # 3. Third KPI (Batteries, Pump CV, or Consumption)
    if "pump" in project:
        pump_cv = final_results.get("pump_power_cv") or final_results.get("pump_cv")
        flow = final_results.get("flow_m3_h")
        hmt = final_results.get("hmt_m")
        if pump_cv:
            sub = f"Débit: {flow} m³/h | HMT: {hmt}m" if flow and hmt else "Au fil du soleil"
            kpis.append({"label": "Pompe immergée", "value": f"{pump_cv} CV", "sub": sub, "icon": "💧"})
        elif flow and hmt:
            kpis.append({"label": "Débit & Hauteur", "value": f"{flow} m³/h", "sub": f"HMT: {hmt} mètres", "icon": "💧"})
    elif "hybrid" in project or final_results.get("battery_count"):
        bat_kwh = final_results.get("battery_total_capacity_kwh")
        bat_count = final_results.get("battery_count")
        unit_cap = final_results.get("battery_unit_capacity_kwh")
        if bat_kwh:
            sub = f"{bat_count} × {unit_cap} kWh LiFePO4" if bat_count and unit_cap else "Stockage lithium sécurisé"
            kpis.append({"label": "Stockage Lithium", "value": f"{bat_kwh} kWh", "sub": sub, "icon": "🔋"})
        elif metrics.get("Stockage Lithium"):
            kpis.append({"label": "Stockage Lithium", "value": str(metrics.get("Stockage Lithium")), "sub": "Batteries solaires", "icon": "🔋"})
    else:
        conso = final_results.get("monthly_consumption_kwh")
        bill = final_results.get("monthly_bill_dh")
        if conso:
            kpis.append({"label": "Consommation", "value": f"{int(conso)} kWh/mois", "sub": "Autoconsommation directe", "icon": "📉"})
        elif bill:
            kpis.append({"label": "Facture mensuelle", "value": f"{bill} DH/mois", "sub": "Cible d'effacement", "icon": "📉"})

    if not kpis:
        kpis.append({"label": "Installation", "value": quote.get("project", "Solaire").capitalize(), "sub": "Configuration validée", "icon": "⚡"})

    return kpis[:3]


@bp.get("/admin/devis/<int:quote_id>")
def admin_quote_detail(quote_id):
    quote = get_quote(quote_id)
    if not quote:
        abort(404)
    calculation_detail = quote.get("calculation_detail") or {}
    bom = quote.get("bom") or calculation_detail.get("bom", {})
    bom_lines = _display_equipment_lines((bom or {}).get("lines") or quote.get("selected_equipment") or [])
    financial_breakdown = quote.get("financial_breakdown") or {}
    financial_summary_rows = _financial_summary_rows(financial_breakdown)
    quote["display_status"] = display_quote_status(quote.get("status"))

    kpis = _extract_quote_kpis(quote, calculation_detail, bom_lines)
    vat_summary = _extract_vat_summary(financial_breakdown)
    wa_phone = _clean_phone_for_whatsapp(quote.get("phone"))
    customer_name = quote.get("customer_name") or ""
    quote_number = quote.get("quote_number") or f"HSQ-{quote_id}"
    wa_message = f"Bonjour {customer_name}, suite à votre demande de devis {quote_number} pour votre installation solaire HeliAntha, nous restons à votre entière disposition pour tout échange technique ou commercial."

    return render_template(
        "admin/quote_detail.html",
        quote=quote,
        project_labels=PROJECT_LABELS,
        statuses=ADMIN_QUOTE_STATUSES,
        display_equipment_lines=bom_lines,
        financial_summary_rows=financial_summary_rows,
        financial_breakdown=financial_breakdown,
        kpis=kpis,
        vat_summary=vat_summary,
        wa_phone=wa_phone,
        wa_message=wa_message,
    )


@bp.get("/admin/devis/<int:quote_id>/pdf")
def admin_quote_pdf(quote_id):
    quote = get_quote(quote_id)
    if not quote:
        abort(404)
    return _quote_pdf_response(quote)


@bp.post("/admin/devis/<int:quote_id>/status")
def admin_quote_status(quote_id):
    status = request.form.get("status", "Nouveau")
    if status not in ADMIN_QUOTE_STATUSES:
        abort(400)
    update_quote_status(quote_id, status, session.get("admin_user", "admin"))
    return redirect(url_for("main.admin_quote_detail", quote_id=quote_id))


@bp.get("/admin/prospects")
def admin_prospects():
    filters = {key: request.args[key] for key in ("q", "project", "status") if key in request.args}
    return redirect(url_for("main.admin_quotes", **filters))


@bp.get("/admin/catalogue")
def admin_catalog():
    filters = {
        "q": request.args.get("q", ""),
        "category": request.args.get("category", ""),
        "active": request.args.get("active", ""),
        "brand": request.args.get("brand", ""),
        "sort": request.args.get("sort", "catalog"),
    }
    if filters["sort"] == "stock_desc":
        filters["sort"] = "catalog"
    products = [
        _decorate_catalog_product(item)
        for item in list_products(
            search=filters["q"],
            category=filters["category"],
            active=filters["active"],
            brand=filters["brand"],
            sort=filters["sort"],
        )
    ]
    products_data_map = {
        str(item["id"]): _catalog_form_view_product(item)
        for item in products
        if item.get("id")
    }
    return render_template(
        "admin/catalog.html",
        products=products,
        products_data_map=products_data_map,
        filters=filters,
        category_options=category_options(),
        technical_fields=technical_fields_by_category(),
        sort_options=CATALOG_SORT_OPTIONS,
    )


@bp.route("/admin/catalogue/new", methods=["GET", "POST"])
def admin_catalog_new():
    product = _catalog_form_defaults()
    errors = {}
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.accept_mimetypes.best == "application/json"
    if request.method == "POST":
        product = _product_from_form(request.form)
        try:
            save_product(product, submitted_fields=request.form)
        except ProductValidationError as exc:
            errors = exc.errors
            if is_ajax:
                return jsonify({
                    "ok": False,
                    "errors": errors,
                    "message": "La fiche produit n'a pas été enregistrée. Corrigez les champs signalés."
                }), 400
            flash("La fiche produit n'a pas été enregistrée. Corrigez les champs signalés.", "error")
        else:
            if is_ajax:
                return jsonify({
                    "ok": True,
                    "reference": product.get("reference"),
                    "redirect": url_for("main.admin_catalog", saved=product.get("reference"))
                })
            return redirect(url_for("main.admin_catalog", saved=product.get("reference")))
    return render_template(
        "admin/catalog_form.html",
        product=_catalog_form_view_product(product),
        errors=errors,
        category_options=category_options(),
        technical_fields=technical_fields_by_category(),
    )


@bp.route("/admin/catalogue/<int:product_id>/edit", methods=["GET", "POST"])
def admin_catalog_edit(product_id):
    product = get_product(product_id)
    if not product:
        abort(404)
    errors = {}
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.accept_mimetypes.best == "application/json"
    if request.method == "GET" and (is_ajax or request.args.get("format") == "json"):
        return jsonify({
            "ok": True,
            "product": _catalog_form_view_product(product),
        })
    if request.method == "POST":
        product = _product_from_form(request.form, existing_product=product)
        try:
            save_product(product, product_id=product_id, submitted_fields=request.form)
        except ProductValidationError as exc:
            errors = exc.errors
            if is_ajax:
                return jsonify({
                    "ok": False,
                    "errors": errors,
                    "message": "La fiche produit n'a pas été enregistrée. Corrigez les champs signalés."
                }), 400
            flash("La fiche produit n'a pas été enregistrée. Corrigez les champs signalés.", "error")
        else:
            if is_ajax:
                return jsonify({
                    "ok": True,
                    "reference": product.get("reference"),
                    "redirect": url_for("main.admin_catalog", saved=product.get("reference"))
                })
            return redirect(url_for("main.admin_catalog", saved=product.get("reference")))
    return render_template(
        "admin/catalog_form.html",
        product=_catalog_form_view_product(product),
        errors=errors,
        category_options=category_options(),
        technical_fields=technical_fields_by_category(),
    )


@bp.post("/admin/catalogue/<int:product_id>/toggle")
def admin_catalog_toggle(product_id):
    product = get_product(product_id)
    if not product:
        abort(404)
    try:
        set_product_active(product_id, not bool(product.get("active")))
    except ProductValidationError as exc:
        for message in exc.errors.values():
            flash(message, "error")
    return redirect(url_for("main.admin_catalog"))



@bp.route("/admin/regles-pompage", methods=["GET", "POST"])
def admin_pumping_rules():
    admin_name = session.get("admin_user", "HeliAntha")
    saved = False

    if request.method == "POST":
        action = request.form.get("action", "").strip()
        rule_type = request.form.get("rule_type", "").strip()
        section = _pumping_rule_section(rule_type)
        if not section:
            abort(400)

        rules = list_pumping_solar_rules()
        rule_id = request.form.get("rule_id", type=int)
        current = next((row for row in rules if int(row.get("id") or 0) == int(rule_id or 0)), None) if rule_id else None
        try:
            payload = _pumping_rule_payload(rule_type, request.form, current)
        except TaxValidationError as exc:
            flash(str(exc), "error")
            return render_template(
                "admin/pumping_rules.html",
                sections=group_rules(list_pumping_solar_rules()),
                section_definitions=PUMPING_RULE_SECTIONS,
                saved=False,
            ), 400

        if action == "add_rule":
            if not section.get("addable"):
                abort(400)
            if rule_type == "pump_configuration":
                target_cv = normalize_pump_cv(payload.get("pump_cv"))
                if not target_cv:
                    abort(400)
                existing = next(
                    (
                        row
                        for row in rules
                        if str(row.get("rule_type") or "") == "pump_configuration"
                        and abs(normalize_pump_cv(row.get("pump_cv")) - target_cv) <= 0.05
                    ),
                    None,
                )
                if existing:
                    update_pumping_solar_rule(existing["id"], payload, changed_by=admin_name)
                else:
                    payload["rule_key"] = f"pump_configuration_{str(target_cv).replace('.', '_')}_{uuid4().hex[:6]}"
                    payload["title"] = (payload.get("title") or f"{str(target_cv).replace('.', ',')} CV").strip()
                    payload["sort_order"] = max(
                        [int(row.get("sort_order") or 0) for row in rules if str(row.get("rule_type") or "") == "pump_configuration"] or [0]
                    ) + 10
                    create_pumping_solar_rule(payload, changed_by=admin_name)
            else:
                abort(400)
            saved = True
        elif action == "save_rule" and current:
            update_pumping_solar_rule(current["id"], payload, changed_by=admin_name)
            saved = True
        else:
            abort(400)

        if saved:
            return redirect(url_for("main.admin_pumping_rules", saved=1))

    sections = group_rules(list_pumping_solar_rules())
    return render_template(
        "admin/pumping_rules.html",
        sections=sections,
        section_definitions=PUMPING_RULE_SECTIONS,
        saved=bool(request.args.get("saved")),
    )


@bp.route("/admin/regles-ongrid", methods=["GET", "POST"])
def admin_ongrid_rules():
    saved = False
    if request.method == "POST":
        values = {
            key.removeprefix("value_"): value
            for key, value in request.form.items()
            if key.startswith("value_")
        }
        try:
            update_ongrid_parameters(values, changed_by=session.get("admin_user", "HeliAntha"))
        except (TaxValidationError, TransportValidationError) as exc:
            flash(str(exc), "error")
            return redirect(url_for("main.admin_ongrid_rules"))
        return redirect(url_for("main.admin_ongrid_rules", saved=1))

    groups = [
        {
            "key": "per_panel",
            "title": "Prix ajoutés pour chaque panneau",
            "intro": "Ces montants se multiplient automatiquement par le nombre de panneaux du devis.",
            "keys": ["protection_acdc_per_pv", "cablage_acdc_per_pv", "installation_per_pv"],
        },
        {
            "key": "injection",
            "title": "Limiteur d'injection",
            "intro": "C'est le boîtier qui limite l'injection vers le réseau. Le forfait dépend du type de réseau et de la puissance installée.",
            "keys": ["injection_limit_mono", "injection_limit_tri_threshold", "injection_limit_tri_low", "injection_limit_tri_high"],
        },
        {
            "key": "taxes",
            "title": "Soleil utilisé pour l'estimation",
            "intro": "Le soleil utilisé ici est une valeur fixe, pas une ville. Les taux de TVA sont gérés dans la page TVA.",
            "keys": ["psh_hours"],
        },
    ]
    friendly = {
        "protection_acdc_per_pv": {
            "label": "Protection électrique par panneau",
            "help": "Montant ajouté pour protéger l'installation électrique de chaque panneau.",
            "formula": "Calcul : nombre de panneaux x ce montant.",
            "suffix": "DH par panneau",
        },
        "cablage_acdc_per_pv": {
            "label": "Câbles et accessoires par panneau",
            "help": "Montant ajouté pour le câblage nécessaire à chaque panneau.",
            "formula": "Calcul : nombre de panneaux x ce montant.",
            "suffix": "DH par panneau",
        },
        "installation_per_pv": {
            "label": "Pose par panneau",
            "help": "Main-d'oeuvre de pose et mise en service pour chaque panneau.",
            "formula": "Calcul : nombre de panneaux x ce montant.",
            "suffix": "DH par panneau",
        },
        "transport_per_pv": {
            "label": "Transport par panneau",
            "help": "Part transport ajoutée pour chaque panneau.",
            "formula": "Calcul : nombre de panneaux x ce montant.",
            "suffix": "DH par panneau",
        },
        "injection_limit_mono": {
            "label": "Forfait limiteur en monophasé",
            "help": "Montant ajouté quand le client a un réseau monophasé.",
            "formula": "Calcul : forfait fixe si le réseau est monophasé.",
            "suffix": "DH",
        },
        "injection_limit_tri_threshold": {
            "label": "Seuil grande installation triphasée",
            "help": "Au-dessus de cette puissance, le système utilise le forfait triphasé élevé.",
            "formula": "Ce seuil sépare les petites et grandes installations triphasées.",
            "suffix": "kW",
        },
        "injection_limit_tri_low": {
            "label": "Forfait triphasé jusqu'au seuil",
            "help": "Montant ajouté en triphasé lorsque la puissance reste sous le seuil.",
            "formula": "Calcul : forfait fixe si puissance installée <= seuil.",
            "suffix": "DH",
        },
        "injection_limit_tri_high": {
            "label": "Forfait triphasé au-dessus du seuil",
            "help": "Montant ajouté en triphasé lorsque la puissance dépasse le seuil.",
            "formula": "Calcul : forfait fixe si puissance installée > seuil.",
            "suffix": "DH",
        },
        "vat_pv_rate": {
            "label": "TVA sur les panneaux",
            "help": "Taux de TVA appliqué uniquement aux panneaux.",
            "formula": "Calcul : prix HT panneaux x ce taux.",
            "suffix": "%",
        },
        "vat_transport_rate": {
            "label": "TVA sur le transport",
            "help": "Taux de TVA appliqué uniquement au transport.",
            "formula": "Calcul : transport HT x ce taux.",
            "suffix": "%",
        },
        "vat_standard_rate": {
            "label": "TVA sur les autres postes",
            "help": "Taux de TVA appliqué à l'onduleur, la structure, la protection, le câblage, le limiteur et la pose.",
            "formula": "Calcul : chaque autre poste HT x ce taux.",
            "suffix": "%",
        },
        "psh_hours": {
            "label": "Soleil moyen utilisé pour l'estimation",
            "help": "Nombre d'heures de soleil retenu pour tous les calculs On-Grid. Ce n'est pas lié à une ville.",
            "formula": "Calcul : puissance cible = consommation par jour / ce nombre.",
            "suffix": "heures",
        },
    }
    parameters = {}
    for row in list_ongrid_parameters():
        item = dict(row)
        item.update(friendly.get(row["key"], {}))
        parameters[row["key"]] = item
    return render_template(
        "admin/ongrid_rules.html",
        parameters=parameters,
        groups=groups,
        saved=bool(request.args.get("saved")),
    )



@bp.route("/admin/tva", methods=["GET", "POST"])
def admin_tva():
    values = {row["key"]: row["value"] for row in list_vat_rates()}
    transport_settings = [row for row in list_company_settings() if row["key"] in TRANSPORT_KEYS]
    errors = {}
    transport_error = ""
    if request.method == "POST" and request.form.get("action") == "save_transport":
        submitted = {key: request.form[key] for key in TRANSPORT_KEYS if key in request.form}
        try:
            update_company_settings(submitted)
        except TransportValidationError as exc:
            transport_error = str(exc)
            flash(transport_error, "error")
            transport_settings = [{**row, "value": submitted.get(row["key"], row["value"])} for row in transport_settings]
        else:
            flash("Tarifs de transport enregistrés avec succès.", "success")
            return redirect(url_for("main.admin_tva", _anchor="transport-heading"))
    elif request.method == "POST":
        values = {field["key"]: request.form.get(field["key"], "") for field in VAT_FIELDS}
        for field in VAT_FIELDS:
            key = field["key"]
            try:
                parse_vat_percentage(values[key])
            except TaxValidationError as exc:
                errors[key] = str(exc)
        if errors:
            for message in dict.fromkeys(errors.values()):
                flash(message, "error")
        else:
            update_vat_rates(values, changed_by=session.get("admin_user", "HeliAntha"))
            flash("Taux de TVA mis à jour avec succès", "success")
            return redirect(url_for("main.admin_tva"))
    return render_template(
        "admin/tva.html",
        profiles=VAT_PROFILES,
        fields=VAT_FIELDS,
        values=values,
        errors=errors,
        transport_settings=transport_settings,
    ), 400 if errors or transport_error else 200


@bp.route("/admin/parametres", methods=["GET", "POST"])
def admin_settings():
    settings = [
        setting
        for setting in list_company_settings()
        if setting.get("key") not in HIDDEN_COMPANY_SETTING_KEYS | TRANSPORT_KEYS
    ]
    if request.method == "POST":
        submitted = {
            setting["key"]: request.form[f"value_{setting['id']}"]
            for setting in settings if f"value_{setting['id']}" in request.form
        }
        try:
            update_company_settings(submitted)
        except TransportValidationError as exc:
            flash(str(exc), "error")
            settings = [{**setting, "value": submitted.get(setting["key"], setting["value"])} for setting in settings]
            return render_template("admin/settings.html", settings=settings), 400
        flash("Paramètres enregistrés avec succès.", "success")
        return redirect(url_for("main.admin_settings"))
    return render_template("admin/settings.html", settings=settings)


@bp.get("/admin/whatsapp")
def admin_whatsapp():
    settings = _whatsapp_admin_settings()
    outbox_items = list_whatsapp_outbox(limit=10)
    return render_template("admin/whatsapp.html", settings=settings, outbox_items=outbox_items)


@bp.get("/admin/whatsapp/status")
def admin_whatsapp_status():
    settings = _whatsapp_admin_settings()
    return jsonify(get_gateway_status(settings["gateway_url"]))


@bp.get("/admin/whatsapp/qr")
def admin_whatsapp_qr():
    settings = _whatsapp_admin_settings()
    return jsonify(get_gateway_qr(settings["gateway_url"]))


@bp.post("/admin/whatsapp/logout")
def admin_whatsapp_logout():
    settings = _whatsapp_admin_settings()
    success = gateway_logout(settings["gateway_url"])
    return jsonify(success=success)


@bp.post("/admin/whatsapp/test")
def admin_whatsapp_test():
    settings = _whatsapp_admin_settings()
    payload = request.get_json(silent=True) or {}
    phone = str(payload.get("phone") or settings.get("admin_whatsapp") or "").strip()
    message = str(payload.get("message") or "Test WhatsApp HeliAntha").strip()
    success = send_whatsapp_raw(phone, message, gateway_url=settings["gateway_url"])
    return jsonify(success=success)


@bp.post("/admin/whatsapp/retry-outbox")
def admin_whatsapp_retry_outbox():
    settings = _whatsapp_admin_settings()
    return jsonify(process_outbox(gateway_url=settings["gateway_url"]))


@bp.route("/admin/utilisateurs", methods=["GET", "POST"])
def admin_users():
    error = ""
    edit_id = request.args.get("edit_id", type=int)
    editing_user = get_user(edit_id) if edit_id else None

    if request.method == "POST":
        action = request.form.get("action", "save")
        if action == "save":
            user_id = request.form.get("user_id", type=int)
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "").strip()
            existing_user = get_user(user_id) if user_id else None
            role = (existing_user or {}).get("role") if existing_user else "Commercial"
            if role not in {"Direction", "Commercial"}:
                role = "Commercial"

            if not email:
                error = "L'email est obligatoire."
            elif not user_id and not password:
                error = "Le mot de passe est obligatoire pour un nouveau compte."
            else:
                try:
                    save_user(
                        user_id=user_id,
                        username=email,
                        display_name=email,
                        role=role,
                        active=True,
                        password=password,
                    )
                    return redirect(url_for("main.admin_users"))
                except Exception:
                    error = "Impossible d'enregistrer cet utilisateur."
            editing_user = {
                "id": user_id,
                "username": email,
                "display_name": email,
                "role": role,
                "active": 1,
            }
        elif action == "delete":
            user_id = request.form.get("user_id", type=int)
            user = get_user(user_id) if user_id else None
            current_username = session.get("admin_user", "")
            active_admins = [u for u in list_users() if u["role"] == "Direction" and u["active"]]
            if not user:
                error = "Utilisateur introuvable."
            elif user["username"] == current_username:
                error = "Vous ne pouvez pas supprimer le compte actuellement connecté."
            elif user["role"] == "Direction" and user["active"] and len(active_admins) <= 1:
                error = "Au moins un compte Direction actif doit rester disponible."
            else:
                try:
                    delete_user(user_id)
                    return redirect(url_for("main.admin_users"))
                except Exception:
                    error = "Impossible de supprimer cet utilisateur."

    return render_template(
        "admin/users.html",
        users=list_users(),
        editing_user=editing_user,
        error=error,
    )


def _catalog_form_defaults():
    return {
        "reference": "",
        "category": "",
        "brand": "",
        "model": "",
        "sale_price": "",
        "currency": "DH",
        "active": 1,
        "technical_specs": {},
    }


def _product_from_form(form, existing_product=None):
    product = _catalog_form_defaults()
    if existing_product:
        product.update(dict(existing_product))
    # Absent fields are not edits. Technical JSON is merged/validated by save_product.
    for key in ("reference", "category", "brand", "model", "sale_price", "currency", "power_w"):
        if key in form:
            product[key] = form.get(key, "").strip()
    if "power_w" not in form and "spec_power_w" in form:
        product["power_w"] = form.get("spec_power_w", "").strip()
    if "active" in form:
        product["active"] = form.get("active")
    elif "active_submitted" in form or not existing_product:
        product["active"] = 0
    specs = dict(product.get("technical_specs") or {})
    for field in technical_fields_by_category().get(product.get("category"), []):
        key = f"spec_{field['key']}"
        if key in form:
            specs[field["key"]] = form.get(key, "")
    product["technical_specs"] = specs
    return product


def _catalog_form_view_product(product: dict | None) -> dict:
    view = dict(product or {})
    # Inventory is not editable or sent to the administration's forms.
    view.pop("stock", None)
    view.pop("stock_label", None)
    view.pop("vat_rate", None)
    specs = dict(view.get("technical_specs") or {})
    for key in ("power_w", "power_kw", "capacity_kwh", "capacity_l", "voltage", "current_amp"):
        if view.get(key) not in (None, "") and (key == "power_w" or key not in specs):
            specs[key] = view.get(key)
    if view.get("category") == "pumps" and "power_hp" not in specs:
        power_kw = view.get("power_kw")
        try:
            if power_kw not in (None, ""):
                specs["power_hp"] = round(float(power_kw) / 0.7355, 1)
        except (TypeError, ValueError):
            pass
    if view.get("category") == "pumps":
        specs["curve_points"] = "\n".join(
            f"{point.get('flow_m3_h'):g}:{point.get('hmt_m'):g}"
            for point in (view.get("pump_curve_points") or [])
        )
    view["form_specs"] = specs
    return view



def _pumping_rule_section(rule_type: str) -> dict | None:
    for section in PUMPING_RULE_SECTIONS:
        if section["key"] == rule_type:
            return section
    return None


def _pumping_rule_payload(rule_type: str, form, current: dict | None = None) -> dict[str, object]:
    section = _pumping_rule_section(rule_type)
    if not section:
        return {}
    payload: dict[str, object] = {}
    current = current or {}

    for field in section.get("fields") or []:
        key = field["key"]
        raw = (form.get(f"field_{key}") or "").strip()
        kind = field.get("kind")
        if kind == "number":
            if key == "vat_rate":
                payload[key] = (
                    float(parse_vat_percentage(raw) / 100)
                    if f"field_{key}" in form
                    else current.get(key)
                )
                continue
            value = parse_number(raw, None)
            if value is None and current.get(key) not in (None, ""):
                value = current.get(key)
            if value is not None and key in {"panel_count", "sort_order"}:
                value = int(round(float(value)))
            if value is not None and key == "pump_cv":
                value = normalize_pump_cv(value)
            payload[key] = value
        elif kind == "select":
            payload[key] = raw or current.get(key) or ""
        else:
            payload[key] = raw or current.get(key) or ""

    if "title" in form or current.get("title"):
        payload["title"] = (form.get("title") or current.get("title") or "").strip()
    if "rule_key" in form or current.get("rule_key"):
        payload["rule_key"] = (form.get("rule_key") or current.get("rule_key") or "").strip()
    if "notes" in form or current.get("notes"):
        payload["notes"] = (form.get("notes") or current.get("notes") or "").strip()
    if "active" in form:
        payload["active"] = 1 if form.get("active") == "on" else 0
    elif current.get("active") is not None:
        payload["active"] = 1 if int(current.get("active") or 0) == 1 else 0
    if "sort_order" not in payload and current.get("sort_order") is not None:
        payload["sort_order"] = current.get("sort_order")
    payload["source_type"] = "heliantha"
    payload["source_name"] = "HeliAntha"
    return payload



def _decorate_catalog_product(product):
    item = dict(product)
    item["category_label"] = category_label(item.get("category"))
    item["main_characteristic"] = _main_catalog_characteristic(item)
    item["datasheet_available"] = bool(item.get("datasheet_url"))
    return item


def _main_catalog_characteristic(product):
    category = product.get("category")
    specs = product.get("technical_specs") or {}
    if category == "panels" and product.get("power_w"):
        return f"{float(product['power_w']):.0f} Wc"
    if category == "batteries" and product.get("capacity_kwh"):
        return f"{float(product['capacity_kwh']):.2f} kWh"
    if category == "pumps" and specs.get("power_hp"):
        return f"{float(specs['power_hp']):g} CV"
    if category in {"inverters", "drives", "ev_chargers"} and product.get("power_kw"):
        return f"{float(product['power_kw']):.2f} kW"
    if category == "thermal":
        if product.get("capacity_l"):
            return f"{float(product['capacity_l']):.0f} L"
        if specs.get("surface_m2"):
            return f"{float(specs['surface_m2']):.2f} m2"
    if product.get("voltage"):
        return f"{float(product['voltage']):.0f} V"
    return "Caracteristique a completer"
