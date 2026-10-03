import pytest

from app import create_app
from app.calculators import CalculationEngine
from app.db import load_calculation_context


def calculate(data, context=None):
    return CalculationEngine().calculate("hybrid", data, context=context)


def line(result, component):
    return next(item for item in result["selected_equipment"] if item["component"] == component)


def test_hybrid_tier_1_450_kwh(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "hybrid-tier-1.db")})
    with app.app_context():
        result = calculate({"monthly_consumption_kwh": 450}, context=load_calculation_context())

    final = result["final_results"]
    assert final["hybrid_tier"] == 1
    assert final["phase"] == "monophase"
    assert final["voltage_v"] == 220
    assert final["panel_count"] == 8
    assert final["panel_power_w"] == 585
    assert final["installed_power_kwp"] == pytest.approx(4.68)
    assert final["inverter_brand"] == "Deye"
    assert final["inverter_power_kw"] == pytest.approx(6)
    assert final["battery_count"] == 2
    assert final["battery_unit_capacity_kwh"] == pytest.approx(5)
    assert final["battery_total_capacity_kwh"] == pytest.approx(10)
    assert "2x Batterie Lithium 5 kWh - Total 10 kWh" == final["battery_label"]


def test_hybrid_tier_2_1000_kwh(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "hybrid-tier-2.db")})
    with app.app_context():
        result = calculate({"monthly_consumption_kwh": 1000}, context=load_calculation_context())

    final = result["final_results"]
    assert final["hybrid_tier"] == 2
    assert final["panel_count"] == 16
    assert final["panel_power_w"] == 585
    assert final["installed_power_kwp"] == pytest.approx(9.36)
    assert final["inverter_power_kw"] == pytest.approx(10)
    assert final["battery_count"] == 1
    assert final["battery_unit_capacity_kwh"] == pytest.approx(15)
    assert final["battery_total_capacity_kwh"] == pytest.approx(15)


def test_hybrid_tier_3_1800_kwh(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "hybrid-tier-3.db")})
    with app.app_context():
        result = calculate({"monthly_consumption_kwh": 1800}, context=load_calculation_context())

    final = result["final_results"]
    assert final["hybrid_tier"] == 3
    assert final["panel_count"] == 24
    assert final["panel_power_w"] in {725, 720}
    assert final["installed_power_kwp"] == pytest.approx(24 * final["panel_power_w"] / 1000)
    assert final["inverter_power_kw"] == pytest.approx(18)
    assert final["battery_count"] == 2
    assert final["battery_unit_capacity_kwh"] == pytest.approx(15)
    assert final["battery_total_capacity_kwh"] == pytest.approx(30)


def test_hybrid_tier_3_uses_720w_fallback_when_725w_is_unavailable(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "hybrid-fallback-720.db")})
    with app.app_context():
        context = load_calculation_context()
        context["products"] = [
            product
            for product in context["products"]
            if not (product.get("category") == "panels" and int(product.get("power_w") or 0) == 725)
        ]
        result = calculate({"monthly_consumption_kwh": 1800}, context=context)

    assert result["final_results"]["panel_count"] == 24
    assert result["final_results"]["panel_power_w"] == 720


def test_hybrid_ancillary_pricing_and_vat_follow_ongrid_rules(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "hybrid-vat.db")})
    with app.app_context():
        result = calculate({"monthly_consumption_kwh": 450}, context=load_calculation_context())

    assert line(result, "structure")["total_price"] == pytest.approx(8 * 200)
    assert line(result, "protection_acdc")["total_price"] == pytest.approx(8 * 130)
    assert line(result, "cabling_acdc")["total_price"] == pytest.approx(8 * 80)
    assert line(result, "installation")["total_price"] == pytest.approx(8 * 200)
    assert line(result, "transport")["total_price"] == pytest.approx(8 * 50)

    assert line(result, "panel")["vat_rate"] == pytest.approx(0.10)
    assert line(result, "transport")["vat_rate"] == pytest.approx(0.10)
    for component in ("inverter", "battery", "structure", "protection_acdc", "cabling_acdc", "installation"):
        assert line(result, component)["vat_rate"] == pytest.approx(0.20)

    expected_vat = round(
        sum(round(float(item["total_price"]) * float(item["vat_rate"]), 2) for item in result["selected_equipment"]),
        2,
    )
    assert result["financial_breakdown"]["vat"] == pytest.approx(expected_vat)


def test_hybrid_api_route_is_available(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "hybrid-api.db")})
    client = app.test_client()

    response = client.post(
        "/api/calculate",
        json={
            "project": "hybrid",
            "project_type": "hybrid",
            "data": {"monthly_consumption_kwh": 450},
            "contact": {"name": "Client Hybride", "phone": "0600000000"},
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["project"] == "hybrid"
    assert payload["final_results"]["battery_total_capacity_kwh"] == pytest.approx(10)
    assert "public_url" in payload
