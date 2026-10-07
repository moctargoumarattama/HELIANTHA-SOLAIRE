import time

_CALC_CACHE = None
_CALC_CACHE_VERSION = None
_CALC_CACHE_TIME = 0.0

def _get_redis_client():
    try:
        import redis
        client = redis.Redis(host="127.0.0.1", port=6379, db=0, socket_timeout=0.2)
        client.ping()
        return client
    except Exception:
        return None

def invalidate_calculation_context():
    """Vide le cache RAM local et synchronise via Redis."""
    global _CALC_CACHE, _CALC_CACHE_VERSION, _CALC_CACHE_TIME
    _CALC_CACHE = None
    _CALC_CACHE_VERSION = None
    _CALC_CACHE_TIME = 0.0
    r = _get_redis_client()
    if r:
        try:
            r.incr("heliantha:calc_context_version")
        except Exception:
            pass

def _get_redis_version():
    r = _get_redis_client()
    if r:
        try:
            val = r.get("heliantha:calc_context_version")
            if val is None:
                r.set("heliantha:calc_context_version", 1)
                return 1
            return int(val)
        except Exception:
            return None
    return None

import json
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from flask import current_app, g
from werkzeug.security import check_password_hash, generate_password_hash

from .catalog import ProductValidationError, product_completeness, validate_product
from .defaults import (
    CALCULATION_PARAMETERS,
    DASHBOARD_PROJECT_LABELS,
    CATALOG_PRODUCTS,
    COMPANY_SETTINGS,
    ONGRID_PARAMETER_DEFAULTS,
    PARAMETER_CLASSIFICATION,
    PARAMETER_PRESENTATION,
    PRICING_RULES,
    PUBLIC_PROJECTS,
    QUOTE_STATUSES,
    TECHNICAL_REFERENCE,
)
from .pumping_rules import PUMPING_SOLAR_RULE_DEFAULTS
from .tax import VAT_FIELDS, TaxValidationError, get_vat_rates, parse_vat_percentage


SCHEMA = """
CREATE TABLE IF NOT EXISTS quote_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_number TEXT NOT NULL UNIQUE,
    project TEXT NOT NULL,
    customer_name TEXT,
    phone TEXT,
    email TEXT,
    location TEXT,
    request_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Nouveau',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reference TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    subcategory TEXT,
    brand TEXT,
    model TEXT,
    description TEXT,
    power_kw REAL,
    power_w REAL,
    voltage REAL,
    current_amp REAL,
    capacity_kwh REAL,
    capacity_l REAL,
    efficiency REAL,
    technology TEXT,
    technical_specs_json TEXT,
    purchase_price REAL,
    sale_price REAL,
    supplier TEXT,
    stock REAL,
    unit TEXT,
    warranty TEXT,
    vat_rate REAL,
    currency TEXT NOT NULL DEFAULT 'DH',
    datasheet_url TEXT,
    demo INTEGER NOT NULL DEFAULT 0,
    preferred INTEGER NOT NULL DEFAULT 0,
    priority INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pump_curve_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pump_id INTEGER NOT NULL,
    flow_m3_h REAL NOT NULL,
    hmt_m REAL NOT NULL,
    FOREIGN KEY (pump_id) REFERENCES products(id) ON DELETE CASCADE,
    UNIQUE (pump_id, flow_m3_h)
);

CREATE TABLE IF NOT EXISTS calculation_parameters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT,
    category TEXT,
    description TEXT,
    display_name TEXT,
    display_kind TEXT,
    plain_explanation TEXT,
    used_for TEXT,
    example TEXT,
    source_type TEXT NOT NULL DEFAULT 'demo',
    source_name TEXT,
    source_reference TEXT,
    validated_by TEXT,
    validated_at TEXT,
    editable INTEGER NOT NULL DEFAULT 1,
    calculator_usage TEXT,
    admin_visible INTEGER NOT NULL DEFAULT 1,
    management_scope TEXT NOT NULL DEFAULT 'business_rule',
    role_label TEXT,
    role_description TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS calculation_parameter_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parameter_id INTEGER NOT NULL,
    parameter_key TEXT NOT NULL,
    old_value REAL NOT NULL,
    new_value REAL NOT NULL,
    changed_by TEXT,
    source_type TEXT,
    source_name TEXT,
    source_reference TEXT,
    change_comment TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (parameter_id) REFERENCES calculation_parameters(id)
);

CREATE TABLE IF NOT EXISTS pricing_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    value REAL NOT NULL,
    value_type TEXT NOT NULL,
    unit TEXT,
    project TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pumping_solar_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_key TEXT NOT NULL UNIQUE,
    rule_type TEXT NOT NULL,
    title TEXT NOT NULL,
    pump_cv REAL,
    panel_count REAL,
    panel_power_w REAL,
    panel_reference TEXT,
    panel_sale_price_ht REAL,
    drive_power_kw REAL,
    drive_reference TEXT,
    drive_sale_price_ht REAL,
    drive_brand TEXT,
    phase TEXT,
    min_cv REAL,
    max_cv REAL,
    pricing_mode TEXT,
    unit_price_ht REAL,
    coefficient_1 REAL,
    coefficient_2 REAL,
    vat_rate REAL,
    applies_to TEXT,
    source_type TEXT NOT NULL DEFAULT 'heliantha',
    source_name TEXT,
    source_reference TEXT,
    notes TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    updated_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ongrid_parameters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    value TEXT NOT NULL,
    unit TEXT,
    description TEXT,
    updated_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS vat_rates (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_by TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS technical_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    description TEXT,
    effective_date TEXT,
    status TEXT NOT NULL DEFAULT 'Actif',
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    password_hash TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS company_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value TEXT,
    category TEXT,
    label TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS quote_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_id INTEGER NOT NULL,
    old_status TEXT,
    new_status TEXT NOT NULL,
    changed_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (quote_id) REFERENCES quote_requests(id)
);

CREATE TABLE IF NOT EXISTS visit_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_id INTEGER NOT NULL,
    quote_number TEXT NOT NULL,
    preferred_date TEXT,
    time_slot TEXT,
    address TEXT,
    phone TEXT,
    comment TEXT,
    status TEXT NOT NULL DEFAULT 'Nouveau',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (quote_id) REFERENCES quote_requests(id)
);

CREATE TABLE IF NOT EXISTS quote_client_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_id INTEGER NOT NULL,
    quote_number TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_value TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (quote_id) REFERENCES quote_requests(id)
);

CREATE TABLE IF NOT EXISTS whatsapp_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT,
    msg_type TEXT NOT NULL,
    pdf_url TEXT,
    filename TEXT,
    caption TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING',
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sent_at TEXT,
    error_message TEXT
);

"""

QUOTE_COLUMNS = {
    "company": "TEXT",
    "city": "TEXT",
    "solution_name": "TEXT",
    "amount_ht": "REAL",
    "amount_ttc": "REAL",
    "confidence": "INTEGER",
    "reliability_json": "TEXT",
    "calculation_detail_json": "TEXT",
    "financial_breakdown_json": "TEXT",
    "selected_equipment_json": "TEXT",
    "calculator_versions_json": "TEXT",
    "technical_parameters_json": "TEXT",
    "quote_snapshot_json": "TEXT",
    "technical_reference_json": "TEXT",
    "bom_json": "TEXT",
    "technical_configuration_json": "TEXT",
    "compatibility_json": "TEXT",
    "product_selections_json": "TEXT",
    "selected_offer_level": "TEXT",
    "updated_at": "TEXT",
}

PRODUCT_COLUMNS = {
    "vat_rate": "REAL",
    "currency": "TEXT NOT NULL DEFAULT 'DH'",
    "datasheet_url": "TEXT",
    "demo": "INTEGER NOT NULL DEFAULT 0",
    "preferred": "INTEGER NOT NULL DEFAULT 0",
    "priority": "INTEGER NOT NULL DEFAULT 0",
}

CALCULATION_PARAMETER_COLUMNS = {
    "display_name": "TEXT",
    "display_kind": "TEXT",
    "plain_explanation": "TEXT",
    "used_for": "TEXT",
    "example": "TEXT",
    "source_type": "TEXT NOT NULL DEFAULT 'demo'",
    "source_name": "TEXT",
    "source_reference": "TEXT",
    "validated_by": "TEXT",
    "validated_at": "TEXT",
    "editable": "INTEGER NOT NULL DEFAULT 1",
    "calculator_usage": "TEXT",
    "admin_visible": "INTEGER NOT NULL DEFAULT 1",
    "management_scope": "TEXT NOT NULL DEFAULT 'business_rule'",
    "role_label": "TEXT",
    "role_description": "TEXT",
}

