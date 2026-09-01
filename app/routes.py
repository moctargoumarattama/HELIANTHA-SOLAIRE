from copy import deepcopy
from datetime import datetime, timedelta
from json import dumps as json_dumps, loads as json_loads
from pathlib import Path
from random import randint
from uuid import uuid4

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from .catalog import ProductValidationError, category_label, category_options, technical_fields_by_category
from .calculators import CalculationEngine, ValidationError
from .db import (
    dashboard_stats,
    authenticate_user,
    get_calculation_parameter,
    get_advisor_knowledge,
    get_advisor_runtime_assets,
    get_product,
    get_quote,
    get_primary_admin_user,
    get_user,
    get_quote_by_number,
    list_calculation_parameters,
    list_calculation_parameter_history,
    list_company_settings,
    list_pricing_rules,
    list_pumping_solar_rules,
    list_products,
    list_quotes,
    list_users,
    list_advisor_unknown_messages,
    list_advisor_learning_log,
    list_advisor_messages,
    list_advisor_intent_examples,
    list_advisor_synonyms,
    load_calculation_context,
    save_advisor_intent_example,
    save_advisor_knowledge_item,
    save_advisor_synonym,
    save_user,
    save_product,
    save_quote,
    save_quote_client_event,
    save_visit_request,
    create_pumping_solar_rule,
    delete_user,
    set_product_active,
    update_calculation_parameter,
    update_company_setting,
    update_advisor_unknown_status,
    update_pricing_rule,
    update_pumping_solar_rule,
    update_quote_selected_offer,
    update_quote_status,
)
from .defaults import CATEGORY_PRESENTATION, PROJECT_LABELS, PUBLIC_PROJECTS, QUOTE_STATUSES, SOURCE_TYPES
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
from .parameter_views import (
    SOURCE_OPTIONS,
    filter_and_group_parameters,
    format_display_value,
    parse_display_value,
)
from .public_presenters import build_public_quote_payload, company_profile
from .services.advisor import AdvisorService
from .services.advisor.entities import extract_dynamic_matches
from .services.advisor.intents import detect_intents
from .services.advisor.knowledge import search_knowledge
from .services.advisor.learning import similar_occurrence_count
from .services.advisor.rules import contains_any, detect_project, normalize
from .services.pump_selector import NO_STANDARD_PUMP_MESSAGE, curve_head_for_flow, select_pump_for_duty
from .wizard_projects import engine_project_for, normalize_wizard_project, wizard_projects_payload


bp = Blueprint("main", __name__)
engine = CalculationEngine()
advisor_service = AdvisorService(engine)
CATALOG_SORT_OPTIONS = [
    {"value": "catalog", "label": "Ordre catalogue"},
    {"value": "brand", "label": "Marque"},
    {"value": "stock_desc", "label": "Stock decroissant"},
    {"value": "price_asc", "label": "Prix croissant"},
    {"value": "price_desc", "label": "Prix decroissant"},
    {"value": "updated", "label": "Derniere mise a jour"},
]
CATALOG_STOCK_OPTIONS = [
    {"value": "", "label": "Tous stocks"},
    {"value": "available", "label": "Stock disponible"},
    {"value": "empty", "label": "Stock a confirmer / nul"},
]
PWA_CACHE_NAME = "heliantha-pwa-v4"
APP_ASSET_VERSION = "20260901-1"
PWA_ASSET_VERSION = "20260901-1"
PWA_CORE_PATHS = [
    "/",
    "/assets/helin.jpeg",
    "/static/css/app.css",
    "/static/css/admin.css",
    f"/static/js/app.js?v={APP_ASSET_VERSION}",
    "/static/js/public-result.js",
    "/static/js/advisor.js",
    f"/static/js/pwa.js?v={PWA_ASSET_VERSION}",
]

PRICING_RULE_PRESENTATION = {
    "vat_rate": {
        "title": "TVA",
        "group": "Prix de vente",
        "icon": "🧾",
        "help": "Taxe appliquée au total hors taxe.",
    },
    "accessories_rate": {
        "title": "Accessoires",
        "group": "Compléments techniques",
        "icon": "🔩",
        "help": "Petits accessoires nécessaires autour du matériel principal.",
    },
    "protections_rate": {
        "title": "Protections électriques",
        "group": "Compléments techniques",
        "icon": "🛡️",
        "help": "Protections, coffrets et éléments de sécurité.",
    },
    "cabling_rate": {
        "title": "Câblage",
        "group": "Compléments techniques",
        "icon": "🔌",
        "help": "Câbles et raccordements estimés.",
    },
    "structure_rate": {
        "title": "Structure de pose",
        "group": "Compléments techniques",
        "icon": "🏗️",
        "help": "Supports, rails et éléments de fixation.",
    },
    "installation_base": {
        "title": "Installation",
        "group": "Services",
        "icon": "🛠️",
        "help": "Frais minimum pour la pose de l’installation.",
    },
    "labor_base": {
        "title": "Main-d’œuvre",
        "group": "Services",
        "icon": "👷",
        "help": "Temps de travail de base prévu pour l’équipe.",
    },
    "commissioning_fee": {
        "title": "Mise en service",
        "group": "Services",
        "icon": "✅",
        "help": "Contrôle et démarrage de l’installation.",
    },
}

