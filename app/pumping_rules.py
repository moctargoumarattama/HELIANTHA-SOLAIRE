from __future__ import annotations

from copy import deepcopy


PUMPING_SOLAR_RULE_DEFAULTS = [
    {
        "rule_key": "pump-2cv",
        "rule_type": "pump_configuration",
        "title": "2 CV",
        "pump_cv": 2,
        "panel_count": 6,
        "panel_power_w": 400,
        "drive_power_kw": 2.2,
        "phase": "monophase",
        "drive_brand": "INVT",
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 10,
    },
    {
        "rule_key": "pump-3cv",
        "rule_type": "pump_configuration",
        "title": "3 CV",
        "pump_cv": 3,
        "panel_count": 6,
        "panel_power_w": 400,
        "drive_power_kw": 2.2,
        "phase": "monophase",
        "drive_brand": "INVT",
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 20,
    },
    {
        "rule_key": "pump-5_5cv",
        "rule_type": "pump_configuration",
        "title": "5,5 CV",
        "pump_cv": 5.5,
        "panel_count": 12,
        "panel_power_w": 590,
        "drive_power_kw": 5.5,
        "phase": "triphase",
        "drive_brand": "VEICHI",
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 30,
    },
    {
        "rule_key": "pump-7_5cv",
        "rule_type": "pump_configuration",
        "title": "7,5 CV",
        "pump_cv": 7.5,
        "panel_count": 14,
        "panel_power_w": 590,
        "drive_power_kw": 7.5,
        "phase": "triphase",
        "drive_brand": "VEICHI",
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 40,
    },
    {
        "rule_key": "pump-10cv",
        "rule_type": "pump_configuration",
        "title": "10 CV",
        "pump_cv": 10,
        "panel_count": 15,
        "panel_power_w": 715,
        "drive_power_kw": 11,
        "phase": "triphase",
        "drive_brand": "VEICHI",
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 50,
    },
    {
        "rule_key": "pump-15cv",
        "rule_type": "pump_configuration",
        "title": "15 CV",
        "pump_cv": 15,
        "panel_count": 24,
        "panel_power_w": 715,
        "drive_power_kw": 15,
        "phase": "triphase",
        "drive_brand": "VEICHI",
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 60,
    },
    {
        "rule_key": "pump-20cv",
        "rule_type": "pump_configuration",
        "title": "20 CV",
        "pump_cv": 20,
        "panel_count": 30,
        "panel_power_w": 715,
        "drive_power_kw": 18,
        "phase": "triphase",
        "drive_brand": "VEICHI",
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 70,
    },
    {
        "rule_key": "pump-30cv",
        "rule_type": "pump_configuration",
        "title": "30 CV",
        "pump_cv": 30,
        "panel_count": 45,
        "panel_power_w": 715,
        "drive_power_kw": 30,
        "phase": "triphase",
        "drive_brand": "VEICHI",
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 80,
    },
    {
        "rule_key": "pump-40cv",
        "rule_type": "pump_configuration",
        "title": "40 CV",
        "pump_cv": 40,
        "panel_count": 60,
        "panel_power_w": 715,
        "drive_power_kw": 37,
        "phase": "triphase",
        "drive_brand": "VEICHI",
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 90,
    },
    {
        "rule_key": "pump-50cv",
        "rule_type": "pump_configuration",
        "title": "50 CV",
        "pump_cv": 50,
        "panel_count": 75,
        "panel_power_w": 715,
        "drive_power_kw": 45,
        "phase": "triphase",
        "drive_brand": "VEICHI",
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 100,
    },
    {
        "rule_key": "drive-invt-2_2-mono",
        "rule_type": "drive_pricing",
        "title": "2,2 kW monophasé INVT",
        "drive_power_kw": 2.2,
        "phase": "monophase",
        "drive_brand": "INVT",
        "drive_reference": "DRV-INVT-2.2",
        "unit_price_ht": 1800,
        "drive_sale_price_ht": 1800,
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 10,
    },
    {
        "rule_key": "drive-veichi-5_5",
        "rule_type": "drive_pricing",
        "title": "5,5 kW triphasé VEICHI",
        "drive_power_kw": 5.5,
        "phase": "triphase",
        "drive_brand": "VEICHI",
        "unit_price_ht": None,
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 20,
    },
    {
        "rule_key": "drive-veichi-7_5",
        "rule_type": "drive_pricing",
        "title": "7,5 kW triphasé VEICHI",
        "drive_power_kw": 7.5,
        "phase": "triphase",
        "drive_brand": "VEICHI",
        "unit_price_ht": None,
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 30,
    },
    {
        "rule_key": "drive-veichi-11",
        "rule_type": "drive_pricing",
        "title": "11 kW triphasé VEICHI",
        "drive_power_kw": 11,
        "phase": "triphase",
        "drive_brand": "VEICHI",
        "unit_price_ht": None,
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 40,
    },
    {
        "rule_key": "drive-veichi-15",
        "rule_type": "drive_pricing",
        "title": "15 kW triphasé VEICHI",
        "drive_power_kw": 15,
        "phase": "triphase",
        "drive_brand": "VEICHI",
        "unit_price_ht": None,
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 50,
    },
    {
        "rule_key": "drive-veichi-18",
        "rule_type": "drive_pricing",
        "title": "18 kW triphasé VEICHI",
        "drive_power_kw": 18,
        "phase": "triphase",
        "drive_brand": "VEICHI",
        "unit_price_ht": None,
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 60,
    },
    {
        "rule_key": "drive-veichi-30",
        "rule_type": "drive_pricing",
        "title": "30 kW triphasé VEICHI",
        "drive_power_kw": 30,
        "phase": "triphase",
        "drive_brand": "VEICHI",
        "unit_price_ht": None,
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 70,
    },
    {
        "rule_key": "drive-veichi-37",
        "rule_type": "drive_pricing",
        "title": "37 kW triphasé VEICHI",
        "drive_power_kw": 37,
        "phase": "triphase",
        "drive_brand": "VEICHI",
        "unit_price_ht": None,
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 80,
    },
    {
        "rule_key": "drive-veichi-45",
        "rule_type": "drive_pricing",
        "title": "45 kW triphasé VEICHI",
        "drive_power_kw": 45,
        "phase": "triphase",
        "drive_brand": "VEICHI",
        "unit_price_ht": None,
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 90,
    },
    {
        "rule_key": "structure-400",
        "rule_type": "structure_pricing",
        "title": "Panneau 400 W",
        "panel_power_w": 400,
        "unit_price_ht": 480,
        "unit_label": "DH / panneau",
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 10,
    },
    {
        "rule_key": "structure-590",
        "rule_type": "structure_pricing",
        "title": "Panneau 590 W",
        "panel_power_w": 590,
        "unit_price_ht": 480,
        "unit_label": "DH / panneau",
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 20,
    },
    {
        "rule_key": "structure-715",
        "rule_type": "structure_pricing",
        "title": "Panneau 715 W",
        "panel_power_w": 715,
        "unit_price_ht": 580,
        "unit_label": "DH / panneau",
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 30,
    },
    {
        "rule_key": "coffret-mono-small",
        "rule_type": "coffret_pricing",
        "title": "Monophasé 2 à 3 CV",
        "min_cv": 2,
        "max_cv": 3,
        "phase": "monophase",
        "unit_price_ht": 2000,
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "visible": False,
        "sort_order": 10,
    },
    {
        "rule_key": "coffret-tri-medium",
        "rule_type": "coffret_pricing",
        "title": "Triphasé jusqu’à 30 CV",
        "min_cv": 5.5,
        "max_cv": 30,
        "phase": "triphase",
        "unit_price_ht": 3000,
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 20,
    },
    {
        "rule_key": "coffret-tri-large",
        "rule_type": "coffret_pricing",
        "title": "Triphasé au-delà de 30 CV",
        "min_cv": 40,
        "max_cv": 50,
        "phase": "triphase",
        "unit_price_ht": 4500,
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 30,
    },
    {
        "rule_key": "cabling-per-panel",
        "rule_type": "cabling_pricing",
        "title": "Câblage DC et accessoires",
        "unit_price_ht": 200,
        "unit_label": "DH / panneau",
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 10,
    },
    {
        "rule_key": "installation-small-forfait",
        "rule_type": "installation_pricing",
        "title": "Forfait petites installations",
        "min_cv": 2,
        "max_cv": 3,
        "pricing_mode": "fixed",
        "unit_price_ht": 3000,
        "unit_label": "DH HT",
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 10,
    },
    {
        "rule_key": "installation-standard-per-panel",
        "rule_type": "installation_pricing",
        "title": "Tarif standard",
        "min_cv": 5.5,
        "max_cv": 50,
        "pricing_mode": "per_panel",
        "unit_price_ht": 300,
        "unit_label": "DH / panneau",
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 20,
    },
    {
        "rule_key": "vat-panels",
        "rule_type": "vat_pricing",
        "title": "Panneaux photovoltaïques",
        "applies_to": "panels",
        "vat_rate": 0.10,
        "unit_label": "%",
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 10,
    },
    {
        "rule_key": "vat-others",
        "rule_type": "vat_pricing",
        "title": "Autres éléments",
        "applies_to": "others",
        "vat_rate": 0.20,
        "unit_label": "%",
        "source_type": "heliantha",
        "source_name": "HeliAntha",
        "active": 1,
        "sort_order": 20,
    },
]