PUMPING_SOLAR_RULE_COLUMNS = {
    "rule_type": "TEXT NOT NULL",
    "title": "TEXT NOT NULL",
    "pump_cv": "REAL",
    "panel_count": "REAL",
    "panel_power_w": "REAL",
    "panel_reference": "TEXT",
    "panel_sale_price_ht": "REAL",
    "drive_power_kw": "REAL",
    "drive_reference": "TEXT",
    "drive_sale_price_ht": "REAL",
    "drive_brand": "TEXT",
    "phase": "TEXT",
    "min_cv": "REAL",
    "max_cv": "REAL",
    "pricing_mode": "TEXT",
    "unit_price_ht": "REAL",
    "coefficient_1": "REAL",
    "coefficient_2": "REAL",
    "vat_rate": "REAL",
    "applies_to": "TEXT",
    "source_type": "TEXT NOT NULL DEFAULT 'heliantha'",
    "source_name": "TEXT",
    "source_reference": "TEXT",
    "notes": "TEXT",
    "sort_order": "INTEGER NOT NULL DEFAULT 0",
    "active": "INTEGER NOT NULL DEFAULT 1",
    "updated_by": "TEXT",
}

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    ensure_schema(db)


def ensure_schema(db=None):
    """Apply idempotent migrations without deleting or rebuilding data."""
    db = db or get_db()
    db.executescript(SCHEMA)
    _migrate_quote_requests(db)
    _migrate_products(db)
    _migrate_pump_curve_points(db)
    _migrate_calculation_parameters(db)
    _migrate_pumping_solar_rules(db)
    _migrate_public_tracking(db)
    _migrate_users(db)
    _seed_defaults(db)
    _seed_vat_rates(db)
    db.commit()


def _migrate_quote_requests(db):
    existing = {row["name"] for row in db.execute("PRAGMA table_info(quote_requests)").fetchall()}
    for column, column_type in QUOTE_COLUMNS.items():
        if column not in existing:
            db.execute(f"ALTER TABLE quote_requests ADD COLUMN {column} {column_type}")


def _migrate_products(db):
    existing = {row["name"] for row in db.execute("PRAGMA table_info(products)").fetchall()}
    for column, column_type in PRODUCT_COLUMNS.items():
        if column not in existing:
            db.execute(f"ALTER TABLE products ADD COLUMN {column} {column_type}")
    db.execute(
        """CREATE INDEX IF NOT EXISTS idx_products_catalog_lookup
        ON products(active, category, brand, stock, priority)"""
    )


def _migrate_pump_curve_points(db):
    db.execute(
        """CREATE INDEX IF NOT EXISTS idx_pump_curve_points_lookup
        ON pump_curve_points(pump_id, flow_m3_h)"""
    )


def _migrate_calculation_parameters(db):
    existing = {row["name"] for row in db.execute("PRAGMA table_info(calculation_parameters)").fetchall()}
    for column, column_type in CALCULATION_PARAMETER_COLUMNS.items():
        if column not in existing:
            db.execute(f"ALTER TABLE calculation_parameters ADD COLUMN {column} {column_type}")


def _migrate_pumping_solar_rules(db):
    existing = {row["name"] for row in db.execute("PRAGMA table_info(pumping_solar_rules)").fetchall()}
    for column, column_type in PUMPING_SOLAR_RULE_COLUMNS.items():
        if column not in existing:
            db.execute(f"ALTER TABLE pumping_solar_rules ADD COLUMN {column} {column_type}")
    db.execute(
        """CREATE INDEX IF NOT EXISTS idx_pumping_solar_rules_lookup
        ON pumping_solar_rules(active, rule_type, pump_cv, panel_power_w, drive_power_kw, phase, sort_order)"""
    )


def _migrate_public_tracking(db):
    db.execute(
        """CREATE INDEX IF NOT EXISTS idx_visit_requests_quote
        ON visit_requests(quote_id, created_at DESC)"""
    )
    db.execute(
        """CREATE INDEX IF NOT EXISTS idx_quote_client_events_quote
        ON quote_client_events(quote_id, created_at DESC)"""
    )
    db.execute(
        """CREATE INDEX IF NOT EXISTS idx_whatsapp_outbox_status
        ON whatsapp_outbox(status, created_at, id)"""
    )


def _migrate_users(db):
    existing = {row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()}
    if "password_hash" not in existing:
        db.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")

    direction_user = db.execute(
        """SELECT id FROM users
        WHERE username = 'direction@heliantha.ma' OR role = 'Direction'
        ORDER BY CASE WHEN username = 'direction@heliantha.ma' THEN 0 ELSE 1 END, id ASC
        LIMIT 1"""
    ).fetchone()
    if direction_user:
        db.execute(
            """UPDATE users
            SET username = COALESCE(NULLIF(username, ''), 'direction@heliantha.ma'),
                display_name = COALESCE(NULLIF(display_name, ''), 'Direction HeliAntha'),
                role = 'Direction',
                password_hash = COALESCE(NULLIF(password_hash, ''), ?)
            WHERE id = ?""",
            (generate_password_hash(current_app.config.get("ADMIN_PASSWORD", "heliantha2026")), direction_user["id"]),
        )