PRICING_GROUP_ORDER = ["Prix de vente", "Compléments techniques", "Services", "Autres"]
PRICING_RULES_HIDDEN = {"travel_fixed", "travel_cost_per_km", "margin_rate", "study_fee", "other_costs"}

ADVISOR_STATUS_LABELS = {
    "new": "À vérifier",
    "learned": "Validés",
    "ignored": "Ignorés",
}

ADVISOR_PROJECT_LABELS = {
    "pumping": "Pompage solaire",
    "offgrid": "Site sans réseau",
    "ongrid": "Réduire ma consommation",
    "hybrid": "Solaire avec batteries",
    "thermal": "Chauffage solaire",
    "ev": "Recharge électrique",
}

ADVISOR_INTENT_LABELS = {
    "request_visit": "Demande de visite",
    "request_human": "Parler à quelqu’un",
    "ask_price": "Question de prix",
    "ask_explanation": "Question technique",
    "ask_equipment": "Question matériel",
    "request_quote": "Lancer une étude",
    "change_project": "Changer de projet",
    "start_project": "Démarrer le projet",
    "greeting": "Bonjour",
    "thanks": "Remerciement",
    "give_information": "Information donnée",
    "restart": "Reprendre le projet",
}

ADVISOR_KNOWLEDGE_LABELS = {
    "battery": "Batteries",
    "inverter": "Onduleur",
    "pumping": "Pompage solaire",
    "thermal": "Thermique",
    "ev": "Recharge électrique",
    "quote": "Prix et devis",
    "general": "Réponse HeliAntha",
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

        power_cv = row.get("power_cv") or specs.get("power_hp")
        if category == "pumps":
            cv_label = clean_number(power_cv, 1)
            return f"Pompe solaire {cv_label} CV" if cv_label else "Pompe solaire"

        power_w = row.get("power_w") or specs.get("power_w") or specs.get("panel_power_w")
        if component == "panel" or category == "panels":
            power_label = clean_number(power_w, 0)
            return f"Panneaux photovoltaïques {power_label} Wc" if power_label else "Panneaux photovoltaïques"

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
        display_lines.append(row)
    return display_lines


def _financial_summary_rows(financial_breakdown: dict) -> list[dict]:
    categories = {
        item.get("key"): float(item.get("amount") or 0)
        for item in (financial_breakdown.get("categories") or [])
    }

    def total(*keys: str) -> float:
        return round(sum(categories.get(key, 0) for key in keys), 2)

    return [
        {"label": "Matériel", "amount": total("principal_equipment")},
        {"label": "Compléments", "amount": total("accessories", "protections", "cabling", "structure")},
        {"label": "Pose", "amount": total("installation", "labor")},
        {"label": "Total HT", "amount": float(financial_breakdown.get("total_ht") or 0), "emphasis": True},
        {"label": "TVA", "amount": float(financial_breakdown.get("vat") or 0)},
        {"label": "Net à payer", "amount": float(financial_breakdown.get("total_ttc") or 0), "emphasis": True},
    ]


def _advisor_status_label(status: str | None) -> str:
    return ADVISOR_STATUS_LABELS.get(status or "new", "À vérifier")


def _advisor_project_label(project_type: str | None) -> str:
    if not project_type:
        return "Projet à préciser"
    return ADVISOR_PROJECT_LABELS.get(project_type, project_type)


def _advisor_intent_label(intent: str | None) -> str:
    return ADVISOR_INTENT_LABELS.get(intent or "", "À préciser")


def _advisor_knowledge_label(category: str | None) -> str:
    return ADVISOR_KNOWLEDGE_LABELS.get(category or "", "Réponse HeliAntha")


def _advisor_title_from_message(message: str) -> str:
    text = " ".join(str(message or "").split()).strip(" .,!?:;\"'«»")
    if not text:
        return "Nouvelle question"
    words = text.split()
    if len(text) <= 48:
        return text[:1].upper() + text[1:]
    return " ".join(words[:6]).rstrip(" ,;:") + "…"


def _advisor_keywords_from_message(message: str) -> str:
    tokens = []
    for token in normalize(message).split():
        if len(token) < 4:
            continue
        if token in {"avec", "sans", "pour", "dans", "votre", "votre", "cette", "cela", "quand", "comment", "pourquoi"}:
            continue
        if token not in tokens:
            tokens.append(token)
    return ", ".join(tokens[:5])


def _advisor_context(item: dict) -> dict:
    try:
        context = json_loads(item.get("context_json") or "{}")
    except Exception:
        context = {}
    return context if isinstance(context, dict) else {}


def _build_advisor_suggestion(item: dict, runtime_assets: dict) -> dict:
    original = str(item.get("original_message") or "").strip()
    normalized = str(item.get("normalized_message") or normalize(original))
    context = _advisor_context(item)
    detected_project = (
        item.get("project_type")
        or context.get("project_type")
        or (detect_project(original, runtime_assets.get("synonyms"), runtime_assets.get("intent_examples")) or {}).get("project")
        or ""
    )
    intents = detect_intents(original, runtime_assets.get("intent_examples") or [])
    top_intent = intents[0]["intent"] if intents else "give_information"
    top_confidence = intents[0]["confidence"] if intents else 0
    knowledge_hit = search_knowledge(original, detected_project, runtime_assets.get("knowledge"))
    synonym_hits = extract_dynamic_matches(original, runtime_assets.get("synonyms"))
    question_like = "?" in original or contains_any(
        normalized,
        [
            "comment",
            "pourquoi",
            "combien",
            "c est quoi",
            "cest quoi",
            "dure",
            "autonomie",
            "pluie",
            "fonctionne",
            "marchent",
            "marche",
            "expliquer",
        ],
    )

    if synonym_hits:
        match = max(synonym_hits, key=lambda row: row.get("score", 0))
        canonical_term = match.get("canonical_term") or ""
        variant = match.get("variant") or original
        return {
            "mode": "synonym",
            "title": "Expression reconnue",
            "label": f'« {variant} » → « {canonical_term or variant} »',
            "note": _advisor_project_label(match.get("project_type") or detected_project),
            "primary_label": "✓ Valider",
            "action": "save_synonym",
            "canonical_term": canonical_term or variant,
            "variant": variant,
            "category": match.get("category") or "",
            "project_type": match.get("project_type") or detected_project,
        }

    if knowledge_hit and (question_like or top_intent in {"ask_price", "ask_explanation", "ask_equipment"}):
        question = knowledge_hit.get("question") or original
        return {
            "mode": "knowledge_existing",
            "title": "Réponse HeliAntha",
            "label": knowledge_hit.get("title") or _advisor_knowledge_label(knowledge_hit.get("category")),
            "note": "Question fréquente déjà connue.",
            "primary_label": "✓ Utiliser cette réponse",
            "action": "save_knowledge",
            "category": knowledge_hit.get("category") or "general",
            "question": question,
            "title_input": knowledge_hit.get("title") or _advisor_title_from_message(question),
            "answer": knowledge_hit.get("answer") or "",
            "keywords": knowledge_hit.get("keywords") or "",
        }

    if top_confidence >= 70 or item.get("intent") in ADVISOR_INTENT_LABELS:
        intent = item.get("intent") or top_intent
        return {
            "mode": "intent",
            "title": "Ce que le client veut faire",
            "label": _advisor_intent_label(intent),
            "note": _advisor_project_label(detected_project),
            "primary_label": "✓ Valider",
            "action": "save_intent",
            "intent": intent,
            "example_text": original,
            "project_type": detected_project,
        }

    if question_like:
        question = original or normalized
        return {
            "mode": "knowledge_new",
            "title": "Nouvelle question fréquente",
            "label": _advisor_title_from_message(question),
            "note": _advisor_project_label(detected_project),
            "primary_label": "Enregistrer la réponse",
            "action": "save_knowledge",
            "category": context.get("project_type") or detected_project or "general",
            "question": question,
            "title_input": _advisor_title_from_message(question),
            "answer": "",
            "keywords": _advisor_keywords_from_message(question),
        }

    intent = item.get("intent") or top_intent or "give_information"
    return {
        "mode": "intent",
        "title": "À vérifier",
        "label": _advisor_intent_label(intent),
        "note": _advisor_project_label(detected_project),
        "primary_label": "✓ Valider",
        "action": "save_intent",
        "intent": intent,
        "example_text": original,
        "project_type": detected_project,
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
    company = company_profile(list_company_settings())
    return render_template(
        "index.html",
        company=company,
        public_projects=PUBLIC_PROJECTS,
        project_labels=PROJECT_LABELS,
        wizard_projects=wizard_projects_payload(),
    )


@bp.get("/assets/heliantha-terrain.jpeg")
@bp.get("/assets/helin.jpeg")
def brand_image():
    return send_file(Path(__file__).resolve().parent.parent / "helin.jpeg", mimetype="image/jpeg")


@bp.get("/manifest.webmanifest")
def pwa_manifest():
    icon_url = url_for("main.brand_image")
    manifest = {
        "name": "HELIANTHA",
        "short_name": "HELIANTHA",
        "description": "HeliAntha Smart Quote pour les estimations solaires et energetiques.",
        "start_url": url_for("main.index"),
        "scope": url_for("main.index"),
        "display": "standalone",
        "display_override": ["window-controls-overlay", "standalone"],
        "orientation": "portrait",
        "background_color": "#f6f8fb",
        "theme_color": "#102638",
        "lang": "fr",
        "icons": [
            {
                "src": icon_url,
                "sizes": "192x192",
                "type": "image/jpeg",
            },
            {
                "src": icon_url,
                "sizes": "512x512",
                "type": "image/jpeg",
            },
        ],
    }
    return current_app.response_class(json_dumps(manifest, ensure_ascii=False), mimetype="application/manifest+json")


@bp.get("/service-worker.js")
def service_worker():
    core_assets = ",\n  ".join(f'"{path}"' for path in PWA_CORE_PATHS)
    source = f"""
const CACHE_NAME = "{PWA_CACHE_NAME}";
const CORE_ASSETS = [
  {core_assets}
];

const isSameOrigin = (request) => new URL(request.url).origin === self.location.origin;

self.addEventListener("install", (event) => {{
  event.waitUntil((async () => {{
    const cache = await caches.open(CACHE_NAME);
    await cache.addAll(CORE_ASSETS);
  }})());
  self.skipWaiting();
}});

self.addEventListener("activate", (event) => {{
  event.waitUntil((async () => {{
    const keys = await caches.keys();
    await Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)));
    await self.clients.claim();
  }})());
}});

self.addEventListener("fetch", (event) => {{
  const {{ request }} = event;

  if (request.method !== "GET" || !isSameOrigin(request)) {{
    return;
  }}

  const url = new URL(request.url);

  if (request.mode === "navigate") {{
    event.respondWith((async () => {{
      try {{
        return await fetch(request);
      }} catch {{
        const cache = await caches.open(CACHE_NAME);
        return (await cache.match("/")) || Response.error();
      }}
    }})());
    return;
  }}

  if (["style", "script", "image", "font"].includes(request.destination) || url.pathname.startsWith("/assets/") || url.pathname.startsWith("/static/")) {{
    event.respondWith((async () => {{
      const cache = await caches.open(CACHE_NAME);
      const cached = await cache.match(request);

      const updateCache = async () => {{
        try {{
          const response = await fetch(request);
          if (response && response.ok) {{
            await cache.put(request, response.clone());
          }}
        }} catch {{}}
      }};

      if (cached) {{
        event.waitUntil(updateCache());
        return cached;
      }}

      try {{
        const response = await fetch(request);
        if (response && response.ok) {{
          await cache.put(request, response.clone());
        }}
        return response;
      }} catch {{
        return (await cache.match("/")) || Response.error();
      }}
    }})());
  }}
}});
""".strip()
    return current_app.response_class(source, mimetype="application/javascript")


@bp.get("/health")
def health():
    return jsonify(status="ok", engine=engine.version)


def _advisor_session_key():
    if not session.get("advisor_session_key"):
        session["advisor_session_key"] = uuid4().hex
    return session["advisor_session_key"]


@bp.post("/api/advisor/message")
def advisor_message():
    payload = request.get_json(silent=True) or {}
    reply = advisor_service.handle_message(
        _advisor_session_key(),
        str(payload.get("message", "")),
        payload.get("state") or {},
    )
    return jsonify(reply)


@bp.post("/api/advisor/calculate")
def advisor_calculate():
    payload = request.get_json(silent=True) or {}
    reply = advisor_service.calculate(
        _advisor_session_key(),
        payload.get("state") or {},
        payload.get("contact") or {},
    )
    return jsonify(reply), 200 if reply.get("ok", True) else 400


@bp.post("/api/calculate")
def calculate():
    payload = request.get_json(silent=True) or {}
    project = normalize_wizard_project(payload.get("project_type") or payload.get("project") or "")
    if not project:
        return jsonify(error="Projet non reconnu."), 400
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
    save_quote(result["quote_number"], engine_project, data, contact, result)
    result["public_url"] = url_for("main.public_quote", quote_number=result["quote_number"])
    return jsonify(result)


@bp.get("/simulation/<quote_number>")
def public_quote(quote_number):
    quote = get_quote_by_number(quote_number)
    if not quote:
        abort(404)
    company = company_profile(list_company_settings())
    payload = build_public_quote_payload(quote, company)
    save_quote_client_event(quote["id"], quote["quote_number"], "public_view", request.args.get("from", "direct"))
    return render_template("public_quote.html", quote=quote, public_view=payload, company=company, print_mode=False)


@bp.get("/simulation/<quote_number>/predevis")
def public_quote_print(quote_number):
    quote = get_quote_by_number(quote_number)
    if not quote:
        abort(404)
    save_quote_client_event(quote["id"], quote["quote_number"], "print_view", "predevis")
    display_equipment_lines = _display_equipment_lines(quote.get("selected_equipment") or [])
    financial_summary_rows = _financial_summary_rows(quote.get("financial_breakdown") or {})
    return render_template(
        "admin/quote_pdf.html",
        quote=quote,
        project_labels=PROJECT_LABELS,
        display_equipment_lines=display_equipment_lines,
        financial_summary_rows=financial_summary_rows,
    )


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
        statuses=QUOTE_STATUSES,
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
        pumps.append({**product, "_method_power_hp": power_hp, "_method_curve": curve})
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


def _method_candidates(pumps, flow_m3_h, hmt_m):
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
        candidates.append({
            "cv": cv,
            "cv_label": format_cv(cv),
            "variant_index": variant_counts[cv],
            "interval_label": _method_interval_label(duty),
            "hmt_label": f"{_method_decimal(available_hmt, 1)} m" if available_hmt is not None else "—",
            "status": status,
            "status_tone": status_tone,
            "compatible": compatible,
            "price": float(pump.get("sale_price") or 0) if pump.get("sale_price") not in (None, "") else None,
            "price_label": format_price(pump.get("sale_price")),
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
            "le prix Admin actuel le plus faible les départage."
        )
    if not rule:
        lines.append("La configuration solaire HeliAntha correspondante n'est pas encore définie.")
    else:
        lines.append("Le CV retenu est envoyé vers la règle solaire HeliAntha active.")
    lines.append(f"→ {format_cv(selected_cv)} retenu.")
    return {
        "status": "selected",
        "title": f"{format_cv(selected_cv)} retenu",
        "selected_cv": selected_cv,
        "selected_cv_label": format_cv(selected_cv),
        "selected_price_label": format_price(selection.get("current_price")),
        "solar_rule_missing": not bool(rule),
        "lines": lines,
    }


def _method_performance_groups(pumps):
    groups = []
    by_cv = {}
    for pump in pumps:
        by_cv.setdefault(pump["_method_power_hp"], []).append(pump)
    for cv, variants in sorted(by_cv.items()):
        group = {"cv": cv, "cv_label": format_cv(cv), "variants": []}
        for index, pump in enumerate(variants, start=1):
            specs = pump.get("technical_specs") or {}
            group["variants"].append({
                "label": f"Variante technique {index}",
                "power_kw": format_power_kw(pump.get("power_kw") or specs.get("power_kw")),
                "voltage": f"{_method_decimal(pump.get('voltage') or specs.get('voltage_v'), 0)} V" if (pump.get("voltage") or specs.get("voltage_v")) not in (None, "") else "—",
                "current": f"{_method_decimal(pump.get('current_amp') or specs.get('current_a'), 1)} A" if (pump.get("current_amp") or specs.get("current_a")) not in (None, "") else "—",
                "price": format_price(pump.get("sale_price")),
                "points": pump["_method_curve"],
            })
        groups.append(group)
    return groups


def _pumping_method_view(flow_value="", hmt_value=""):
    context = load_calculation_context()
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
            candidates = _method_candidates(pumps, flow, hmt)
            selected_cv = float(selection["selected_pump_cv"]) if selection else None
            rule = _method_rule_for_cv(context, selected_cv) if selected_cv else None
            selected_duty = selection.get("duty") if selection else None
            analysis = {
                "flow_label": f"{_method_decimal(flow, 1)} m³/h",
                "hmt_label": f"{_method_decimal(hmt, 1)} m",
                "interval_label": _method_interval_label(selected_duty),
                "policy_label": _method_policy_label((selected_duty or {}).get("policy")),
                "candidates": candidates,
                "decision": _method_decision(selection, candidates, rule),
                "solar_config": _method_solar_config(rule),
            }
    return {
        "summary": summary,
        "flow_value": flow_value,
        "hmt_value": hmt_value,
        "analysis": analysis,
        "error": error,
        "performance_groups": _method_performance_groups(pumps),
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


def _visit_request_signature(visit):
    return tuple(
        str(visit.get(key) or "").strip().lower()
        for key in ("preferred_date", "time_slot", "address", "phone", "comment", "status")
    )


def _visit_request_display_summary(visits):
    visits = [dict(visit) for visit in visits or []]
    if not visits:
        return {"latest": None, "groups": [], "total": 0, "unique_count": 0, "duplicate_count": 0}
    groups_by_signature = {}
    groups = []
    for visit in visits:
        signature = _visit_request_signature(visit)
        group = groups_by_signature.get(signature)
        if not group:
            group = {
                "visit": visit,
                "count": 0,
                "created_at_values": [],
            }
            groups_by_signature[signature] = group
            groups.append(group)
        group["count"] += 1
        if visit.get("created_at"):
            group["created_at_values"].append(visit.get("created_at"))

    latest = visits[0]
    for group in groups:
        created_values = group["created_at_values"]
        group["first_created_at"] = created_values[-1] if created_values else ""
        group["last_created_at"] = created_values[0] if created_values else ""
        group["duplicate_label"] = (
            f"{group['count']} demandes identiques"
            if group["count"] > 1
            else "1 demande"
        )
    latest_signature = _visit_request_signature(latest)
    latest_group = groups_by_signature.get(latest_signature) or groups[0]
    other_groups = [group for group in groups if group is not latest_group]
    return {
        "latest": latest,
        "latest_group": latest_group,
        "groups": groups,
        "other_groups": other_groups,
        "total": len(visits),
        "unique_count": len(groups),
        "duplicate_count": len(visits) - len(groups),
    }


@bp.get("/admin/devis")
def admin_quotes():
    quotes = list_quotes()
    return render_template(
        "admin/quotes.html",
        quotes=quotes,
        project_labels=PROJECT_LABELS,
        public_projects=PUBLIC_PROJECTS,
        statuses=QUOTE_STATUSES,
        filters=request.args,
    )


@bp.get("/admin/devis/<int:quote_id>")
def admin_quote_detail(quote_id):
    quote = get_quote(quote_id)
    if not quote:
        abort(404)
    calculation_detail = quote.get("calculation_detail") or {}
    bom = quote.get("bom") or calculation_detail.get("bom", {})
    bom_lines = _display_equipment_lines((bom or {}).get("lines") or quote.get("selected_equipment") or [])
    financial_summary_rows = _financial_summary_rows(quote.get("financial_breakdown") or {})
    visit_summary = _visit_request_display_summary(quote.get("visit_requests") or [])
    return render_template(
        "admin/quote_detail.html",
        quote=quote,
        project_labels=PROJECT_LABELS,
        statuses=QUOTE_STATUSES,
        display_equipment_lines=bom_lines,
        financial_summary_rows=financial_summary_rows,
        visit_summary=visit_summary,
    )


@bp.get("/admin/devis/<int:quote_id>/pdf")
def admin_quote_pdf(quote_id):
    quote = get_quote(quote_id)
    if not quote:
        abort(404)
    display_equipment_lines = _display_equipment_lines(quote.get("selected_equipment") or [])
    financial_summary_rows = _financial_summary_rows(quote.get("financial_breakdown") or {})
    return render_template(
        "admin/quote_pdf.html",
        quote=quote,
        project_labels=PROJECT_LABELS,
        display_equipment_lines=display_equipment_lines,
        financial_summary_rows=financial_summary_rows,
    )


@bp.post("/admin/devis/<int:quote_id>/status")
def admin_quote_status(quote_id):
    update_quote_status(quote_id, request.form.get("status", "Nouveau"), session.get("admin_user", "admin"))
    return redirect(url_for("main.admin_quote_detail", quote_id=quote_id))


@bp.get("/admin/prospects")
def admin_prospects():
    quotes = list_quotes()
    return render_template(
        "admin/prospects.html",
        quotes=quotes,
        project_labels=PROJECT_LABELS,
        public_projects=PUBLIC_PROJECTS,
        statuses=QUOTE_STATUSES,
        filters=request.args,
    )


@bp.get("/admin/catalogue")
def admin_catalog():
    filters = {
        "q": request.args.get("q", ""),
        "category": request.args.get("category", ""),
        "active": request.args.get("active", ""),
        "brand": request.args.get("brand", ""),
        "stock": request.args.get("stock", ""),
        "sort": request.args.get("sort", "catalog"),
    }
    products = [
        _decorate_catalog_product(item)
        for item in list_products(
            search=filters["q"],
            category=filters["category"],
            active=filters["active"],
            brand=filters["brand"],
            stock=filters["stock"],
            sort=filters["sort"],
        )
    ]
    return render_template(
        "admin/catalog.html",
        products=products,
        filters=filters,
        category_options=category_options(),
        sort_options=CATALOG_SORT_OPTIONS,
        stock_options=CATALOG_STOCK_OPTIONS,
    )


@bp.route("/admin/catalogue/new", methods=["GET", "POST"])
def admin_catalog_new():
    product = _catalog_form_defaults()
    errors = {}
    if request.method == "POST":
        product = _product_from_form(request.form)
        try:
            save_product(product, submitted_fields=request.form)
        except ProductValidationError as exc:
            errors = exc.errors
        else:
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
    if request.method == "POST":
        product = _product_from_form(request.form, existing_product=product)
        try:
            save_product(product, product_id=product_id, submitted_fields=request.form)
        except ProductValidationError as exc:
            errors = exc.errors
        else:
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
    set_product_active(product_id, not bool(product.get("active")))
    return redirect(url_for("main.admin_catalog"))


@bp.route("/admin/parametres-calcul", methods=["GET", "POST"])
def admin_calculation_parameters():
    if request.method == "POST":
        param_id = int(request.form.get("parameter_id", "0"))
        param = get_calculation_parameter(param_id)
        if not param:
            abort(404)
        if not param.get("admin_visible"):
            abort(403)
        if not param.get("editable"):
            abort(403)
        try:
            value = parse_display_value(param.get("display_kind") or param.get("unit") or "", request.form.get("display_value", ""))
        except ValueError:
            return redirect(url_for("main.admin_calculation_parameters", error="value"))

        update_calculation_parameter(
            param_id,
            value,
            active=request.form.get("active") == "on",
            source_type="heliantha",
            source_name="HeliAntha",
            source_reference="",
            validated_by="",
            validated_at="",
            changed_by=session.get("admin_user", "admin"),
            change_comment=request.form.get("change_comment", "").strip(),
        )
        return redirect(url_for(
            "main.admin_calculation_parameters",
            q=request.args.get("q", ""),
            category=request.args.get("category", ""),
            updated=param_id,
        ))

    parameters = [
        param
        for param in list_calculation_parameters(admin_visible_only=True)
        if param.get("category") != "Pompage"
    ]
    groups = filter_and_group_parameters(
        parameters,
        search=request.args.get("q", ""),
        category=request.args.get("category", ""),
    )
    categories = {key: value for key, value in CATEGORY_PRESENTATION.items() if key != "Pompage"}
    history = _format_parameter_history(list_calculation_parameter_history())
    return render_template(
        "admin/calculation_parameters.html",
        groups=groups,
        parameters=parameters,
        filters=request.args,
        categories=categories,
        source_options=SOURCE_OPTIONS,
        source_types=SOURCE_TYPES,
        history=history,
    )


@bp.route("/admin/tarification", methods=["GET", "POST"])
def admin_pricing():
    if request.method == "POST":
        for rule in list_pricing_rules():
            value = request.form.get(f"value_{rule['id']}", rule["value"])
            parsed_value = _float_or_none(value) or 0
            if rule.get("unit") == "ratio" and abs(parsed_value) > 1:
                parsed_value = parsed_value / 100
            active = request.form.get(f"active_{rule['id']}") == "on"
            update_pricing_rule(rule["id"], parsed_value, active)
        return redirect(url_for("main.admin_pricing"))
    return render_template("admin/pricing.html", pricing_groups=_decorate_pricing_rules(list_pricing_rules()))


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
        payload = _pumping_rule_payload(rule_type, request.form, current)

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


@bp.get("/admin/referentiel-technique")
def admin_references():
    return redirect(url_for("main.admin_calculation_parameters"))


@bp.route("/admin/conseiller", methods=["GET", "POST"])
def admin_advisor():
    status = request.args.get("status", "new").strip() or "new"
    if status not in {"new", "learned", "ignored"}:
        status = "new"

    if request.method == "POST":
        action = request.form.get("action", "").strip()
        item_id = request.form.get("item_id", type=int)
        admin_name = session.get("admin_user", "HeliAntha")
        if action == "ignore" and item_id:
            update_advisor_unknown_status(item_id, "ignored")
        elif action == "save_intent" and item_id:
            save_advisor_intent_example(
                request.form.get("intent", "").strip(),
                request.form.get("example_text", "").strip(),
                project_type=request.form.get("project_type", "").strip(),
                validated_by=admin_name,
            )
            update_advisor_unknown_status(item_id, "learned")
        elif action == "save_synonym" and item_id:
            save_advisor_synonym(
                request.form.get("canonical_term", "").strip(),
                request.form.get("variant", "").strip(),
                category=request.form.get("category", "").strip(),
                project_type=request.form.get("project_type", "").strip(),
                validated_by=admin_name,
            )
            update_advisor_unknown_status(item_id, "learned")
        elif action == "save_knowledge" and item_id:
            save_advisor_knowledge_item(
                request.form.get("category", "").strip() or "general",
                request.form.get("title", "").strip() or request.form.get("question", "").strip(),
                request.form.get("question", "").strip(),
                request.form.get("answer", "").strip(),
                keywords=request.form.get("keywords", "").strip(),
                validated_by=admin_name,
            )
            update_advisor_unknown_status(item_id, "learned")
        return redirect(url_for("main.admin_advisor", status=status))

    unknown_messages = list_advisor_unknown_messages(status=status)
    for item in unknown_messages:
        item["similar_count"] = similar_occurrence_count(item, unknown_messages)
        item["project_label"] = _advisor_project_label(item.get("project_type"))
        item["status_label"] = _advisor_status_label(item.get("status"))

    runtime_assets = get_advisor_runtime_assets()
    current_item = unknown_messages[0] if unknown_messages else None
    suggestion = _build_advisor_suggestion(current_item, runtime_assets) if current_item else None
    knowledge_rows = get_advisor_knowledge()
    synonym_rows = list_advisor_synonyms()
    intent_example_rows = list_advisor_intent_examples()
    conversation_rows = list_advisor_messages(limit=24)
    learning_log = list_advisor_learning_log(limit=24)

    today = datetime.now()
    week_threshold = today - timedelta(days=7)
    weekly_count = 0
    for row in learning_log:
        created_at = str(row.get("created_at") or "")
        try:
            created = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if created >= week_threshold:
            weekly_count += 1
    for item in knowledge_rows:
        item["category_label"] = _advisor_knowledge_label(item.get("category"))
    for item in intent_example_rows:
        item["intent_label"] = _advisor_intent_label(item.get("intent"))
    for item in conversation_rows:
        item["role_label"] = "Client" if item.get("role") == "user" else "Conseiller"
    for item in learning_log:
        item["learning_label"] = {
            "intent": "Ce que les clients veulent faire",
            "synonym": "Expressions reconnues",
            "knowledge": "Réponses HeliAntha",
        }.get(item.get("learning_type"), "Historique")
    return render_template(
        "admin/advisor.html",
        unknown_messages=unknown_messages,
        current_item=current_item,
        suggestion=suggestion,
        knowledge_rows=knowledge_rows,
        synonym_rows=synonym_rows,
        intent_example_rows=intent_example_rows,
        conversation_rows=conversation_rows,
        learning_log=learning_log,
        runtime_assets=runtime_assets,
        filters=request.args,
        current_status=status,
        current_status_label=_advisor_status_label(status),
        current_index=1 if current_item else 0,
        remaining_count=max(len(unknown_messages) - 1, 0),
        pending_count=len(unknown_messages),
        weekly_count=weekly_count,
        response_count=len(runtime_assets.get("knowledge") or []),
    )


@bp.route("/admin/parametres", methods=["GET", "POST"])
def admin_settings():
    settings = list_company_settings()
    if request.method == "POST":
        for setting in settings:
            update_company_setting(setting["id"], request.form.get(f"value_{setting['id']}", setting["value"]))
        return redirect(url_for("main.admin_settings"))
    return render_template("admin/settings.html", settings=settings)


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
        "stock": 0,
        "vat_rate": None,
        "currency": "DH",
        "active": 1,
        "technical_specs": {},
    }


def _product_from_form(form, existing_product=None):
    product = _catalog_form_defaults()
    if existing_product:
        product.update(dict(existing_product))
    product.update({
        "reference": form.get("reference", "").strip(),
        "category": form.get("category", "").strip(),
        "brand": form.get("brand", "").strip(),
        "model": form.get("model", "").strip(),
        "sale_price": form.get("sale_price", "").strip(),
        "stock": (
            (existing_product or {}).get("stock", 0)
            if form.get("category", "").strip() == "pumps"
            else form.get("stock", "").strip()
        ),
        "vat_rate": form.get("vat_rate", "").strip(),
        "currency": form.get("currency", "DH").strip(),
        "active": 1 if form.get("active") == "on" else 0,
    })
    technical_specs = {}
    for fields in technical_fields_by_category().values():
        for field in fields:
            form_key = f"spec_{field['key']}"
            if form_key not in form:
                continue
            raw_value = form.get(form_key, "")
            if raw_value in (None, ""):
                technical_specs.pop(field["key"], None)
            else:
                technical_specs[field["key"]] = raw_value
    product["technical_specs"] = technical_specs
    return product


def _catalog_form_view_product(product: dict | None) -> dict:
    view = dict(product or {})
    specs = dict(view.get("technical_specs") or {})
    for key in ("power_w", "power_kw", "capacity_kwh", "capacity_l", "voltage", "current_amp"):
        if view.get(key) not in (None, "") and key not in specs:
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


def _float_or_none(value):
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except ValueError:
        return None


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
            value = parse_number(raw, None)
            if value is None and current.get(key) not in (None, ""):
                value = current.get(key)
            if value is not None and key in {"panel_count", "sort_order"}:
                value = int(round(float(value)))
            if value is not None and key == "pump_cv":
                value = normalize_pump_cv(value)
            if value is not None and key == "vat_rate" and float(value) > 1:
                value = float(value) / 100
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


def _decorate_pricing_rules(rules):
    grouped = {group: [] for group in PRICING_GROUP_ORDER}
    grouped["Autres"] = grouped.get("Autres", [])
    for rule in rules:
        item = dict(rule)
        if item.get("key") in PRICING_RULES_HIDDEN:
            continue
        presentation = PRICING_RULE_PRESENTATION.get(item.get("key"), {})
        value = float(item.get("value") or 0)
        is_ratio = item.get("unit") == "ratio"
        item["display_title"] = presentation.get("title") or item.get("name") or item.get("key")
        item["display_group"] = presentation.get("group") or "Autres"
        item["display_icon"] = presentation.get("icon") or "⚙️"
        item["plain_help"] = presentation.get("help") or "Règle utilisée dans le calcul du prix final."
        item["display_value"] = value * 100 if is_ratio else value
        item["display_unit"] = "%" if is_ratio else (item.get("unit") or "")
        item["type_label"] = "Pourcentage" if is_ratio else ("Montant fixe" if item.get("value_type") == "fixed" else "Distance")
        item["internal_value"] = value
        grouped.setdefault(item["display_group"], []).append(item)
    return [
        {"name": group, "rules": grouped.get(group, [])}
        for group in PRICING_GROUP_ORDER
        if grouped.get(group)
    ]


def _decorate_catalog_product(product):
    item = dict(product)
    item["category_label"] = category_label(item.get("category"))
    item["main_characteristic"] = _main_catalog_characteristic(item)
    item["datasheet_available"] = bool(item.get("datasheet_url"))
    item["stock_label"] = (
        ""
        if item.get("category") == "pumps"
        else ("Disponible" if float(item.get("stock") or 0) > 0 else "A confirmer")
    )
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


def _format_parameter_history(rows):
    formatted = []
    for row in rows:
        item = dict(row)
        base = {"display_kind": item.get("display_kind"), "unit": item.get("unit")}
        item["old_display"] = format_display_value({**base, "value": item.get("old_value")})
        item["new_display"] = format_display_value({**base, "value": item.get("new_value")})
        item["source_badge"] = SOURCE_TYPES.get(item.get("source_type") or "heliantha", SOURCE_TYPES["heliantha"])["badge"]
        item["display_name"] = item.get("display_name") or item.get("name") or item.get("parameter_key")
        formatted.append(item)
    return formatted
