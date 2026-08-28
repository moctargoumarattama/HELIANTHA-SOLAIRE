from datetime import datetime, timedelta
from json import loads as json_loads
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
    delete_user,
    set_product_active,
    update_calculation_parameter,
    update_company_setting,
    update_advisor_unknown_status,
    update_pricing_rule,
    update_quote_selected_offer,
    update_quote_status,
)
from .defaults import CATEGORY_PRESENTATION, PROJECT_LABELS, PUBLIC_PROJECTS, QUOTE_STATUSES, SOURCE_TYPES
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

PRICING_RULE_PRESENTATION = {
    "margin_rate": {
        "title": "Marge commerciale",
        "group": "Prix de vente",
        "icon": "💼",
        "help": "Part ajoutée pour couvrir la marge HeliAntha.",
    },
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
    "study_fee": {
        "title": "Frais d’étude",
        "group": "Services",
        "icon": "📋",
        "help": "Montant ajouté si l’étude doit être facturée.",
    },
    "travel_fixed": {
        "title": "Déplacement minimum",
        "group": "Déplacement",
        "icon": "🚗",
        "help": "Frais minimum de déplacement.",
    },
    "travel_cost_per_km": {
        "title": "Prix par kilomètre",
        "group": "Déplacement",
        "icon": "📍",
        "help": "Coût ajouté selon la distance du projet.",
    },
    "other_costs": {
        "title": "Autres frais",
        "group": "Autres",
        "icon": "➕",
        "help": "Ligne de secours pour un coût fixe supplémentaire.",
    },
}

PRICING_GROUP_ORDER = ["Prix de vente", "Compléments techniques", "Services", "Déplacement", "Autres"]

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
    return [item for item in (lines or []) if not _is_placeholder_equipment_line(item)]


def _financial_summary_rows(financial_breakdown: dict) -> list[dict]:
    categories = {
        item.get("key"): float(item.get("amount") or 0)
        for item in (financial_breakdown.get("categories") or [])
    }

    def total(*keys: str) -> float:
        return round(sum(categories.get(key, 0) for key in keys), 2)

    return [
        {"label": "Matériel principal", "amount": total("principal_equipment")},
        {"label": "Compléments techniques", "amount": total("accessories", "protections", "cabling", "structure")},
        {"label": "Services et frais", "amount": total("installation", "labor", "travel", "other_costs")},
        {"label": "Sous-total avant marge", "amount": float(financial_breakdown.get("subtotal_before_margin") or 0), "emphasis": True},
        {"label": "Marge commerciale", "amount": float(financial_breakdown.get("commercial_margin") or 0)},
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
    )


@bp.get("/assets/helin.jpeg")
@bp.get("/assets/heliantha-terrain.jpeg")
def brand_image():
    return send_file(Path(__file__).resolve().parent.parent / "helin.jpeg", mimetype="image/jpeg")


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
    project = str(payload.get("project", ""))
    if project == "iot":
        return jsonify(error="IoT / systèmes embarqués est temporairement hors périmètre de cette version."), 400
    data = payload.get("data") or {}
    contact = payload.get("contact") or {}
    try:
        result = engine.calculate(project, data, context=load_calculation_context())
    except ValidationError as exc:
        return jsonify(error=str(exc)), 400
    except Exception:
        current_app.logger.exception("HeliAntha calculate failed for project=%s", project)
        return jsonify(error="Nous n'avons pas pu terminer l'étude. Vérifiez vos informations ou réessayez."), 500

    result["quote_number"] = f"HSQ-{datetime.now():%Y%m%d}-{randint(1000, 9999)}"
    result["created_at"] = datetime.now().strftime("%d/%m/%Y à %H:%M")
    save_quote(result["quote_number"], project, data, contact, result)
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
    return render_template(
        "admin/quote_detail.html",
        quote=quote,
        project_labels=PROJECT_LABELS,
        statuses=QUOTE_STATUSES,
        display_equipment_lines=bom_lines,
        financial_summary_rows=financial_summary_rows,
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
        product=product,
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
        product=product,
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

    parameters = list_calculation_parameters(admin_visible_only=True)
    groups = filter_and_group_parameters(
        parameters,
        search=request.args.get("q", ""),
        category=request.args.get("category", ""),
    )
    history = _format_parameter_history(list_calculation_parameter_history())
    return render_template(
        "admin/calculation_parameters.html",
        groups=groups,
        parameters=parameters,
        filters=request.args,
        categories=CATEGORY_PRESENTATION,
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
        "subcategory": "",
        "brand": "",
        "model": "",
        "description": "",
        "power_kw": "",
        "power_w": "",
        "voltage": "",
        "current_amp": "",
        "capacity_kwh": "",
        "capacity_l": "",
        "efficiency": "",
        "technology": "",
        "purchase_price": "",
        "sale_price": "",
        "supplier": "",
        "stock": 0,
        "unit": "piece",
        "warranty": "",
        "vat_rate": 0.20,
        "currency": "DH",
        "datasheet_url": "",
        "priority": 0,
        "preferred": 0,
        "demo": 1,
        "active": 1,
        "technical_specs": {},
    }


def _product_from_form(form, existing_product=None):
    product = _catalog_form_defaults()
    product.update({
        "reference": form.get("reference", "").strip(),
        "category": form.get("category", "").strip(),
        "subcategory": form.get("subcategory", "").strip(),
        "brand": form.get("brand", "").strip(),
        "model": form.get("model", "").strip(),
        "description": form.get("description", "").strip(),
        "power_kw": form.get("power_kw", "").strip(),
        "power_w": form.get("power_w", "").strip(),
        "voltage": form.get("voltage", "").strip(),
        "current_amp": form.get("current_amp", "").strip(),
        "capacity_kwh": form.get("capacity_kwh", "").strip(),
        "capacity_l": form.get("capacity_l", "").strip(),
        "efficiency": form.get("efficiency", "").strip(),
        "technology": form.get("technology", "").strip(),
        "purchase_price": form.get("purchase_price", "").strip(),
        "sale_price": form.get("sale_price", "").strip(),
        "supplier": form.get("supplier", "").strip(),
        "stock": form.get("stock", "").strip(),
        "unit": form.get("unit", "piece").strip(),
        "warranty": form.get("warranty", "").strip(),
        "vat_rate": form.get("vat_rate", "").strip(),
        "currency": form.get("currency", "DH").strip(),
        "datasheet_url": form.get("datasheet_url", "").strip(),
        "priority": form.get("priority", "").strip(),
        "preferred": 1 if form.get("preferred") == "on" else 0,
        "demo": 1 if form.get("demo") == "on" else 0,
        "active": 1 if form.get("active") == "on" else 0,
    })
    technical_specs = dict((existing_product or {}).get("technical_specs") or {})
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


def _float_or_none(value):
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def _decorate_pricing_rules(rules):
    grouped = {group: [] for group in PRICING_GROUP_ORDER}
    grouped["Autres"] = grouped.get("Autres", [])
    for rule in rules:
        item = dict(rule)
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
    item["stock_label"] = "Disponible" if float(item.get("stock") or 0) > 0 else "A confirmer"
    return item


def _main_catalog_characteristic(product):
    category = product.get("category")
    specs = product.get("technical_specs") or {}
    if category == "panels" and product.get("power_w"):
        return f"{float(product['power_w']):.0f} Wc"
    if category == "batteries" and product.get("capacity_kwh"):
        return f"{float(product['capacity_kwh']):.2f} kWh"
    if category in {"inverters", "pumps", "drives", "ev_chargers"} and product.get("power_kw"):
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