def _seed_defaults(db):
    for key, name, value, unit, category, description in CALCULATION_PARAMETERS:
        meta = PARAMETER_PRESENTATION.get(key, {})
        classification = PARAMETER_CLASSIFICATION.get(key, {})
        db.execute(
            """INSERT OR IGNORE INTO calculation_parameters
            (key, name, value, unit, category, description, display_name, display_kind,
             plain_explanation, used_for, example, source_type, source_name, source_reference,
             validated_by, validated_at, editable, calculator_usage, admin_visible,
             management_scope, role_label, role_description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                key,
                name,
                value,
                unit,
                category,
                description,
                meta.get("display_name", name),
                meta.get("display_kind", unit),
                meta.get("plain_explanation", description),
                meta.get("used_for", ""),
                meta.get("example", ""),
                meta.get("source_type", "demo"),
                meta.get("source_name", ""),
                meta.get("source_reference", ""),
                meta.get("validated_by", ""),
                meta.get("validated_at", ""),
                1 if meta.get("editable", True) else 0,
                meta.get("calculator_usage", ""),
                1 if classification.get("admin_visible", True) else 0,
                classification.get("management_scope", "business_rule"),
                classification.get("role_label", ""),
                classification.get("role_description", ""),
            ),
        )
        db.execute(
            """UPDATE calculation_parameters SET
            display_name = COALESCE(NULLIF(display_name, ''), ?),
            display_kind = COALESCE(NULLIF(display_kind, ''), ?),
            plain_explanation = COALESCE(NULLIF(plain_explanation, ''), ?),
            used_for = COALESCE(NULLIF(used_for, ''), ?),
            example = COALESCE(NULLIF(example, ''), ?),
            source_type = COALESCE(NULLIF(source_type, ''), ?),
            source_name = COALESCE(NULLIF(source_name, ''), ?),
            source_reference = COALESCE(NULLIF(source_reference, ''), ?),
            validated_by = COALESCE(NULLIF(validated_by, ''), ?),
            validated_at = COALESCE(NULLIF(validated_at, ''), ?),
            calculator_usage = COALESCE(NULLIF(calculator_usage, ''), ?),
            role_label = COALESCE(NULLIF(role_label, ''), ?),
            role_description = COALESCE(NULLIF(role_description, ''), ?),
            management_scope = COALESCE(NULLIF(management_scope, ''), ?),
            admin_visible = ?,
            editable = ?
            WHERE key = ?""",
            (
                meta.get("display_name", name),
                meta.get("display_kind", unit),
                meta.get("plain_explanation", description),
                meta.get("used_for", ""),
                meta.get("example", ""),
                meta.get("source_type", "demo"),
                meta.get("source_name", ""),
                meta.get("source_reference", ""),
                meta.get("validated_by", ""),
                meta.get("validated_at", ""),
                meta.get("calculator_usage", ""),
                classification.get("role_label", ""),
                classification.get("role_description", ""),
                classification.get("management_scope", "business_rule"),
                1 if classification.get("admin_visible", True) else 0,
                1 if meta.get("editable", True) else 0,
                key,
            ),
        )
        if meta.get("source_type") and meta.get("source_type") != "demo":
            db.execute(
                """UPDATE calculation_parameters SET source_type = ?, source_name = ?,
                source_reference = ?, editable = ?
                WHERE key = ? AND (source_type IS NULL OR source_type = '' OR source_type = 'demo')""",
                (
                    meta.get("source_type"),
                    meta.get("source_name", ""),
                    meta.get("source_reference", ""),
                    1 if meta.get("editable", True) else 0,
                    key,
                ),
            )

    for key, name, value, value_type, unit, project in PRICING_RULES:
        db.execute(
            """INSERT OR IGNORE INTO pricing_rules
            (key, name, value, value_type, unit, project)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (key, name, value, value_type, unit, project),
        )
    db.execute(
        "DELETE FROM pricing_rules WHERE key IN ('travel_fixed', 'travel_cost_per_km', 'margin_rate', 'study_fee', 'other_costs')"
    )
    db.execute(
        "DELETE FROM calculation_parameters WHERE key IN ('pump_efficiency', 'pump_drive_efficiency', 'pump_hydraulic_losses_rate', 'pump_safety_factor')"
    )

    for rule in PUMPING_SOLAR_RULE_DEFAULTS:
        db.execute(
            """INSERT OR IGNORE INTO pumping_solar_rules
            (rule_key, rule_type, title, pump_cv, panel_count, panel_power_w,
             panel_reference, panel_sale_price_ht, drive_power_kw, drive_reference,
             drive_sale_price_ht, drive_brand, phase, min_cv, max_cv, pricing_mode,
             unit_price_ht, coefficient_1, coefficient_2, vat_rate, applies_to, source_type, source_name,
             source_reference, notes, sort_order, active, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rule.get("rule_key"),
                rule.get("rule_type"),
                rule.get("title"),
                rule.get("pump_cv"),
                rule.get("panel_count"),
                rule.get("panel_power_w"),
                rule.get("panel_reference"),
                rule.get("panel_sale_price_ht"),
                rule.get("drive_power_kw"),
                rule.get("drive_reference"),
                rule.get("drive_sale_price_ht"),
                rule.get("drive_brand"),
                rule.get("phase"),
                rule.get("min_cv"),
                rule.get("max_cv"),
                rule.get("pricing_mode"),
                rule.get("unit_price_ht"),
                rule.get("coefficient_1"),
                rule.get("coefficient_2"),
                rule.get("vat_rate"),
                rule.get("applies_to"),
                rule.get("source_type", "heliantha"),
                rule.get("source_name", "HeliAntha"),
                rule.get("source_reference", ""),
                rule.get("notes", ""),
                rule.get("sort_order", 0),
                1 if rule.get("active", 1) else 0,
                rule.get("updated_by", "HeliAntha"),
            ),
        )

    if not db.execute("SELECT id FROM ongrid_parameters LIMIT 1").fetchone():
        db.executemany(
            """INSERT INTO ongrid_parameters
            (key, label, value, unit, description, updated_by)
            VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (key, label, f"{value:.2f}", unit, description, "HeliAntha")
                for key, label, value, unit, description in ONGRID_PARAMETER_DEFAULTS
            ],
        )

    db.execute(
        """UPDATE pumping_solar_rules
        SET coefficient_1 = COALESCE(coefficient_1, 0.5),
            coefficient_2 = COALESCE(coefficient_2, 1.3),
            vat_rate = COALESCE(vat_rate, 0.20)
        WHERE rule_key = 'pump-sale-parameters'"""
    )

    db.execute(
        """UPDATE pumping_solar_rules
        SET min_cv = 2, max_cv = 3, title = 'Monophasé 2 à 3 CV'
        WHERE rule_key = 'coffret-mono-small' AND (min_cv IS NULL OR min_cv < 2 OR max_cv <> 3 OR title <> 'Monophasé 2 à 3 CV')"""
    )

    db.execute(
        """UPDATE pumping_solar_rules
        SET panel_count = 6,
            phase = 'monophase',
            drive_power_kw = 2.2,
            drive_brand = COALESCE(NULLIF(drive_brand, ''), 'INVT')
        WHERE rule_key = 'pump-2cv'"""
    )

    db.execute(
        """UPDATE pumping_solar_rules
        SET panel_count = 12,
            phase = 'triphase',
            drive_power_kw = 2.2,
            drive_brand = COALESCE(NULLIF(drive_brand, ''), 'INVT')
        WHERE rule_key = 'pump-3cv'"""
    )

    for product in CATALOG_PRODUCTS:
        inserted = db.execute(
            """INSERT OR IGNORE INTO products
            (reference, category, subcategory, brand, model, description, power_kw, power_w,
             voltage, current_amp, capacity_kwh, capacity_l, efficiency, technology,
             technical_specs_json, purchase_price, sale_price, supplier, stock, unit, warranty,
             vat_rate, currency, datasheet_url, demo, preferred, priority)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                product.get("reference"),
                product.get("category"),
                product.get("subcategory"),
                product.get("brand"),
                product.get("model"),
                product.get("description"),
                product.get("power_kw"),
                product.get("power_w"),
                product.get("voltage"),
                product.get("current_amp"),
                product.get("capacity_kwh"),
                product.get("capacity_l"),
                product.get("efficiency"),
                product.get("technology"),
                dumps(product.get("technical_specs") or {}),
                product.get("purchase_price"),
                product.get("sale_price"),
                product.get("supplier"),
                product.get("stock", 0),
                product.get("unit", "piece"),
                product.get("warranty"),
                product.get("vat_rate", 0.20),
                product.get("currency", "DH"),
                product.get("datasheet_url", ""),
                1 if product.get("demo", True) else 0,
                1 if product.get("preferred") else 0,
                int(product.get("priority", 0) or 0),
            ),
        )
        if inserted.rowcount == 1 and product.get("category") == "pumps":
            pump_id = inserted.lastrowid
            points = product.get("pump_curve_points") or []
            db.executemany(
                """INSERT INTO pump_curve_points (pump_id, flow_m3_h, hmt_m)
                VALUES (?, ?, ?)""",
                [
                    (pump_id, point.get("flow_m3_h"), point.get("hmt_m"))
                    for point in points
                ],
            )
        # References in CATALOG_PRODUCTS are the stable identity of the bundled
        # catalogue.  Only the provenance flag is backfilled;
        # prices, stock and any edits made by HeliAntha are never overwritten.
        db.execute(
            """UPDATE products SET demo = ?,
            vat_rate = COALESCE(vat_rate, ?),
            currency = COALESCE(NULLIF(currency, ''), ?)
            WHERE reference = ?""",
            (
                1 if product.get("demo", True) else 0,
                product.get("vat_rate", 0.20),
                product.get("currency", "DH"),
                product.get("reference"),
            ),
        )

    _seed_missing_default_pump_curves(db)
    _seed_default_pump_metadata(db)

    if not db.execute("SELECT id FROM technical_references WHERE status = 'Actif' LIMIT 1").fetchone():
        db.execute(
            """INSERT INTO technical_references
            (name, version, description, effective_date, status, notes)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                TECHNICAL_REFERENCE["name"],
                TECHNICAL_REFERENCE["version"],
                TECHNICAL_REFERENCE["description"],
                TECHNICAL_REFERENCE["effective_date"],
                TECHNICAL_REFERENCE["status"],
                TECHNICAL_REFERENCE["notes"],
            ),
        )

    for key, value, category, label in COMPANY_SETTINGS:
        db.execute(
            """INSERT OR IGNORE INTO company_settings (key, value, category, label)
            VALUES (?, ?, ?, ?)""",
            (key, value, category, label),
        )

    direction_user = db.execute(
        """SELECT * FROM users
        WHERE username = 'direction@heliantha.ma' OR role = 'Direction'
        ORDER BY CASE WHEN username = 'direction@heliantha.ma' THEN 0 ELSE 1 END, id ASC
        LIMIT 1"""
    ).fetchone()
    legacy_admin_user = db.execute(
        "SELECT id FROM users WHERE username = 'admin' AND role = 'Administrateur'"
    ).fetchone()

    if legacy_admin_user and not direction_user:
        db.execute(
            """UPDATE users
            SET username = 'direction@heliantha.ma',
                display_name = 'Direction HeliAntha',
                role = 'Direction',
                password_hash = COALESCE(NULLIF(password_hash, ''), ?)
            WHERE id = ?""",
            (generate_password_hash(current_app.config.get("ADMIN_PASSWORD", "heliantha2026")), legacy_admin_user["id"]),
        )
    elif not direction_user:
        db.execute(
            """INSERT OR IGNORE INTO users (username, display_name, role, password_hash)
            VALUES ('direction@heliantha.ma', 'Direction HeliAntha', 'Direction', ?)""",
            (generate_password_hash(current_app.config.get("ADMIN_PASSWORD", "heliantha2026")),),
        )
    else:
        db.execute(
            """UPDATE users
            SET username = 'direction@heliantha.ma',
                display_name = 'Direction HeliAntha',
                role = 'Direction',
                password_hash = COALESCE(NULLIF(password_hash, ''), ?)
            WHERE id = ?""",
            (generate_password_hash(current_app.config.get("ADMIN_PASSWORD", "heliantha2026")), direction_user["id"]),
        )
        if legacy_admin_user and legacy_admin_user["id"] != direction_user["id"]:
            db.execute("DELETE FROM users WHERE id = ?", (legacy_admin_user["id"],))