PUMPING_RULE_SECTIONS = [
    {
        "key": "pump_configuration",
        "title": "Puissance de pompe → Configuration solaire",
        "description": "Associe la pompe déjà installée à la configuration solaire retenue.",
        "icon": "💧",
        "fields": [
            {"key": "pump_cv", "label": "Pompe", "unit": "CV", "kind": "number", "step": "0.1"},
            {"key": "panel_count", "label": "Panneaux", "unit": "unités", "kind": "number", "step": "1"},
            {"key": "panel_power_w", "label": "Puissance panneau", "unit": "W", "kind": "number", "step": "1"},
            {"key": "drive_power_kw", "label": "Variateur", "unit": "kW", "kind": "number", "step": "0.1"},
            {"key": "phase", "label": "Phase", "kind": "select", "options": [("monophase", "Monophasé"), ("triphase", "Triphasé")]},
            {"key": "drive_brand", "label": "Marque", "kind": "text"},
        ],
        "editable": True,
        "addable": True,
        "default_row": {"rule_type": "pump_configuration", "source_type": "heliantha", "source_name": "HeliAntha", "active": 1},
    },
    {
        "key": "drive_pricing",
        "title": "Variateurs",
        "description": "Prix utilisé pour le variateur de pompage si aucune fiche catalogue exacte n’est disponible.",
        "icon": "⚙️",
        "fields": [
            {"key": "drive_power_kw", "label": "Puissance", "unit": "kW", "kind": "number", "step": "0.1"},
            {"key": "phase", "label": "Phase", "kind": "select", "options": [("monophase", "Monophasé"), ("triphase", "Triphasé")]},
            {"key": "drive_brand", "label": "Marque", "kind": "text"},
            {"key": "unit_price_ht", "label": "Prix HT", "unit": "DH", "kind": "number", "step": "1"},
            {"key": "drive_reference", "label": "Réf. variateur", "kind": "text"},
        ],
        "editable": True,
        "addable": False,
        "visible": False,
    },
    {
        "key": "structure_pricing",
        "title": "Structures photovoltaïques",
        "description": "Tarif appliqué à la structure de support selon la puissance du panneau.",
        "icon": "🧱",
        "fields": [
            {"key": "panel_power_w", "label": "Puissance panneau", "unit": "W", "kind": "number", "step": "1"},
            {"key": "unit_price_ht", "label": "Prix HT / panneau", "unit": "DH", "kind": "number", "step": "1"},
        ],
        "editable": True,
        "addable": False,
    },
    {
        "key": "coffret_pricing",
        "title": "Coffrets de protection",
        "description": "Montant appliqué au coffret de protection selon la puissance de pompe.",
        "icon": "🛡️",
        "fields": [
            {"key": "min_cv", "label": "CV minimum", "unit": "CV", "kind": "number", "step": "0.1"},
            {"key": "max_cv", "label": "CV maximum", "unit": "CV", "kind": "number", "step": "0.1"},
            {"key": "phase", "label": "Phase", "kind": "select", "options": [("monophase", "Monophasé"), ("triphase", "Triphasé")]},
            {"key": "unit_price_ht", "label": "Prix HT", "unit": "DH", "kind": "number", "step": "1"},
        ],
        "editable": True,
        "addable": False,
    },
    {
        "key": "cabling_pricing",
        "title": "Câblage DC et accessoires",
        "description": "Tarif utilisé par panneau pour le câblage et les accessoires.",
        "icon": "🔌",
        "fields": [
            {"key": "unit_price_ht", "label": "Prix HT / panneau", "unit": "DH", "kind": "number", "step": "1"},
        ],
        "editable": True,
        "addable": False,
    },
    {
        "key": "installation_pricing",
        "title": "Installation et mise en service",
        "description": "Forfait ou tarif unitaire utilisé pour l’installation du pompage solaire.",
        "icon": "🛠️",
        "fields": [
            {"key": "min_cv", "label": "CV minimum", "unit": "CV", "kind": "number", "step": "0.1"},
            {"key": "max_cv", "label": "CV maximum", "unit": "CV", "kind": "number", "step": "0.1"},
            {"key": "pricing_mode", "label": "Mode", "kind": "select", "options": [("fixed", "Forfait"), ("per_panel", "Par panneau")]},
            {"key": "unit_price_ht", "label": "Prix HT", "unit": "DH", "kind": "number", "step": "1"},
        ],
        "editable": True,
        "addable": False,
    },
    {
        "key": "vat_pricing",
        "title": "TVA Pompage solaire",
        "description": "TVA utilisée pour les panneaux et les autres postes du pompage.",
        "icon": "🧾",
        "fields": [
            {"key": "applies_to", "label": "Appliquée à", "kind": "select", "options": [("panels", "Panneaux"), ("others", "Autres éléments")]},
            {"key": "vat_rate", "label": "TVA", "unit": "%", "kind": "number", "step": "0.01"},
        ],
        "editable": True,
        "addable": False,
    },
]


