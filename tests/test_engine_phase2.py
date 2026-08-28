import json
from math import ceil

import pytest

from app import create_app
from app.calculators import CalculationEngine
from app.defaults import CATALOG_PRODUCTS
from app.parameter_views import enrich_parameter


def test_offgrid_pv_losses_no_longer_change_pv_sizing():
    engine = CalculationEngine()
    payload = {"daily_kwh": 10, "peak_kw": 3, "city": "Marrakech"}

    base = engine.calculate(
        "offgrid",
        payload,
        context={"technical_parameters": {"pv_losses": {"value": 0.00}}},
    )
    changed = engine.calculate(
        "offgrid",
        payload,
        context={"technical_parameters": {"pv_losses": {"value": 0.45}}},
    )

    assert base["final_results"]["pv_theoretical_kwp"] == pytest.approx(changed["final_results"]["pv_theoretical_kwp"])
    assert base["final_results"]["pv_power_kwp"] == pytest.approx(changed["final_results"]["pv_power_kwp"])
    assert "pv_losses" not in base["calculation_detail"]["parameters_used"]
    assert "pv_losses" not in base["calculation_detail"]["resolved_sources"]
    assert base["final_results"]["pv_loss_method"] == "performance_ratio_only"


def test_pv_safety_margin_increases_target_power():
    result = CalculationEngine().calculate(
        "offgrid",
        {"daily_kwh": 10, "peak_kw": 3, "city": "Marrakech"},
        context={"technical_parameters": {"pv_safety_margin": {"value": 0.20}}},
    )

    final = result["final_results"]
    assert final["pv_target_kwp"] == pytest.approx(final["pv_theoretical_kwp"] * 1.20)


def test_panel_count_is_rounded_up_from_theoretical_count():
    custom_panel = {
        "reference": "PV-1000-TEST",
        "category": "panels",
        "subcategory": "mono",
        "brand": "Test",
        "model": "1000 Wc",
        "power_w": 1000,
        "sale_price": 1000,
        "unit": "piece",
        "technical_specs": {"surface_m2": 2.0},
        "active": 1,
    }
    products = [custom_panel] + [item for item in CATALOG_PRODUCTS if item["category"] != "panels"]
    result = CalculationEngine().calculate(
        "ongrid",
        {"monthly_kwh": 410, "city": "Marrakech", "roof_area": 100},
        context={
            "products": products,
            "technical_parameters": {
                "pv_performance_ratio": {"value": 1.0},
                "pv_safety_margin": {"value": 0.0},
            },
        },
    )

    final = result["final_results"]
    assert final["panels"] == ceil(final["panel_count_theoretical"])
    assert final["panels"] >= final["panel_count_theoretical"]


def test_hybrid_no_longer_double_counts_pv_losses():
    engine = CalculationEngine()
    payload = {"daily_kwh": 9, "peak_kw": 3, "city": "Agadir"}

    base = engine.calculate(
        "hybrid",
        payload,
        context={"technical_parameters": {"pv_losses": {"value": 0.00}}},
    )
    changed = engine.calculate(
        "hybrid",
        payload,
        context={"technical_parameters": {"pv_losses": {"value": 0.35}}},
    )

    assert base["final_results"]["pv_theoretical_kwp"] == pytest.approx(changed["final_results"]["pv_theoretical_kwp"])
    assert base["final_results"]["pv_power_kwp"] == pytest.approx(changed["final_results"]["pv_power_kwp"])


def test_ev_safety_factor_warns_when_available_power_is_below_recommended_margin():
    result = CalculationEngine().calculate(
        "ev",
        {
            "available_power": 11,
            "charger_power": 11,
            "vehicle_battery": 60,
            "vehicle_ac_max": 22,
            "phases": "triphase",
        },
    )

    codes = {item["code"] for item in result["warnings"]}
    assert "EV_SAFETY_MARGIN_LOW" in codes
    assert result["final_results"]["recommended_available_power_kw"] == pytest.approx(12.1)


def test_quote_snapshot_keeps_phase2_fields_after_parameter_change(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "phase2-snapshot.db")})
    client = app.test_client()
    response = client.post(
        "/api/calculate",
        json={"project": "offgrid", "data": {"daily_kwh": 10, "peak_kw": 3, "city": "Rabat"}},
    )
    assert response.status_code == 200

    with app.app_context():
        from app.db import get_db

        db = get_db()
        before = json.loads(db.execute("SELECT calculation_detail_json FROM quote_requests").fetchone()["calculation_detail_json"])
        db.execute("UPDATE calculation_parameters SET value = ? WHERE key = 'pv_safety_margin'", (0.30,))
        db.commit()
        after = json.loads(db.execute("SELECT calculation_detail_json FROM quote_requests").fetchone()["calculation_detail_json"])

    assert before["final_results"]["pv_target_kwp"] == after["final_results"]["pv_target_kwp"]
    assert before["calculation_blocks"] == after["calculation_blocks"]


def test_psh_and_panel_sources_are_saved_in_quote_detail():
    custom_panel = {
        "reference": "PV-700-SOURCE",
        "category": "panels",
        "subcategory": "monocristallin",
        "brand": "HeliAntha Pro",
        "model": "700 Wc",
        "power_w": 700,
        "sale_price": 1500,
        "unit": "piece",
        "technical_specs": {"surface_m2": 2.8},
        "active": 1,
    }
    products = [custom_panel] + [item for item in CATALOG_PRODUCTS if item["category"] != "panels"]
    result = CalculationEngine().calculate(
        "ongrid",
        {"monthly_kwh": 600, "city": "Marrakech", "roof_area": 90},
        context={"products": products},
    )

    sources = result["calculation_detail"]["resolved_sources"]
    assert sources["productible_default_psh"]["source_type"] == "local_data"
    assert sources["pv_panel_default_w"]["source_type"] == "manufacturer"
    assert sources["pv_panel_default_w"]["source_reference"] == "PV-700-SOURCE"


def test_phase2_calculation_blocks_show_consistent_units():
    result = CalculationEngine().calculate(
        "offgrid",
        {"daily_kwh": 8, "peak_kw": 3, "city": "Agadir"},
    )

    blocks = {block["title"]: block["items"] for block in result["calculation_detail"]["calculation_blocks"]}
    local_items = {item["label"]: item["value"] for item in blocks["Données locales"]}
    pv_items = {item["label"]: item["value"] for item in blocks["Calcul photovoltaïque"]}
    battery_items = {item["label"]: item["value"] for item in blocks["Calcul batterie"]}
    inverter_items = {item["label"]: item["value"] for item in blocks["Calcul onduleur"]}

    assert local_items["Performance globale PV"].endswith("%")
    assert pv_items["Puissance PV théorique"].endswith("kWp")
    assert pv_items["Puissance PV cible"].endswith("kWp")
    assert battery_items["Capacité théorique"].endswith("kWh")
    assert inverter_items["Puissance minimale onduleur"].endswith("kW")


def test_admin_usage_status_marks_non_used_parameters_honestly():
    param = enrich_parameter({
        "key": "pv_losses",
        "name": "Pertes PV",
        "display_kind": "percent",
        "value": 0.15,
        "unit": "ratio",
        "category": "Photovoltaique",
        "source_type": "heliantha",
        "editable": 1,
        "active": 1,
    })

    assert param["engine_usage_status"] == "unused"
    assert "Non utilise actuellement" in param["engine_usage_badge"]