def _seed_missing_default_pump_curves(db):
    for product in CATALOG_PRODUCTS:
        if product.get("category") != "pumps":
            continue
        points = product.get("pump_curve_points") or []
        if not points:
            continue
        row = db.execute(
            "SELECT id FROM products WHERE reference = ?",
            (product.get("reference"),),
        ).fetchone()
        if not row:
            continue
        pump_id = row["id"]
        existing_points = db.execute(
            "SELECT COUNT(1) FROM pump_curve_points WHERE pump_id = ?",
            (pump_id,),
        ).fetchone()[0]
        if existing_points:
            continue
        db.executemany(
            """INSERT INTO pump_curve_points (pump_id, flow_m3_h, hmt_m)
            VALUES (?, ?, ?)""",
            [
                (pump_id, point.get("flow_m3_h"), point.get("hmt_m"))
                for point in points
            ],
        )


def _seed_default_pump_metadata(db):
    """Backfill bundled pump technical metadata without touching admin prices."""

    for product in CATALOG_PRODUCTS:
        if product.get("category") != "pumps":
            continue
        default_specs = product.get("technical_specs") or {}
        outlet_diameter = default_specs.get("outlet_diameter")
        if not outlet_diameter:
            continue
        row = db.execute(
            "SELECT id, technical_specs_json FROM products WHERE reference = ?",
            (product.get("reference"),),
        ).fetchone()
        if not row:
            continue
        specs = loads(row["technical_specs_json"], {})
        if not isinstance(specs, dict):
            specs = {}
        changed = False
        if not specs.get("outlet_diameter"):
            specs["outlet_diameter"] = outlet_diameter
            changed = True
        if str(specs.get("price_tax_basis") or "").strip().lower() in {"", "unconfirmed"}:
            specs["price_tax_basis"] = default_specs.get("price_tax_basis") or "internal_pt"
            changed = True
        if changed:
            db.execute(
                "UPDATE products SET technical_specs_json = ?, updated_at = ? WHERE id = ?",
                (dumps(specs), utc_now(), row["id"]),
            )


def dumps(value):
    return json.dumps(value, ensure_ascii=False)


def loads(value, default=None):
    if value in (None, ""):
        return {} if default is None else default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {} if default is None else default


def utc_now():
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _seed_vat_rates(db):
    """Migrate legacy active rates once; subsequent initialization preserves all edits."""
    existing = {row["key"]: dict(row) for row in db.execute("SELECT * FROM vat_rates").fetchall()}
    if len(existing) == len(VAT_FIELDS) and all(field["key"] in existing for field in VAT_FIELDS):
        return
    context = {
        "vat_rates": existing,
        "ongrid_parameters": {
            row["key"]: dict(row) for row in db.execute("SELECT * FROM ongrid_parameters").fetchall()
        },
        "pumping_solar_rules": {
            row["rule_key"]: dict(row)
            for row in db.execute("SELECT * FROM pumping_solar_rules WHERE active = 1").fetchall()
        },
    }
    rates = get_vat_rates(context)
    db.executemany(
        "INSERT OR IGNORE INTO vat_rates (key, value, updated_by) VALUES (?, ?, ?)",
        [(field["key"], format(rates[field["key"]], "f"), "Migration TVA") for field in VAT_FIELDS],
    )


def _validate_vat_values(values):
    known = {field["key"] for field in VAT_FIELDS}
    parsed = {}
    errors = {}
    for key, raw in values.items():
        if key not in known:
            errors[key] = "Paramètre de TVA inconnu."
            continue
        try:
            parsed[key] = parse_vat_percentage(raw)
        except TaxValidationError as exc:
            errors[key] = str(exc)
    if errors:
        raise TaxValidationError(next(iter(errors.values())), errors=errors)
    return parsed


def _sync_legacy_vat_rates(db, changed_by):
    """Keep old administrative readers compatible; calculations use the central profiles."""
    rates = {row["key"]: parse_vat_percentage(row["value"]) for row in db.execute("SELECT * FROM vat_rates").fetchall()}
    timestamp = utc_now()
    for old_key, central_key in (
        ("vat_pv_rate", "residential_panels"),
        ("vat_standard_rate", "residential_equipment"),
        ("vat_transport_rate", "residential_transport"),
    ):
        db.execute(
            "UPDATE ongrid_parameters SET value = ?, updated_by = ?, updated_at = ? WHERE key = ?",
            (format(rates[central_key], "f"), changed_by, timestamp, old_key),
        )
    for applies_to, central_key in (
        ("panels", "pumping_panels"),
        ("others", "pumping_accessories"),
        ("transport", "pumping_transport"),
    ):
        db.execute(
            "UPDATE pumping_solar_rules SET vat_rate = ?, updated_by = ?, updated_at = ? "
            "WHERE rule_type = 'vat_pricing' AND applies_to = ?",
            (float(rates[central_key] / 100), changed_by, timestamp, applies_to),
        )
    db.execute(
        "UPDATE pumping_solar_rules SET vat_rate = ?, updated_by = ?, updated_at = ? WHERE rule_type = 'pump_sale_parameters'",
        (float(rates["pumping_equipment"] / 100), changed_by, timestamp),
    )


def _write_vat_rates(db, values, changed_by):
    timestamp = utc_now()
    db.executemany(
        "INSERT INTO vat_rates (key, value, updated_by, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_by = excluded.updated_by, updated_at = excluded.updated_at",
        [(key, format(value, "f"), changed_by, timestamp) for key, value in values.items()],
    )
    _sync_legacy_vat_rates(db, changed_by)


def list_vat_rates():
    db = get_db()
    ensure_schema(db)
    rows = {row["key"]: dict(row) for row in db.execute("SELECT * FROM vat_rates").fetchall()}
    return [dict(rows[field["key"]], label=field["label"], profile=field["profile"]) for field in VAT_FIELDS]


def update_vat_rates(values, changed_by="HeliAntha"):
    # Validate the entire payload before initialization or any writes. A failed form
    # neither partially changes valid fields nor invalidates the calculation cache.
    parsed = _validate_vat_values(values)
    if not parsed:
        return
    db = get_db()
    ensure_schema(db)
    with db:
        _write_vat_rates(db, parsed, changed_by)
    invalidate_calculation_context()


def _validated_legacy_vat_fraction(raw):
    percentage = parse_vat_percentage(parse_vat_percentage(raw) * 100)
    return float(percentage / 100)


def _pumping_vat_updates(rule, fraction):
    if int(rule.get("active", 1) or 0) != 1:
        return {}
    if rule.get("rule_type") == "pump_sale_parameters":
        components = ("equipment",)
    elif rule.get("rule_type") == "vat_pricing":
        components = {
            "panels": ("panels",), "transport": ("transport",),
            "others": ("equipment", "accessories", "installation"),
        }.get(rule.get("applies_to"), ())
    else:
        components = ()
    percentage = parse_vat_percentage(str(fraction)) * 100
    return {f"pumping_{component}": percentage for component in components}


