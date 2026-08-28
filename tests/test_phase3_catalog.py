import json

from app import create_app
from app.calculators import CalculationEngine
from app.defaults import CATALOG_PRODUCTS
from app.services.product_selector import ProductSelector


def test_demo_panel_selection_is_clearly_flagged():
    selection = ProductSelector(CATALOG_PRODUCTS).select_panel(3.2)

    codes = {item["code"] for item in selection["warnings"]}
    assert selection["selected_product"] is not None
    assert "DEMO_PRODUCT_SELECTED" in codes


def test_incomplete_catalog_product_generates_warning():
    products = [{
        "reference": "PV-INCOMPLETE",
        "category": "panels",
        "brand": "Test",
        "model": "500 W",
        "power_w": 500,
        "sale_price": 900,
        "unit": "piece",
        "active": 1,
        "demo": 0,
        "technical_specs": {},
    }]

    selection = ProductSelector(products).select_panel(2.0)

    assert selection["status"] == "compatible_with_warning"
    assert any(item["code"] == "PRODUCT_DATA_INCOMPLETE" for item in selection["warnings"])


def test_battery_catalog_values_override_fallback_parameters_in_phase3():
    custom_battery = {
        "reference": "BAT-LFP-CUSTOM",
        "category": "batteries",
        "subcategory": "lithium",
        "brand": "HeliAntha Storage",
        "model": "LFP 5.12 Premium",
        "capacity_kwh": 5.12,
        "sale_price": 15000,
        "unit": "piece",
        "warranty": "10 ans",
        "preferred": 1,
        "active": 1,
        "demo": 0,
        "technical_specs": {
            "depth_of_discharge": 0.90,
            "round_trip_efficiency": 0.96,
            "nominal_voltage_v": 51.2,
            "continuous_power_kw": 5.0,
        },
    }
    products = [custom_battery] + [item for item in CATALOG_PRODUCTS if item["category"] != "batteries"]

    result = CalculationEngine().calculate(
        "offgrid",
        {"daily_kwh": 8, "peak_kw": 3, "city": "Rabat"},
        context={"products": products},
    )

    assert result["final_results"]["battery_dod"] == 0.90
    assert result["final_results"]["battery_efficiency"] == 0.96
    assert result["calculation_detail"]["resolved_sources"]["battery_dod"]["source_reference"] == "BAT-LFP-CUSTOM"
    assert result["calculation_detail"]["resolved_sources"]["battery_efficiency"]["source_reference"] == "BAT-LFP-CUSTOM"


def test_quote_snapshot_saves_bom_and_product_selections(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "phase3-bom.db")})
    client = app.test_client()

    response = client.post(
        "/api/calculate",
        json={"project": "ongrid", "data": {"monthly_kwh": 650, "city": "Marrakech", "roof_area": 60}},
    )

    assert response.status_code == 200
    with app.app_context():
        from app.db import get_db

        row = get_db().execute(
            "SELECT bom_json, product_selections_json, compatibility_json, calculator_versions_json FROM quote_requests"
        ).fetchone()
        bom = json.loads(row["bom_json"])
        selections = json.loads(row["product_selections_json"])
        compatibility = json.loads(row["compatibility_json"])
        versions = json.loads(row["calculator_versions_json"])

    assert bom["lines"]
    assert "panel" in selections
    assert compatibility["status"]
    assert versions["ProductSelector"] == "1.0"
    assert versions["BOMBuilder"] == "1.0"


def test_admin_catalog_form_saves_category_specific_specs(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "catalog-form.db")})
    client = app.test_client()
    client.post("/admin/login", data={"password": "heliantha2026"})

    response = client.post(
        "/admin/catalogue/new",
        data={
            "reference": "PV-640-ADMIN",
            "category": "panels",
            "subcategory": "monocristallin",
            "brand": "Admin Test",
            "model": "640 Wc",
            "unit": "piece",
            "sale_price": "1350",
            "stock": "7",
            "vat_rate": "20",
            "currency": "DH",
            "active": "on",
            "demo": "on",
            "spec_surface_m2": "2.9",
            "spec_voc_v": "49.8",
            "spec_vmp_v": "41.5",
            "spec_isc_a": "16.2",
            "spec_imp_a": "15.4",
            "spec_efficiency_percent": "21.5",
        },
    )

    assert response.status_code == 302
    with app.app_context():
        from app.db import get_product, get_db

        row = get_db().execute("SELECT id FROM products WHERE reference = 'PV-640-ADMIN'").fetchone()
        product = get_product(row["id"])

    assert product["technical_specs"]["surface_m2"] == 2.9
    assert product["technical_specs"]["voc_v"] == 49.8
    assert product["technical_specs"]["efficiency_percent"] == 0.215


def test_admin_quote_detail_renders_phase3_sections(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "quote-detail-phase3.db")})
    client = app.test_client()
    client.post(
        "/api/calculate",
        json={"project": "ongrid", "data": {"monthly_kwh": 650, "city": "Marrakech", "roof_area": 60}},
    )
    client.post("/admin/login", data={"password": "heliantha2026"})

    response = client.get("/admin/devis/1")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Selection du materiel" in html
    assert "Nomenclature technique (BOM)" in html
    assert "Compatibilite globale" in html


def test_calculator_versions_expose_phase3_services():
    result = CalculationEngine().calculate(
        "ongrid",
        {"monthly_kwh": 700, "city": "Marrakech", "roof_area": 80},
    )

    versions = result["calculator_versions"]
    assert versions["PricingEngine"] == "2.0-bom"
    assert versions["ProductSelector"] == "1.0"
    assert versions["CompatibilityChecker"] == "3.0"
    assert versions["BOMBuilder"] == "1.0"