def normalize_pump_cv(value: object) -> float:
    try:
        number = float(str(value).replace(",", "."))
    except Exception:
        return 0.0
    if number <= 0:
        return 0.0
    return round(number, 2)


def format_decimal(value: object, digits: int = 0) -> str:
    try:
        number = float(value)
    except Exception:
        return "—"
    text = f"{number:,.{digits}f}"
    return text.replace(",", " ").replace(".", ",")


def format_cv(value: object) -> str:
    text = format_decimal(value, 1)
    return f"{text} CV".replace(",0 CV", " CV")


def format_power_w(value: object) -> str:
    return f"{format_decimal(value, 0)} W"


def format_power_kw(value: object) -> str:
    return f"{format_decimal(value, 1)} kW"


def format_percent(value: object) -> str:
    try:
        number = float(value)
    except Exception:
        return "—"
    if number <= 1:
        number *= 100
    return f"{format_decimal(number, 0)} %"


def format_price(value: object | None) -> str:
    if value in (None, ""):
        return "À compléter"
    try:
        number = float(value)
    except Exception:
        return "À compléter"
    return f"{format_decimal(number, 0)} DH"


def format_phase(value: object) -> str:
    return {
        "monophase": "Monophasé",
        "triphase": "Triphasé",
    }.get(str(value or ""), "À préciser")