def _load_raw_calculation_context():
    db = get_db()
    ensure_schema(db)
    params = {
        row["key"]: dict(row)
        for row in db.execute("SELECT * FROM calculation_parameters WHERE active = 1").fetchall()
    }
    pricing = {
        row["key"]: dict(row)
        for row in db.execute("SELECT * FROM pricing_rules WHERE active = 1").fetchall()
    }
    pumping_rules = {
        row["rule_key"]: dict(row)
        for row in db.execute("SELECT * FROM pumping_solar_rules WHERE active = 1").fetchall()
    }
    ongrid_parameters = {
        row["key"]: dict(row)
        for row in db.execute("SELECT * FROM ongrid_parameters ORDER BY id").fetchall()
    }
    # Keep inactive rows in the context so the calculation layer can make the
    # active/inactive decision without interpreting an empty active result as
    # "no database catalogue" and silently restoring bundled demo products.
    products = _products_with_pump_curves(
        db,
        db.execute("SELECT * FROM products ORDER BY id").fetchall(),
    )
    reference = active_reference()
    return {
        "technical_parameters": params,
        "pricing_rules": pricing,
        "pumping_solar_rules": pumping_rules,
        "ongrid_parameters": ongrid_parameters,
        "vat_rates": {row["key"]: dict(row) for row in db.execute("SELECT * FROM vat_rates").fetchall()},
        "products": products,
        "technical_reference": reference,
    }



def load_calculation_context():
    global _CALC_CACHE, _CALC_CACHE_VERSION, _CALC_CACHE_TIME
    
    # En mode test unitaire, lecture directe pour respecter l'isolation des bases temporaires
    try:
        if current_app and current_app.config.get("TESTING"):
            return _load_raw_calculation_context()
    except Exception:
        pass

    now = time.time()
    current_version = _get_redis_version()

    if _CALC_CACHE is not None:
        if current_version is not None and current_version == _CALC_CACHE_VERSION:
            return _CALC_CACHE
        elif current_version is None and (now - _CALC_CACHE_TIME) < 60:
            return _CALC_CACHE

    _CALC_CACHE = _load_raw_calculation_context()
    _CALC_CACHE_VERSION = current_version
    _CALC_CACHE_TIME = now
    return _CALC_CACHE

def save_quote(quote_number, project, data, contact, result):
    db = get_db()
    ensure_schema(db)
    financial = result.get("financial_breakdown") or {}
    calculation_detail = result.get("calculation_detail") or {}
    snapshot = result.get("quote_snapshot") or {}
    offers = result.get("offers") or []
    selected_offer_level = next((offer.get("level") for offer in offers if offer.get("recommended")), "")
    cursor = db.execute(
        """INSERT INTO quote_requests
        (quote_number, project, customer_name, phone, email, location, company, city,
         request_json, result_json, status, solution_name, amount_ht, amount_ttc,
         confidence, reliability_json, calculation_detail_json, financial_breakdown_json,
         selected_equipment_json, calculator_versions_json, technical_parameters_json,
         quote_snapshot_json, technical_reference_json, bom_json, technical_configuration_json,
         compatibility_json, product_selections_json, selected_offer_level, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            quote_number,
            project,
            contact.get("name", ""),
            contact.get("phone", ""),
            contact.get("email", ""),
            contact.get("location", ""),
            contact.get("company", ""),
            data.get("city") or contact.get("location", ""),
            dumps({"data": data, "contact": contact}),
            dumps(result),
            contact.get("status", "Nouveau") if contact.get("status") in QUOTE_STATUSES else "Nouveau",
            result.get("title", ""),
            financial.get("total_ht"),
            financial.get("total_ttc"),
            result.get("confidence"),
            dumps(result.get("reliability") or {}),
            dumps(calculation_detail),
            dumps(financial),
            dumps(result.get("selected_equipment") or []),
            dumps(result.get("calculator_versions") or {}),
            dumps(calculation_detail.get("parameters_used") or {}),
            dumps(snapshot),
            dumps(result.get("technical_reference") or {}),
            dumps(result.get("bom") or {}),
            dumps(result.get("technical_configuration") or {}),
            dumps(result.get("compatibility") or {}),
            dumps(result.get("product_selections") or {}),
            selected_offer_level,
            utc_now(),
        ),
    )
    db.commit()
    return cursor.lastrowid


def list_quotes(search="", project="", status="", limit=200):
    db = get_db()
    ensure_schema(db)
    where = []
    values = []
    if search:
        where.append("(quote_number LIKE ? OR customer_name LIKE ? OR phone LIKE ? OR email LIKE ? OR location LIKE ?)")
        term = f"%{search}%"
        values.extend([term, term, term, term, term])
    if project:
        where.append("project = ?")
        values.append(project)
    if status:
        where.append("status = ?")
        values.append(status)
    sql = "SELECT * FROM quote_requests"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC"
    if limit is not None:
        sql += " LIMIT ?"
        values.append(limit)
    return [dict(row) for row in db.execute(sql, values).fetchall()]


def get_quote(quote_id):
    db = get_db()
    ensure_schema(db)
    row = db.execute("SELECT * FROM quote_requests WHERE id = ?", (quote_id,)).fetchone()
    return _hydrate_quote(row)


def get_quote_by_number(quote_number):
    db = get_db()
    ensure_schema(db)
    row = db.execute("SELECT * FROM quote_requests WHERE quote_number = ?", (quote_number,)).fetchone()
    return _hydrate_quote(row)


def _hydrate_quote(row):
    if not row:
        return None
    quote = dict(row)
    quote["request"] = loads(quote.get("request_json"), {})
    quote["result"] = loads(quote.get("result_json"), {})
    quote["reliability"] = loads(quote.get("reliability_json"), {})
    quote["calculation_detail"] = loads(quote.get("calculation_detail_json"), {})
    quote["financial_breakdown"] = loads(quote.get("financial_breakdown_json"), {})
    quote["selected_equipment"] = loads(quote.get("selected_equipment_json"), [])
    quote["calculator_versions"] = loads(quote.get("calculator_versions_json"), {})
    quote["technical_parameters"] = loads(quote.get("technical_parameters_json"), {})
    quote["quote_snapshot"] = loads(quote.get("quote_snapshot_json"), {})
    quote["technical_reference"] = loads(quote.get("technical_reference_json"), {})
    quote["bom"] = loads(quote.get("bom_json"), {})
    quote["technical_configuration"] = loads(quote.get("technical_configuration_json"), {})
    quote["compatibility"] = loads(quote.get("compatibility_json"), {})
    quote["product_selections"] = loads(quote.get("product_selections_json"), {})
    quote["visit_requests"] = [
        dict(item)
        for item in get_db().execute(
            "SELECT * FROM visit_requests WHERE quote_id = ? ORDER BY id DESC",
            (quote["id"],),
        ).fetchall()
    ]
    quote["client_events"] = [
        dict(item)
        for item in get_db().execute(
            "SELECT * FROM quote_client_events WHERE quote_id = ? ORDER BY id DESC",
            (quote["id"],),
        ).fetchall()
    ]
    quote["status_history"] = [
        dict(item)
        for item in get_db().execute(
            "SELECT * FROM quote_status_history WHERE quote_id = ? ORDER BY id DESC",
            (quote["id"],),
        ).fetchall()
    ]
    return quote


def update_quote_status(quote_id, new_status, changed_by="admin"):
    if new_status not in QUOTE_STATUSES:
        raise ValueError("Statut non reconnu")
    db = get_db()
    ensure_schema(db)
    row = db.execute("SELECT status FROM quote_requests WHERE id = ?", (quote_id,)).fetchone()
    if not row:
        return False
    old_status = row["status"]
    db.execute(
        "UPDATE quote_requests SET status = ?, updated_at = ? WHERE id = ?",
        (new_status, utc_now(), quote_id),
    )
    db.execute(
        """INSERT INTO quote_status_history (quote_id, old_status, new_status, changed_by)
        VALUES (?, ?, ?, ?)""",
        (quote_id, old_status, new_status, changed_by),
    )
    db.commit()
    return True


def update_quote_selected_offer(quote_id, level):
    db = get_db()
    ensure_schema(db)
    db.execute(
        "UPDATE quote_requests SET selected_offer_level = ?, updated_at = ? WHERE id = ?",
        (level, utc_now(), quote_id),
    )
    db.commit()


def save_visit_request(quote_id, quote_number, payload):
    db = get_db()
    ensure_schema(db)
    db.execute(
        """INSERT INTO visit_requests
        (quote_id, quote_number, preferred_date, time_slot, address, phone, comment, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            quote_id,
            quote_number,
            payload.get("preferred_date", ""),
            payload.get("time_slot", ""),
            payload.get("address", ""),
            payload.get("phone", ""),
            payload.get("comment", ""),
            "Nouveau",
        ),
    )
    update_quote_status(quote_id, "Visite programmee", payload.get("requested_by", "Client"))
    return True


