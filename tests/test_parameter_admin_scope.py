import pytest

from app import create_app
from app.calculators import CalculationEngine
from app.defaults import CATALOG_PRODUCTS


def test_physical_constants_stay_available_in_engine_but_are_not_admin_parameters():
    result = CalculationEngine().calculate(
        "pumping",
        {
            "water_need": 25,
            "depth": 40,
            "elevation": 12,
            "distance": 60,
            "hours": 5,
            "city": "Casablanca",
        },
    )

    resolved = result["calculation_detail"]["resolved_sources"]
    params = result["calculation_detail"]["parameters_used"]

    assert resolved["gravity"]["source_type"] == "physical_constant"
    assert resolved["gravity"]["source_reference"] == "app.constants.GRAVITY"
    assert resolved["water_density"]["source_type"] == "physical_constant"
    assert resolved["water_density"]["source_reference"] == "app.constants.WATER_DENSITY"
    assert "gravity" not in params
    assert "water_density" not in params


def test_admin_calculation_page_hides_physical_constants(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "admin-hidden-constants.db")})
    client = app.test_client()
    client.post("/admin/login", data={"password": "heliantha2026"})

    response = client.get("/admin/parametres-calcul")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "gravity" not in html
    assert "water_density" not in html
    with app.app_context():
        from app.db import list_calculation_parameters

        visible = {item["key"] for item in list_calculation_parameters(admin_visible_only=True)}

    assert "gravity" not in visible
    assert "water_density" not in visible


def test_legacy_parameters_are_hidden_from_admin_calculation_page(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "admin-hidden-legacy.db")})
    client = app.test_client()
    client.post("/admin/login", data={"password": "heliantha2026"})

    response = client.get("/admin/parametres-calcul")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "pv_losses" not in html
    assert "inverter_efficiency" not in html
    with app.app_context():
        from app.db import list_calculation_parameters

        visible = {item["key"] for item in list_calculation_parameters(admin_visible_only=True)}

    assert "pv_losses" not in visible
    assert "inverter_efficiency" not in visible


def test_admin_calculation_page_no_longer_shows_technical_details_block(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "admin-no-tech-block.db")})
    client = app.test_client()
    client.post("/admin/login", data={"password": "heliantha2026"})

    html = client.get("/admin/parametres-calcul").get_data(as_text=True)

    assert "Voir les dÃ©tails techniques" not in html
    assert "ClÃ© interne" not in html
    assert "Valeur interne" not in html
    assert "Type interne" not in html


def test_panel_product_value_has_priority_over_fallback_when_available():
    custom_panel = {
        "reference": "PV-700-CUSTOM",
        "category": "panels",
        "subcategory": "monocristallin",
        "brand": "HeliAntha Pro",
        "model": "700 Wc",
        "description": "Panneau test",
        "power_w": 700,
        "sale_price": 1500,
        "unit": "piece",
        "warranty": "15 ans",
        "technical_specs": {"surface_m2": 2.8},
        "active": 1,
    }
    products = [custom_panel] + [item for item in CATALOG_PRODUCTS if item["category"] != "panels"]

    result = CalculationEngine().calculate(
        "ongrid",
        {"monthly_kwh": 600, "city": "Marrakech", "roof_area": 90},
        context={"products": products},
    )

    source = result["calculation_detail"]["resolved_sources"]["pv_panel_default_w"]
    panel_line = next(item for item in result["selected_equipment"] if item["category"] == "panels")

    assert source["source_type"] == "manufacturer"
    assert source["source_reference"] == "PV-700-CUSTOM"
    assert source["value"] == pytest.approx(700)
    assert panel_line["reference"] == "PV-700-CUSTOM"


def test_panel_fallback_value_is_used_when_no_catalog_panel_is_available():
    result = CalculationEngine().calculate(
        "ongrid",
        {"monthly_kwh": 600, "city": "Ville inconnue", "roof_area": 90},
        context={
            "products": [item for item in CATALOG_PRODUCTS if item["category"] != "panels"],
            "technical_parameters": {
                "pv_panel_default_w": {"value": 610, "display_name": "Puissance panneau de secours"},
            },
        },
    )

    source = result["calculation_detail"]["resolved_sources"]["pv_panel_default_w"]
    panel_line = next(item for item in result["selected_equipment"] if item["category"] == "panels")

    assert source["source_reference"] == "pv_panel_default_w"
    assert source["source_type"] == "heliantha"
    assert source["value"] == pytest.approx(610)
    assert panel_line["reference"] == "PV-DEFAULT"