def format_pricing_mode(value: object) -> str:
    return {
        "fixed": "Forfait",
        "per_panel": "Par panneau",
    }.get(str(value or ""), "À préciser")


def format_applies_to(value: object) -> str:
    return {
        "panels": "Panneaux",
        "others": "Autres éléments",
    }.get(str(value or ""), "À préciser")


def parse_number(value: object, default: float | None = None) -> float | None:
    text = str(value).strip()
    if not text:
        return default
    try:
        return float(text.replace(",", "."))
    except Exception:
        return default


def parse_int(value: object, default: int | None = None) -> int | None:
    number = parse_number(value, None)
    if number is None:
        return default
    return int(number)


def _rule_value_for_summary(rule: dict[str, object], key: str) -> str:
    if key == "pump_cv":
        return format_cv(rule.get(key))
    if key == "panel_count":
        return f"{format_decimal(rule.get(key), 0)} panneaux"
    if key == "panel_power_w":
        return format_power_w(rule.get(key))
    if key == "drive_power_kw":
        return format_power_kw(rule.get(key))
    if key == "min_cv" or key == "max_cv":
        return format_cv(rule.get(key))
    if key == "unit_price_ht":
        return format_price(rule.get(key))
    if key == "vat_rate":
        return format_percent(rule.get(key))
    if key == "phase":
        return format_phase(rule.get(key))
    if key == "pricing_mode":
        return format_pricing_mode(rule.get(key))
    if key == "applies_to":
        return format_applies_to(rule.get(key))
    return str(rule.get(key) or "—")