def save_quote_client_event(quote_id, quote_number, event_type, event_value=""):
    db = get_db()
    ensure_schema(db)
    db.execute(
        """INSERT INTO quote_client_events (quote_id, quote_number, event_type, event_value)
        VALUES (?, ?, ?, ?)""",
        (quote_id, quote_number, event_type, event_value),
    )
    db.commit()


def enqueue_whatsapp_message(
    phone, msg_type="text", pdf_url="", filename="", caption="", *, replace_pending=False
):
    db = get_db()
    ensure_schema(db)
    if replace_pending:
        from .services.anti_abuse import whatsapp_queue_key

        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
        key = whatsapp_queue_key(phone, caption)
        pending = db.execute(
            "SELECT id, phone, caption FROM whatsapp_outbox WHERE status = 'PENDING' "
            "AND msg_type = ? ORDER BY id DESC", (str(msg_type),)
        ).fetchall()
        existing = next(
            (row for row in pending if whatsapp_queue_key(row["phone"], row["caption"]) == key),
            None,
        )
        if existing is not None:
            db.execute(
                """UPDATE whatsapp_outbox SET phone = ?, pdf_url = ?, filename = ?,
                caption = ?, attempts = 0, error_message = NULL WHERE id = ?""",
                (str(phone).strip(), str(pdf_url).strip(), str(filename).strip(),
                 str(caption).strip(), existing["id"]),
            )
            db.commit()
            return int(existing["id"])
    cursor = db.execute(
        """INSERT INTO whatsapp_outbox
        (phone, msg_type, pdf_url, filename, caption, status, attempts)
        VALUES (?, ?, ?, ?, ?, 'PENDING', 0)""",
        (
            str(phone or "").strip(),
            str(msg_type or "text").strip() or "text",
            str(pdf_url or "").strip(),
            str(filename or "").strip(),
            str(caption or "").strip(),
        ),
    )
    db.commit()
    return int(cursor.lastrowid)


