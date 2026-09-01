import json

import pytest

from app import create_app
from app.calculators import CalculationEngine
from app.defaults import CATALOG_PRODUCTS
from app.services.product_selector import ProductSelector


def test_demo_panel_selection_is_clearly_flagged():
    demo_panels = [item for item in CATALOG_PRODUCTS if item["reference"] in {"PV-590-HS", "PV-550-HS"}]
    selection = ProductSelector(demo_panels).select_panel(3.2)

    codes = {item["code"] for item in selection["warnings"]}
    assert selection["selected_product"] is not None
    assert "DEMO_PRODUCT_SELECTED" in codes


def test_incomplete_catalog_product_generates_warning():
    products = [
        {
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
        }
    ]

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


@pytest.mark.parametrize(
    "category, reference, spec_fields, expected_labels",
    [
        ("panels", "CAT-PANEL-400", {"spec_power_w": "400"}, ["Puissance du panneau"]),
        ("batteries", "CAT-BAT-5120", {"spec_capacity_kwh": "5.12"}, ["Capacité"]),
        (
            "inverters",
            "CAT-INV-10K",
            {"spec_type": "on_grid", "spec_power_kw": "10", "spec_phases": "triphase"},
            ["Type", "On-Grid", "Off-Grid", "Hybride", "Puissance", "Phase", "Monophasé", "Triphasé"],
        ),
        (
            "pumps",
            "CAT-PUMP-15CV",
            {
                "spec_power_hp": "15",
                "spec_power_kw": "11",
                "spec_phases": "triphase",
                "spec_voltage_v": "380",
                "spec_current_a": "24",
                "spec_curve_points": "10:147\n12:144\n15:141",
            },
            ["Puissance", "CV", "kW", "Phase", "Tension", "Courant", "Points", "HMT"],
        ),
        ("drives", "CAT-DRV-15K", {"spec_power_kw": "15", "spec_phases": "triphase"}, ["Puissance", "kW", "Phase"]),
        (
            "ev_chargers",
            "CAT-EV-11K",
            {"spec_power_kw": "11", "spec_phases": "triphase", "spec_connector": "Type 2"},
            ["Puissance", "Phase", "Connecteur"],
        ),
        (
            "protections",
            "CAT-PROT-32A",
            {"spec_protection_type": "Disjoncteur", "spec_current_a": "32", "spec_dc_or_ac": "ac"},
            ["Type", "Courant", "Courant électrique"],
        ),
        ("cables", "CAT-CABLE-6", {"spec_dc_or_ac": "dc", "spec_section_mm2": "6"}, ["Type", "Section"]),
        ("structures", "CAT-STRUCT-10", {"spec_structure_type": "Rail toiture"}, ["Type de structure"]),
        ("accessories", "CAT-ACC-01", {}, []),
        ("thermal", "CAT-THERM-200", {"spec_tank_volume_l": "200"}, ["Volume du ballon"]),
        ("other", "CAT-OTHER-01", {}, []),
    ],
)
def test_admin_catalog_form_is_dynamic_and_saves_minimal_specs(tmp_path, category, reference, spec_fields, expected_labels):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "catalog-form.db")})
    client = app.test_client()
    client.post("/admin/login", data={"password": "heliantha2026"})

    new_page = client.get("/admin/catalogue/new")
    new_html = new_page.get_data(as_text=True)
    assert new_page.status_code == 200
    assert "catalog-form.js" in new_html
    assert "catalog-tech-group" not in new_html
    assert "id=\"catalog-tech-section\"" not in new_html
    assert 'name="spec_' not in new_html
    assert "Fiche technique / URL" not in new_html

    create_payload = {
        "reference": reference,
        "category": category,
        "brand": "Admin Test",
        "model": "Modele test",
        "sale_price": "1350",
        "stock": "7",
        "vat_rate": "20",
        "currency": "DH",
        "active": "on",
    }
    create_payload.update(spec_fields)

    response = client.post("/admin/catalogue/new", data=create_payload)
    assert response.status_code == 302

    with app.app_context():
        from app.db import get_db, get_product

        row = get_db().execute("SELECT id FROM products WHERE reference = ?", (reference,)).fetchone()
        assert row is not None
        product = get_product(row["id"])
        created_specs = product.get("technical_specs") or {}

    edit_page = client.get(f"/admin/catalogue/{product['id']}/edit")
    edit_html = edit_page.get_data(as_text=True)
    assert edit_page.status_code == 200
    assert "catalog-form.js" in edit_html
    if expected_labels:
        assert 'id="catalog-tech-section"' in edit_html
        assert "catalog-tech-group" not in edit_html
        assert edit_html.count('name="spec_') == len(spec_fields)
    else:
        assert 'id="catalog-tech-section"' not in edit_html
        assert 'name="spec_' not in edit_html

    for label in expected_labels:
        assert label in edit_html

    if category == "panels":
        assert created_specs["power_w"] == 400
    elif category == "batteries":
        assert created_specs["capacity_kwh"] == 5.12
    elif category == "inverters":
        assert created_specs["type"] == "on_grid"
        assert created_specs["power_kw"] == 10
        assert created_specs["phases"] == "triphase"
    elif category == "pumps":
        assert created_specs["power_hp"] == 15
        assert created_specs["power_kw"] == 11
        assert created_specs["phases"] == "triphase"
        assert created_specs["voltage_v"] == 380
        assert created_specs["current_a"] == 24
        assert product["pump_curve_points"] == [
            {"flow_m3_h": 10.0, "hmt_m": 147.0},
            {"flow_m3_h": 12.0, "hmt_m": 144.0},
            {"flow_m3_h": 15.0, "hmt_m": 141.0},
        ]
    elif category == "drives":
        assert created_specs["power_kw"] == 15
        assert created_specs["phases"] == "triphase"
    elif category == "ev_chargers":
        assert created_specs["power_kw"] == 11
        assert created_specs["connector"] == "Type 2"
    elif category == "protections":
        assert created_specs["protection_type"] == "Disjoncteur"
    elif category == "cables":
        assert created_specs["section_mm2"] == 6
    elif category == "structures":
        assert created_specs["structure_type"] == "Rail toiture"
    elif category == "thermal":
        assert created_specs["tank_volume_l"] == 200
    else:
        assert created_specs == {}

    edit_response = client.post(
        f"/admin/catalogue/{product['id']}/edit",
        data={
            "reference": reference,
            "category": category,
            "brand": "Admin Test",
            "model": "Modele mis a jour",
            "sale_price": "1450",
            "stock": "9",
            "vat_rate": "20",
            "currency": "DH",
            "active": "on",
        },
    )
    assert edit_response.status_code == 302

    with app.app_context():
        from app.db import get_product

        updated = get_product(product["id"])

    assert updated["model"] == "Modele mis a jour"
    assert float(updated["sale_price"]) == pytest.approx(1450)