def summarize_rule(rule: dict[str, object]) -> str:
    rule_type = str(rule.get("rule_type") or "")
    if rule_type == "pump_configuration":
        return " · ".join(
            [
                format_cv(rule.get("pump_cv")),
                f"{format_decimal(rule.get('panel_count'), 0)} panneaux",
                format_power_w(rule.get("panel_power_w")),
                format_power_kw(rule.get("drive_power_kw")),
                format_phase(rule.get("phase")),
                str(rule.get("drive_brand") or "—"),
            ]
        )
    if rule_type == "drive_pricing":
        return " · ".join(
            [
                format_power_kw(rule.get("drive_power_kw")),
                format_phase(rule.get("phase")),
                str(rule.get("drive_brand") or "—"),
                format_price(rule.get("unit_price_ht")),
            ]
        )
    if rule_type == "structure_pricing":
        return " · ".join([format_power_w(rule.get("panel_power_w")), format_price(rule.get("unit_price_ht")), "par panneau"])
    if rule_type == "coffret_pricing":
        cv_range = f"{format_cv(rule.get('min_cv'))} → {format_cv(rule.get('max_cv'))}"
        return " · ".join([cv_range, format_phase(rule.get("phase")), format_price(rule.get("unit_price_ht"))])
    if rule_type == "cabling_pricing":
        return " · ".join([format_price(rule.get("unit_price_ht")), "par panneau"])
    if rule_type == "installation_pricing":
        cv_range = f"{format_cv(rule.get('min_cv'))} → {format_cv(rule.get('max_cv'))}"
        return " · ".join([cv_range, format_pricing_mode(rule.get("pricing_mode")), format_price(rule.get("unit_price_ht"))])
    if rule_type == "vat_pricing":
        return " · ".join([format_applies_to(rule.get("applies_to")), format_percent(rule.get("vat_rate"))])
    return "Règle HeliAntha"


def decorate_rule(rule: dict[str, object]) -> dict[str, object]:
    item = deepcopy(rule)
    item["summary"] = summarize_rule(item)
    item["source_label"] = "HeliAntha"
    item["source_badge"] = "✅ HeliAntha"
    item["price_status"] = "complete" if item.get("unit_price_ht") not in (None, "") else "missing"
    item["display_active"] = "Actif" if int(item.get("active", 1) or 0) == 1 else "Inactif"
    item["display_pump_cv"] = format_cv(item.get("pump_cv"))
    item["display_panel_count"] = f"{format_decimal(item.get('panel_count'), 0)}"
    item["display_panel_power_w"] = format_power_w(item.get("panel_power_w"))
    item["display_drive_power_kw"] = format_power_kw(item.get("drive_power_kw"))
    item["display_phase"] = format_phase(item.get("phase"))
    item["display_drive_brand"] = str(item.get("drive_brand") or "—")
    item["display_min_cv"] = format_cv(item.get("min_cv"))
    item["display_max_cv"] = format_cv(item.get("max_cv"))
    item["display_unit_price_ht"] = format_price(item.get("unit_price_ht"))
    item["display_pricing_mode"] = format_pricing_mode(item.get("pricing_mode"))
    item["display_applies_to"] = format_applies_to(item.get("applies_to"))
    item["display_vat_rate"] = format_percent(item.get("vat_rate"))
    return item


def group_rules(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {section["key"]: [] for section in PUMPING_RULE_SECTIONS}
    for row in rows:
        grouped.setdefault(str(row.get("rule_type") or ""), []).append(decorate_rule(row))

    grouped_sections = []
    for section in PUMPING_RULE_SECTIONS:
        if not section.get("visible", True):
            continue
        items = sorted(grouped.get(section["key"], []), key=lambda item: (int(item.get("sort_order") or 0), str(item.get("title") or item.get("rule_key") or "")))
        section_copy = deepcopy(section)
        section_copy["rules"] = items
        grouped_sections.append(section_copy)
    return grouped_sections


def rule_matches(rule: dict[str, object], **criteria: object) -> bool:
    for key, expected in criteria.items():
        if expected in (None, ""):
            continue
        value = rule.get(key)
        if key in {"pump_cv", "panel_power_w", "drive_power_kw", "unit_price_ht", "vat_rate", "min_cv", "max_cv"}:
            try:
                if abs(float(value or 0) - float(expected)) > 0.05:
                    return False
            except Exception:
                return False
        else:
            if str(value or "").strip().lower() != str(expected).strip().lower():
                return False
    return True


def find_rule(rows: list[dict[str, object]], rule_type: str, **criteria: object) -> dict[str, object] | None:
    candidates = [
        row
        for row in rows
        if int(row.get("active", 1) or 0) == 1 and str(row.get("rule_type") or "") == rule_type and rule_matches(row, **criteria)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda row: (int(row.get("sort_order") or 0), str(row.get("title") or row.get("rule_key") or "")))[0]