def list_whatsapp_outbox(status=None, limit=10, newest=True):
    db = get_db()
    ensure_schema(db)
    limit = max(1, min(int(limit or 10), 100))
    order = "DESC" if newest else "ASC"
    if status:
        rows = db.execute(
            f"""SELECT * FROM whatsapp_outbox
            WHERE status = ?
            ORDER BY created_at {order}, id {order}
            LIMIT ?""",
            (status, limit),
        ).fetchall()
    else:
        rows = db.execute(
            f"""SELECT * FROM whatsapp_outbox
            ORDER BY created_at {order}, id {order}
            LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def _outbox_payload_condition(payload):
    if payload is None:
        return "", ()
    fields = ("phone", "msg_type", "pdf_url", "filename", "caption")
    return "".join(f" AND {field} = ?" for field in fields), tuple(
        str(payload.get(field) or "") for field in fields
    )


def mark_whatsapp_outbox_sent(item_id, *, expected_payload=None):
    db = get_db()
    ensure_schema(db)
    condition, values = _outbox_payload_condition(expected_payload)
    db.execute(
        """UPDATE whatsapp_outbox
        SET status = 'SENT', sent_at = ?, error_message = NULL
        WHERE id = ?""" + condition,
        (utc_now(), item_id, *values),
    )
    db.commit()


def mark_whatsapp_outbox_failed(item_id, attempts, error_message="", *, expected_payload=None):
    db = get_db()
    ensure_schema(db)
    next_status = "FAILED" if int(attempts or 0) >= 5 else "PENDING"
    condition, values = _outbox_payload_condition(expected_payload)
    db.execute(
        """UPDATE whatsapp_outbox
        SET status = ?, attempts = ?, error_message = ?
        WHERE id = ?""" + condition,
        (next_status, int(attempts or 0), str(error_message or "").strip(), item_id, *values),
    )
    db.commit()


def dashboard_stats():
    db = get_db()
    ensure_schema(db)
    rows = [dict(row) for row in db.execute("SELECT * FROM quote_requests ORDER BY id DESC").fetchall()]
    canonical_projects = set(PUBLIC_PROJECTS)
    rows = [row for row in rows if row.get("project") in canonical_projects]
    today = datetime.now(UTC).date().isoformat()
    by_status = {}
    for row in rows:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
    project_counts = {project: 0 for project in PUBLIC_PROJECTS}
    for row in rows:
        project = row["project"]
        project_counts[project] = project_counts.get(project, 0) + 1
    project_breakdown = [
        {
            "key": project,
            "label": DASHBOARD_PROJECT_LABELS.get(project, project),
            "count": count,
        }
        for project in PUBLIC_PROJECTS
        if (count := project_counts.get(project, 0)) > 0
    ]
    return {
        "total_prospects": len(rows),
        "new_today": sum(1 for row in rows if str(row.get("created_at", "")).startswith(today)),
        "simulations": len(rows),
        "quotes_generated": len(rows),
        "visit_requests": by_status.get("Visite programmee", 0),
        "pending_quotes": by_status.get("Nouveau", 0) + by_status.get("A contacter", 0),
        "accepted_quotes": by_status.get("Accepte", 0),
        "refused_quotes": by_status.get("Refuse", 0),
        "installing_projects": by_status.get("Installation", 0),
        "project_breakdown": project_breakdown,
        "by_status": by_status,
        "latest_quotes": rows[:8],
    }


def list_products(search="", category="", active="", brand="", stock="", sort="catalog"):
    db = get_db()
    ensure_schema(db)
    where = []
    values = []
    if search:
        where.append("(reference LIKE ? OR brand LIKE ? OR model LIKE ? OR description LIKE ?)")
        term = f"%{search}%"
        values.extend([term, term, term, term])
    if category:
        where.append("category = ?")
        values.append(category)
    if brand:
        where.append("brand = ?")
        values.append(brand)
    if active in ("0", "1"):
        where.append("active = ?")
        values.append(int(active))
    if stock == "available":
        where.append("stock > 0")
    elif stock == "empty":
        where.append("stock <= 0")
    sql = "SELECT * FROM products"
    if where:
        sql += " WHERE " + " AND ".join(where)
    order_by = {
        "catalog": "active DESC, preferred DESC, priority DESC, category, brand, reference",
        "brand": "brand, model, reference",
        "stock_desc": "stock DESC, preferred DESC, reference",
        "price_desc": "sale_price DESC, reference",
        "price_asc": "sale_price ASC, reference",
        "updated": "updated_at DESC, reference",
    }.get(sort, "active DESC, preferred DESC, priority DESC, category, brand, reference")
    sql += f" ORDER BY {order_by}"
    return _products_with_pump_curves(db, db.execute(sql, values).fetchall())


def get_product(product_id):
    db = get_db()
    ensure_schema(db)
    row = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    products = _products_with_pump_curves(db, [row] if row else [])
    return products[0] if products else None


def save_product(product, product_id=None, submitted_fields=None):
    invalidate_calculation_context()
    db = get_db()
    ensure_schema(db)
    existing = get_product(product_id) if product_id else None
    validated = validate_product(product, existing=existing, submitted_fields=submitted_fields)
    if validated.get("category") == "pumps" and not validated.get("reference"):
        validated["reference"] = (
            (existing or {}).get("reference")
            or f"PUMP-INTERNAL-{uuid4().hex.upper()}"
        )
    technical_specs = dict(validated.get("technical_specs") or {})
    curve_was_submitted = (
        validated.get("category") == "pumps"
        and (
            (submitted_fields is not None and "spec_curve_points" in submitted_fields)
            or "curve_points" in technical_specs
        )
    )
    curve_points = technical_specs.pop("curve_points", [])
    validated["technical_specs"] = technical_specs
    values = (
        validated.get("reference"),
        validated.get("category"),
        validated.get("subcategory"),
        validated.get("brand"),
        validated.get("model"),
        validated.get("description"),
        validated.get("power_kw"),
        validated.get("power_w"),
        validated.get("voltage"),
        validated.get("current_amp"),
        validated.get("capacity_kwh"),
        validated.get("capacity_l"),
        validated.get("efficiency"),
        validated.get("technology"),
        dumps(technical_specs),
        validated.get("purchase_price"),
        validated.get("sale_price"),
        validated.get("supplier"),
        validated.get("stock"),
        validated.get("unit"),
        validated.get("warranty"),
        validated.get("vat_rate"),
        validated.get("currency"),
        validated.get("datasheet_url"),
        int(validated.get("demo", 0)),
        int(validated.get("preferred", 0)),
        int(validated.get("priority", 0)),
        int(validated.get("active", 1)),
        utc_now(),
    )
    try:
        saved_product_id = product_id
        if product_id:
            db.execute(
                """UPDATE products SET reference=?, category=?, subcategory=?, brand=?, model=?,
                description=?, power_kw=?, power_w=?, voltage=?, current_amp=?, capacity_kwh=?,
                capacity_l=?, efficiency=?, technology=?, technical_specs_json=?, purchase_price=?,
                sale_price=?, supplier=?, stock=?, unit=?, warranty=?, vat_rate=?, currency=?,
                datasheet_url=?, demo=?, preferred=?, priority=?, active=?, updated_at=?
                WHERE id=?""",
                values + (product_id,),
            )
        else:
            cursor = db.execute(
                """INSERT INTO products
                (reference, category, subcategory, brand, model, description, power_kw, power_w,
                 voltage, current_amp, capacity_kwh, capacity_l, efficiency, technology,
                 technical_specs_json, purchase_price, sale_price, supplier, stock, unit, warranty,
                 vat_rate, currency, datasheet_url, demo, preferred, priority, active, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
            saved_product_id = cursor.lastrowid
    except sqlite3.IntegrityError as exc:
        raise ProductValidationError({"reference": "Cette reference existe deja dans le catalogue."}) from exc
    if curve_was_submitted and saved_product_id:
        db.execute("DELETE FROM pump_curve_points WHERE pump_id = ?", (saved_product_id,))
        db.executemany(
            """INSERT INTO pump_curve_points (pump_id, flow_m3_h, hmt_m)
            VALUES (?, ?, ?)""",
            [
                (saved_product_id, point["flow_m3_h"], point["hmt_m"])
                for point in curve_points
            ],
        )
    db.commit()
    return saved_product_id


def set_product_active(product_id, active):
    db = get_db()
    ensure_schema(db)
    db.execute("UPDATE products SET active = ?, updated_at = ? WHERE id = ?", (1 if active else 0, utc_now(), product_id))
    db.commit()


def list_calculation_parameters(admin_visible_only=False):
    db = get_db()
    ensure_schema(db)
    sql = "SELECT * FROM calculation_parameters"
    values = ()
    if admin_visible_only:
        sql += " WHERE admin_visible = 1"
    sql += " ORDER BY category, key"
    return [dict(row) for row in db.execute(sql, values).fetchall()]


def get_calculation_parameter(param_id):
    db = get_db()
    ensure_schema(db)
    row = db.execute("SELECT * FROM calculation_parameters WHERE id = ?", (param_id,)).fetchone()
    return dict(row) if row else None


def update_calculation_parameter(
    param_id,
    value,
    active=True,
    source_type=None,
    source_name=None,
    source_reference=None,
    validated_by=None,
    validated_at=None,
    changed_by="admin",
    change_comment="",
):
    invalidate_calculation_context()
    db = get_db()
    ensure_schema(db)
    row = db.execute("SELECT * FROM calculation_parameters WHERE id = ?", (param_id,)).fetchone()
    if not row:
        return False
    current = dict(row)
    if not current.get("editable"):
        raise PermissionError("Ce paramètre est verrouillé et ne peut pas être modifié depuis l'administration normale.")

    next_source_type = source_type if source_type is not None else current.get("source_type")
    next_source_name = source_name if source_name is not None else current.get("source_name")
    next_source_reference = source_reference if source_reference is not None else current.get("source_reference")
    next_validated_by = validated_by if validated_by is not None else current.get("validated_by")
    next_validated_at = validated_at if validated_at is not None else current.get("validated_at")
    db.execute(
        """UPDATE calculation_parameters SET value = ?, active = ?, source_type = ?,
        source_name = ?, source_reference = ?, validated_by = ?, validated_at = ?, updated_at = ?
        WHERE id = ?""",
        (
            value,
            1 if active else 0,
            next_source_type,
            next_source_name,
            next_source_reference,
            next_validated_by,
            next_validated_at,
            utc_now(),
            param_id,
        ),
    )
    if float(current.get("value") or 0) != float(value) or (current.get("source_type") or "") != (next_source_type or ""):
        db.execute(
            """INSERT INTO calculation_parameter_history
            (parameter_id, parameter_key, old_value, new_value, changed_by,
             source_type, source_name, source_reference, change_comment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                param_id,
                current["key"],
                current["value"],
                value,
                changed_by,
                next_source_type,
                next_source_name,
                next_source_reference,
                change_comment,
            ),
        )
    db.commit()
    return True


def list_calculation_parameter_history(limit=80):
    db = get_db()
    ensure_schema(db)
    return [
        dict(row)
        for row in db.execute(
            """SELECT h.*, p.display_name, p.name, p.display_kind, p.unit, p.category
            FROM calculation_parameter_history h
            LEFT JOIN calculation_parameters p ON p.id = h.parameter_id
            ORDER BY h.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    ]


def list_pricing_rules():
    db = get_db()
    ensure_schema(db)
    return [dict(row) for row in db.execute("SELECT * FROM pricing_rules ORDER BY key").fetchall()]


def update_pricing_rule(rule_id, value, active=True):
    invalidate_calculation_context()
    db = get_db()
    ensure_schema(db)
    db.execute(
        "UPDATE pricing_rules SET value = ?, active = ?, updated_at = ? WHERE id = ?",
        (value, 1 if active else 0, utc_now(), rule_id),
    )
    db.commit()


def list_pumping_solar_rules():
    db = get_db()
    ensure_schema(db)
    return [
        dict(row)
        for row in db.execute(
            "SELECT * FROM pumping_solar_rules ORDER BY sort_order, pump_cv, panel_power_w, drive_power_kw, id"
        ).fetchall()
    ]


def get_pumping_solar_rule(rule_id):
    db = get_db()
    ensure_schema(db)
    row = db.execute("SELECT * FROM pumping_solar_rules WHERE id = ?", (rule_id,)).fetchone()
    return dict(row) if row else None


def update_pumping_solar_rule(rule_id, data: dict[str, object], changed_by: str = "HeliAntha") -> bool:
    data = dict(data)
    if "vat_rate" in data and data["vat_rate"] not in (None, ""):
        data["vat_rate"] = _validated_legacy_vat_fraction(data["vat_rate"])
    db = get_db()
    ensure_schema(db)
    row = db.execute("SELECT * FROM pumping_solar_rules WHERE id = ?", (rule_id,)).fetchone()
    if not row:
        return False
    current = dict(row)
    mutable_fields = {
        "title",
        "pump_cv",
        "panel_count",
        "panel_power_w",
        "panel_reference",
        "panel_sale_price_ht",
        "drive_power_kw",
        "drive_reference",
        "drive_sale_price_ht",
        "drive_brand",
        "phase",
        "min_cv",
        "max_cv",
        "pricing_mode",
        "unit_price_ht",
        "coefficient_1",
        "coefficient_2",
        "vat_rate",
        "applies_to",
        "source_type",
        "source_name",
        "source_reference",
        "notes",
        "sort_order",
        "active",
    }
    updates = {}
    for key in mutable_fields:
        if key in data:
            updates[key] = data[key]
    if not updates:
        return True
    updates["updated_by"] = changed_by
    updates["updated_at"] = utc_now()
    assignments = ", ".join(f"{key} = ?" for key in updates)
    with db:
        db.execute(
            f"UPDATE pumping_solar_rules SET {assignments} WHERE id = ?",
            tuple(updates.values()) + (rule_id,),
        )
        merged = dict(current, **updates)
        if merged.get("vat_rate") not in (None, "") and ("vat_rate" in updates or "applies_to" in updates):
            central = _pumping_vat_updates(merged, merged["vat_rate"])
            if central:
                _write_vat_rates(db, central, changed_by)
    invalidate_calculation_context()
    return True


def create_pumping_solar_rule(data: dict[str, object], changed_by: str = "HeliAntha") -> int:
    data = dict(data)
    if data.get("vat_rate") not in (None, ""):
        data["vat_rate"] = _validated_legacy_vat_fraction(data["vat_rate"])
    db = get_db()
    ensure_schema(db)
    payload = {
        "rule_key": str(data.get("rule_key") or "").strip(),
        "rule_type": str(data.get("rule_type") or "").strip(),
        "title": str(data.get("title") or "").strip(),
        "pump_cv": data.get("pump_cv"),
        "panel_count": data.get("panel_count"),
        "panel_power_w": data.get("panel_power_w"),
        "panel_reference": str(data.get("panel_reference") or "").strip(),
        "panel_sale_price_ht": data.get("panel_sale_price_ht"),
        "drive_power_kw": data.get("drive_power_kw"),
        "drive_reference": str(data.get("drive_reference") or "").strip(),
        "drive_sale_price_ht": data.get("drive_sale_price_ht"),
        "drive_brand": str(data.get("drive_brand") or "").strip(),
        "phase": str(data.get("phase") or "").strip(),
        "min_cv": data.get("min_cv"),
        "max_cv": data.get("max_cv"),
        "pricing_mode": str(data.get("pricing_mode") or "").strip(),
        "unit_price_ht": data.get("unit_price_ht"),
        "coefficient_1": data.get("coefficient_1"),
        "coefficient_2": data.get("coefficient_2"),
        "vat_rate": data.get("vat_rate"),
        "applies_to": str(data.get("applies_to") or "").strip(),
        "source_type": str(data.get("source_type") or "heliantha").strip() or "heliantha",
        "source_name": str(data.get("source_name") or "HeliAntha").strip() or "HeliAntha",
        "source_reference": str(data.get("source_reference") or "").strip(),
        "notes": str(data.get("notes") or "").strip(),
        "sort_order": data.get("sort_order"),
        "active": 1 if data.get("active", 1) else 0,
        "updated_by": changed_by,
        "updated_at": utc_now(),
    }
    columns = ", ".join(payload.keys())
    placeholders = ", ".join("?" for _ in payload)
    with db:
        cursor = db.execute(
            f"INSERT INTO pumping_solar_rules ({columns}) VALUES ({placeholders})",
            tuple(payload.values()),
        )
        if payload["vat_rate"] not in (None, ""):
            central = _pumping_vat_updates(payload, payload["vat_rate"])
            if central:
                _write_vat_rates(db, central, changed_by)
    invalidate_calculation_context()
    return int(cursor.lastrowid)


def list_ongrid_parameters():
    db = get_db()
    ensure_schema(db)
    return [dict(row) for row in db.execute("SELECT * FROM ongrid_parameters ORDER BY id").fetchall()]


def update_ongrid_parameters(values: dict[str, object], changed_by: str = "HeliAntha") -> None:
    legacy_vat = {
        "vat_pv_rate": ("panels",), "vat_transport_rate": ("transport",),
        "vat_standard_rate": ("equipment", "accessories", "installation"),
    }
    central = {}
    errors = {}
    for key, raw in values.items():
        if key in legacy_vat:
            try:
                value = parse_vat_percentage(raw)
                central.update({f"residential_{component}": value for component in legacy_vat[key]})
            except TaxValidationError as exc:
                errors[key] = str(exc)
    if errors:
        raise TaxValidationError(next(iter(errors.values())), errors=errors)
    db = get_db()
    ensure_schema(db)
    known = {
        row["key"]: dict(row)
        for row in db.execute("SELECT * FROM ongrid_parameters").fetchall()
    }
    defaults = {key: (label, value, unit, description) for key, label, value, unit, description in ONGRID_PARAMETER_DEFAULTS}
    with db:
        for key, raw_value in values.items():
            if key not in defaults:
                continue
            value_text = str("" if raw_value is None else raw_value).strip().replace(",", ".")
            if not value_text:
                continue
            label, _default, unit, description = defaults[key]
            if key in known:
                db.execute(
                    """UPDATE ongrid_parameters
                    SET value = ?, updated_by = ?, updated_at = ?
                    WHERE key = ?""",
                    (value_text, changed_by, utc_now(), key),
                )
            else:
                db.execute(
                    """INSERT INTO ongrid_parameters
                    (key, label, value, unit, description, updated_by)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (key, label, value_text, unit, description, changed_by),
                )
        if central:
            _write_vat_rates(db, central, changed_by)
    invalidate_calculation_context()


def active_reference():
    db = get_db()
    row = db.execute(
        "SELECT * FROM technical_references WHERE status = 'Actif' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row:
        return dict(row)
    return dict(TECHNICAL_REFERENCE)


def list_company_settings():
    db = get_db()
    ensure_schema(db)
    return [dict(row) for row in db.execute("SELECT * FROM company_settings ORDER BY category, key").fetchall()]


def update_company_setting(setting_id, value):
    db = get_db()
    ensure_schema(db)
    db.execute(
        "UPDATE company_settings SET value = ?, updated_at = ? WHERE id = ?",
        (value, utc_now(), setting_id),
    )
    db.commit()


def list_users():
    db = get_db()
    ensure_schema(db)
    return [dict(row) for row in db.execute("SELECT * FROM users ORDER BY role, username").fetchall()]


def get_primary_admin_user():
    db = get_db()
    ensure_schema(db)
    row = db.execute(
        """SELECT * FROM users
        WHERE active = 1 AND (username = 'direction@heliantha.ma' OR role = 'Direction')
        ORDER BY CASE WHEN username = 'direction@heliantha.ma' THEN 0 ELSE 1 END, id ASC
        LIMIT 1"""
    ).fetchone()
    return dict(row) if row else None


def authenticate_user(email: str, password: str):
    db = get_db()
    ensure_schema(db)
    row = db.execute(
        "SELECT * FROM users WHERE username = ? AND active = 1 ORDER BY id ASC LIMIT 1",
        (email.strip().lower(),),
    ).fetchone()
    if not row:
        return None
    user = dict(row)
    if user.get("password_hash") and check_password_hash(user["password_hash"], password):
        return user
    return None


def get_user(user_id):
    db = get_db()
    ensure_schema(db)
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def save_user(user_id=None, username="", display_name="", role="Commercial", active=True, password=""):
    db = get_db()
    ensure_schema(db)
    username = username.strip().lower()
    display_name = display_name.strip() or username
    payload = (
        username,
        display_name,
        role.strip() or "Commercial",
        1 if active else 0,
    )
    if user_id:
        if password:
            db.execute(
                "UPDATE users SET username = ?, display_name = ?, role = ?, active = ?, password_hash = ? WHERE id = ?",
                (*payload, generate_password_hash(password), user_id),
            )
        else:
            db.execute(
                "UPDATE users SET username = ?, display_name = ?, role = ?, active = ? WHERE id = ?",
                (*payload, user_id),
            )
        db.commit()
        return user_id
    cursor = db.execute(
        "INSERT INTO users (username, display_name, role, active, password_hash) VALUES (?, ?, ?, ?, ?)",
        (*payload, generate_password_hash(password) if password else ""),
    )
    db.commit()
    return cursor.lastrowid


def delete_user(user_id):
    db = get_db()
    ensure_schema(db)
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()


def _product_from_row(row):
    product = dict(row)
    product["technical_specs"] = loads(product.pop("technical_specs_json", None), {})
    product["completeness"] = product_completeness(product)
    return product


def _products_with_pump_curves(db, rows):
    products = [_product_from_row(row) for row in rows]
    pump_ids = [product["id"] for product in products if product.get("category") == "pumps"]
    points_by_pump = {pump_id: [] for pump_id in pump_ids}
    if pump_ids:
        placeholders = ",".join("?" for _ in pump_ids)
        rows = db.execute(
            f"""SELECT pump_id, flow_m3_h, hmt_m
            FROM pump_curve_points
            WHERE pump_id IN ({placeholders})
            ORDER BY pump_id, flow_m3_h, id""",
            pump_ids,
        ).fetchall()
        for row in rows:
            points_by_pump[row["pump_id"]].append({
                "flow_m3_h": float(row["flow_m3_h"]),
                "hmt_m": float(row["hmt_m"]),
            })
    for product in products:
        if product.get("category") == "pumps":
            product["pump_curve_points"] = points_by_pump.get(product["id"], [])
            product["completeness"] = product_completeness(product)
    return products