def test_admin_catalog_form_shows_french_labels(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "catalog-labels.db")})
    client = app.test_client()
    client.post("/admin/login", data={"password": "heliantha2026"})

    client.post(
        "/admin/catalogue/new",
        data={
            "reference": "CAT-INV-LABELS",
            "category": "inverters",
            "brand": "Test",
            "model": "Label test",
            "sale_price": "1000",
            "stock": "1",
            "vat_rate": "20",
            "currency": "DH",
            "active": "on",
            "spec_type": "on_grid",
            "spec_power_kw": "10",
            "spec_phases": "triphase",
        },
    )

    with app.app_context():
        from app.db import get_db, get_product

        row = get_db().execute("SELECT id FROM products WHERE reference = ?", ("CAT-INV-LABELS",)).fetchone()
        assert row is not None
        product = get_product(row["id"])

    html = client.get(f"/admin/catalogue/{product['id']}/edit").get_data(as_text=True)

    assert "On-Grid" in html
    assert "Off-Grid" in html
    assert "Hybride" in html
    assert "Monophasé" in html
    assert "Triphasé" in html


def test_admin_catalog_form_renders_only_current_category_fields(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "catalog-dom.db")})
    client = app.test_client()
    client.post("/admin/login", data={"password": "heliantha2026"})

    new_html = client.get("/admin/catalogue/new").get_data(as_text=True)
    assert 'id="catalog-tech-section"' not in new_html
    assert 'name="spec_power_w"' not in new_html
    assert 'name="spec_capacity_kwh"' not in new_html
    assert 'name="spec_power_hp"' not in new_html
    assert 'name="spec_power_kw"' not in new_html
    assert 'name="spec_connector"' not in new_html

    client.post(
        "/admin/catalogue/new",
        data={
            "reference": "CAT-DRIVE-15",
            "category": "drives",
            "brand": "VEICHI",
            "model": "Drive test",
            "sale_price": "4500",
            "stock": "3",
            "vat_rate": "20",
            "currency": "DH",
            "active": "on",
            "spec_power_kw": "15",
            "spec_phases": "triphase",
        },
    )

    with app.app_context():
        from app.db import get_db, get_product

        row = get_db().execute("SELECT id FROM products WHERE reference = ?", ("CAT-DRIVE-15",)).fetchone()
        assert row is not None
        product = get_product(row["id"])

    edit_html = client.get(f"/admin/catalogue/{product['id']}/edit").get_data(as_text=True)
    assert 'id="catalog-tech-section"' in edit_html
    assert 'name="spec_power_kw"' in edit_html
    assert 'name="spec_phases"' in edit_html
    assert 'name="spec_power_w"' not in edit_html
    assert 'name="spec_capacity_kwh"' not in edit_html
    assert 'name="spec_power_hp"' not in edit_html
    assert 'name="spec_connector"' not in edit_html
    assert 'name="spec_tank_volume_l"' not in edit_html


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
    assert "Éléments du devis" in html
    assert "Montant du devis" in html
    assert "Raisonnement technique" not in html
    assert "Formule" not in html
    assert "Source" not in html
    assert "Nomenclature technique" not in html
    assert "BOM" not in html
    assert "Selection du materiel" not in html
    assert "Donnees du questionnaire" not in html
    assert "Parametres utilises" not in html
    assert "Avertissements" not in html
    assert "Configuration technique retenue" not in html
    assert "Compatibilite globale" not in html
    assert "Hypotheses utilisees" not in html
    assert "Offres Essentiel / Optimal / Performance" not in html
    assert "Versions des calculateurs" not in html
    assert "Referentiel utilise" not in html


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
