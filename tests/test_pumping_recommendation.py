import json
from pathlib import Path

import pytest

from app import create_app
from app.calculators import CalculationEngine
from app.db import get_db, load_calculation_context, save_product
from app.pump_catalog_data import (
    PUMP_COUNT,
    PUMP_CURVE_POINT_COUNT,
    PUMP_DISTINCT_POWER_HP_COUNT,
)
from app.services.pump_pricing import calculate_pump_sale_price
from app.services.pump_selector import NO_STANDARD_PUMP_MESSAGE, select_pump_for_duty


def pump_product(
    reference: str,
    power_hp: float,
    price: float,
    curve_points: list[tuple[float, float]],
    *,
    stock: int | None = None,
    active: int = 1,
    product_id: int | None = None,
    outlet_diameter: str = '2"',
) -> dict:
    return {
        "id": product_id,
        "reference": reference,
        "category": "pumps",
        "brand": "HeliAntha Test",
        "model": reference,
        "description": f"Pompe solaire {power_hp:g} CV",
        "sale_price": price,
        "currency": "DH",
        "unit": "piece",
        "active": active,
        "stock": stock,
        "technical_specs": {
            "power_hp": power_hp,
            "power_kw": round(power_hp * 0.7355, 2),
            "outlet_diameter": outlet_diameter,
            "price_tax_basis": "internal_pt",
        },
        "pump_curve_points": [
            {"flow_m3_h": flow, "hmt_m": hmt}
            for flow, hmt in curve_points
        ],
    }


def save_db_pump(
    reference: str,
    power_hp: float,
    price: float,
    curve_points: list[tuple[float, float]],
    *,
    active: bool = True,
    stock: int = 0,
    outlet_diameter: str = '2"',
) -> int:
    submitted_fields = {
        "reference": reference,
        "category": "pumps",
        "brand": "HeliAntha Test",
        "model": reference,
        "sale_price": str(price),
        "stock": str(stock),
        "unit": "piece",
        "currency": "DH",
        "active": "1" if active else "0",
        "spec_power_hp": str(power_hp),
        "spec_power_kw": str(round(power_hp * 0.7355, 2)),
        "spec_phases": "triphase",
        "spec_voltage_v": "380",
        "spec_current_a": "12",
        "spec_outlet_diameter": outlet_diameter,
        "spec_curve_points": "\n".join(f"{flow}:{hmt}" for flow, hmt in curve_points),
    }
    return save_product(
        {
            "reference": reference,
            "category": "pumps",
            "brand": "HeliAntha Test",
            "model": reference,
            "description": f"Pompe solaire {power_hp:g} CV",
            "sale_price": price,
            "stock": stock,
            "unit": "piece",
            "currency": "DH",
            "active": 1 if active else 0,
            "vat_rate": None,
            "technical_specs": {
                "power_hp": power_hp,
                "power_kw": round(power_hp * 0.7355, 2),
                "phases": "triphase",
                "voltage_v": 380,
                "current_a": 12,
                "outlet_diameter": outlet_diameter,
                "curve_points": [
                    {"flow_m3_h": flow, "hmt_m": hmt}
                    for flow, hmt in curve_points
                ],
                "price_tax_basis": "internal_pt",
            },
        },
        submitted_fields=submitted_fields,
    )


def test_interval_selection_uses_real_interval_without_interpolation():
    selection = select_pump_for_duty(
        [
            pump_product(
                "PUMP-INTERVAL",
                2,
                5000,
                [(2.0, 80.0), (2.5, 65.0)],
                stock=0,
                product_id=1,
            )
        ],
        2.3,
        65,
    )

    assert selection["selected_pump_cv"] == pytest.approx(2)
    assert selection["duty"]["interval_start_m3_h"] == pytest.approx(2.0)
    assert selection["duty"]["interval_end_m3_h"] == pytest.approx(2.5)
    assert selection["duty"]["available_hmt_m"] == pytest.approx(65.0)
    assert selection["duty"]["policy"] == "conservative_interval_no_interpolation"


def test_selector_chooses_smallest_sufficient_cv():
    selection = select_pump_for_duty(
        [
            pump_product("PUMP-5.5", 5.5, 7000, [(5, 62)], product_id=1),
            pump_product("PUMP-7.5", 7.5, 9000, [(5, 75)], product_id=2),
            pump_product("PUMP-10", 10, 12000, [(5, 105)], product_id=3),
        ],
        5,
        70,
    )

    assert selection["selected_pump_cv"] == pytest.approx(7.5)
    assert selection["product"]["reference"] == "PUMP-7.5"


def test_selector_same_cv_uses_lowest_price_and_ignores_stock():
    selection = select_pump_for_duty(
        [
            pump_product("PUMP-A", 5.5, 7000, [(5, 80)], stock=999, product_id=1, outlet_diameter='2"'),
            pump_product("PUMP-B", 5.5, 6500, [(5, 80)], stock=0, product_id=2, outlet_diameter='2" 1/2'),
        ],
        5,
        70,
    )

    assert selection["selected_pump_cv"] == pytest.approx(5.5)
    assert selection["current_price"] == pytest.approx(6500)
    assert selection["product"]["reference"] == "PUMP-B"
    assert selection["product"]["technical_specs"]["outlet_diameter"] == '2" 1/2'


def test_pump_sale_price_formula_uses_internal_pt():
    sale = calculate_pump_sale_price(11000, 0.5, 1.3, 0.20)

    assert sale["price_ttc"] == pytest.approx(7150)
    assert sale["price_ht"] == pytest.approx(5958.33)
    assert sale["vat_amount"] == pytest.approx(1191.67)


def test_db_admin_price_change_changes_choice_for_same_cv(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "pump-admin-price.db")})

    with app.app_context():
        db = get_db()
        db.execute("UPDATE products SET active = 0 WHERE category = 'pumps'")
        db.commit()
        save_db_pump("PUMP-A", 5.5, 7000, [(5, 80)], stock=100)
        save_db_pump("PUMP-B", 5.5, 6500, [(5, 80)], stock=0)

        first = select_pump_for_duty(load_calculation_context()["products"], 5, 70)
        assert first["product"]["reference"] == "PUMP-B"

        db.execute("UPDATE products SET sale_price = 6000 WHERE reference = 'PUMP-A'")
        db.commit()

        second = select_pump_for_duty(load_calculation_context()["products"], 5, 70)
        assert second["product"]["reference"] == "PUMP-A"
        assert second["current_price"] == pytest.approx(6000)


def test_inactive_pump_is_ignored_by_selector():
    selection = select_pump_for_duty(
        [
            pump_product("PUMP-INACTIVE", 5.5, 6000, [(5, 80)], active=0, product_id=1),
            pump_product("PUMP-ACTIVE", 5.5, 7000, [(5, 80)], active=1, product_id=2),
        ],
        5,
        70,
    )

    assert selection["product"]["reference"] == "PUMP-ACTIVE"


def test_pumping_without_matching_pump_returns_exact_message():
    result = CalculationEngine().calculate(
        "pumping",
        {"pump_existing": False, "flow_m3_h": 40, "hmt_m": 400},
    )

    assert result["summary"] == NO_STANDARD_PUMP_MESSAGE
    assert result["final_results"]["no_standard_pump"] is True
    assert result["final_results"]["pump_rule_mode"] == "no_standard_pump"
    assert result["final_results"]["solar_rule_defined"] is False
    assert result["selected_equipment"] == []


def test_pumping_quote_form_no_standard_pump_is_not_http_400(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "pump-no-standard-form.db")})
    client = app.test_client()

    response = client.post(
        "/api/calculate",
        json={
            "project": "pumping",
            "data": {"pump_existing": False, "flow_m3_h": 75, "hmt_m": 30},
            "contact": {"name": "Client test", "phone": "0600000000"},
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["summary"] == NO_STANDARD_PUMP_MESSAGE
    assert payload["final_results"]["no_standard_pump"] is True
    assert payload["selected_equipment"] == []


def test_pumping_without_solar_rule_keeps_selected_cv_without_rounding(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "pump-no-rule.db")})

    with app.app_context():
        result = CalculationEngine().calculate(
            "pumping",
            {"pump_existing": False, "flow_m3_h": 12, "hmt_m": 40},
        )

    assert result["final_results"]["selected_pump_cv"] == pytest.approx(4.0)
    assert result["final_results"]["solar_rule_defined"] is False
    assert [line["category"] for line in result["selected_equipment"]] == ["pumps"]
    assert "4 CV" in result["summary"]
    assert "5,5 CV" not in result["summary"]


def test_pumping_full_chain_uses_selected_cv_admin_price_and_exact_rule(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "pump-full-chain.db")})

    with app.app_context():
        result = CalculationEngine().calculate(
            "pumping",
            {"pump_existing": False, "flow_m3_h": 12, "hmt_m": 80},
        )

    pump_line = next(item for item in result["selected_equipment"] if item["component"] == "pump")
    panel_line = next(item for item in result["selected_equipment"] if item["component"] == "panel")
    drive_line = next(item for item in result["selected_equipment"] if item["component"] == "pump_drive")

    assert result["final_results"]["selected_pump_cv"] == pytest.approx(7.5)
    assert result["final_results"]["panels"] == 14
    assert result["final_results"]["panel_power_w"] == 590
    assert result["final_results"]["solar_drive_kw"] == pytest.approx(7.5)
    assert result["final_results"]["drive_brand"] == "VEICHI"
    assert result["final_results"]["selected_outlet_diameter"] == '2" 1/2'
    assert result["final_results"]["selected_pump_internal_price"] == pytest.approx(11000)
    assert result["final_results"]["pump_sale_price_ttc"] == pytest.approx(7150)
    assert result["final_results"]["pump_sale_price_ht"] == pytest.approx(5958.33)
    assert result["final_results"]["pump_sale_vat_amount"] == pytest.approx(1191.67)
    assert pump_line["unit_price"] == pytest.approx(5958.33)
    assert pump_line["vat_rate"] == pytest.approx(0.20)
    assert pump_line["technical_specs"]["outlet_diameter"] == '2" 1/2'
    assert pump_line["description"] == "Pompe solaire 7.5 CV"
    assert panel_line["quantity"] == 14
    assert panel_line["power_w"] == 590
    assert drive_line["brand"] == "VEICHI"
    assert drive_line["model"] == "7.5 kW tri"


def test_admin_pump_sale_parameters_change_client_price(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "pump-sale-params.db")})

    with app.app_context():
        db = get_db()
        db.execute(
            """UPDATE pumping_solar_rules
               SET coefficient_1 = 0.6, coefficient_2 = 1.25, vat_rate = 0.20
               WHERE rule_key = 'pump-sale-parameters'"""
        )
        db.commit()
        result = CalculationEngine().calculate(
            "pumping",
            {"pump_existing": False, "flow_m3_h": 12, "hmt_m": 80},
            context=load_calculation_context(),
        )

    pump_line = next(item for item in result["selected_equipment"] if item["component"] == "pump")
    assert result["final_results"]["pump_sale_coefficient_1"] == pytest.approx(0.6)
    assert result["final_results"]["pump_sale_coefficient_2"] == pytest.approx(1.25)
    assert result["final_results"]["pump_sale_price_ttc"] == pytest.approx(8250)
    assert pump_line["unit_price"] == pytest.approx(6875)


def test_admin_pt_change_changes_pump_client_price_without_solar_rule(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "pump-pt-change.db")})

    with app.app_context():
        db = get_db()
        db.execute("UPDATE products SET active = 0 WHERE category = 'pumps'")
        save_db_pump("PUMP-PT", 4, 10000, [(5, 80)], outlet_diameter='3"')
        first = CalculationEngine().calculate(
            "pumping",
            {"pump_existing": False, "flow_m3_h": 5, "hmt_m": 70},
            context=load_calculation_context(),
        )
        db.execute("UPDATE products SET sale_price = 12000 WHERE reference = 'PUMP-PT'")
        db.commit()
        second = CalculationEngine().calculate(
            "pumping",
            {"pump_existing": False, "flow_m3_h": 5, "hmt_m": 70},
            context=load_calculation_context(),
        )

    first_pump = next(item for item in first["selected_equipment"] if item["component"] == "pump")
    second_pump = next(item for item in second["selected_equipment"] if item["component"] == "pump")
    assert first["final_results"]["selected_pump_internal_price"] == pytest.approx(10000)
    assert first_pump["unit_price"] == pytest.approx(5416.67)
    assert second["final_results"]["selected_pump_internal_price"] == pytest.approx(12000)
    assert second["final_results"]["selected_outlet_diameter"] == '3"'
    assert second_pump["unit_price"] == pytest.approx(6500)


def test_pumping_vat_policy_uses_10_for_panels_transport_and_20_for_rest(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "pump-vat.db")})

    with app.app_context():
        result = CalculationEngine().calculate(
            "pumping",
            {"pump_existing": False, "flow_m3_h": 12, "hmt_m": 80},
        )

    pump_line = next(item for item in result["selected_equipment"] if item["component"] == "pump")
    panel_line = next(item for item in result["selected_equipment"] if item["component"] == "panel")
    drive_line = next(item for item in result["selected_equipment"] if item["component"] == "pump_drive")
    expected_vat = round(
        sum(round(float(line["total_price"]) * float(line["vat_rate"]), 2) for line in result["selected_equipment"]),
        2,
    )

    assert panel_line["vat_rate"] == pytest.approx(0.10)
    assert pump_line["vat_rate"] == pytest.approx(0.20)
    assert drive_line["vat_rate"] == pytest.approx(0.20)
    assert result["financial_breakdown"]["vat"] == pytest.approx(expected_vat)
    assert result["final_results"]["pump_sale_vat_amount"] == pytest.approx(1191.67)

    from app.services.pricing import PricingEngine as BomPricingEngine

    class DummyContext:
        pricing = {}

        @staticmethod
        def r(_key, default=0):
            return default

    transport = BomPricingEngine().breakdown(
        "pumping",
        [{"category": "transport", "financial_category": "transport", "total_price": 1000, "price_status": "rule_price"}],
        DummyContext(),
    )
    assert transport["vat"] == pytest.approx(100)


def test_public_pumping_payload_hides_internal_pump_fields(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "pump-public-safe.db")})
    client = app.test_client()
    response = client.post(
        "/api/calculate",
        json={
            "project": "pumping",
            "data": {"pump_existing": False, "flow_m3_h": 12, "hmt_m": 80},
            "contact": {"name": "Client test", "phone": "0600000000"},
        },
    )
    assert response.status_code == 200
    api_payload = response.get_json()

    with app.app_context():
        from app.db import get_quote_by_number, list_company_settings
        from app.public_presenters import build_public_quote_payload, company_profile

        quote = get_quote_by_number(api_payload["quote_number"])
        public_payload = build_public_quote_payload(quote, company_profile(list_company_settings()))

    for payload in (api_payload, public_payload):
        blob = json.dumps(payload)
        assert payload["final_results"]["selected_outlet_diameter"] == '2" 1/2'
        assert "selected_pump_id" not in blob
        assert "selected_pump_reference_internal" not in blob
        assert "selected_pump_internal_price" not in blob
        assert "pump_sale_coefficient" not in blob
        assert "internal_price_pt" not in blob
        assert "product_snapshot" not in blob
        assert "HEL-PUMP-" not in blob


def test_existing_pump_mode_is_preserved():
    result = CalculationEngine().calculate(
        "pumping",
        {"pump_existing": True, "existing_pump_cv": 15},
    )

    assert result["final_results"]["pump_existing"] is True
    assert result["final_results"]["pump_rule_mode"] == "existing_pump_cv"
    assert "selected_pump_id" not in result["final_results"]


def test_pump_seed_counts_and_admin_price_survives_restart(tmp_path):
    database = tmp_path / "pump-seed.db"
    app = create_app({"TESTING": True, "DATABASE": str(database)})

    with app.app_context():
        db = get_db()
        pump_count = db.execute("SELECT COUNT(*) FROM products WHERE category = 'pumps'").fetchone()[0]
        point_count = db.execute("SELECT COUNT(*) FROM pump_curve_points").fetchone()[0]
        distinct_cv = {
            float((product.get("technical_specs") or {}).get("power_hp"))
            for product in load_calculation_context()["products"]
            if product.get("category") == "pumps"
        }
        assert pump_count == PUMP_COUNT
        assert point_count == PUMP_CURVE_POINT_COUNT
        assert len(distinct_cv) == PUMP_DISTINCT_POWER_HP_COUNT

        reference = db.execute(
            "SELECT reference FROM products WHERE category = 'pumps' AND model = 'R95-ST8-36T'"
        ).fetchone()["reference"]
        db.execute("UPDATE products SET sale_price = 8200 WHERE reference = ?", (reference,))
        db.execute("DELETE FROM pump_curve_points")
        db.commit()

    restarted_app = create_app({"TESTING": True, "DATABASE": str(database)})
    with restarted_app.app_context():
        db = get_db()
        price = db.execute("SELECT sale_price FROM products WHERE reference = ?", (reference,)).fetchone()[0]
        point_count = db.execute("SELECT COUNT(1) FROM pump_curve_points").fetchone()[0]
        assert float(price) == pytest.approx(8200)
        assert point_count == PUMP_CURVE_POINT_COUNT


def test_saved_quote_keeps_pump_snapshot_after_admin_price_change(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "pump-snapshot.db")})
    client = app.test_client()

    response = client.post(
        "/api/calculate",
        json={
            "project": "pumping",
            "data": {"pump_existing": False, "flow_m3_h": 12, "hmt_m": 80},
            "contact": {"name": "Client test", "phone": "0600000000"},
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    public_blob = json.dumps(payload)
    assert "selected_pump_reference_internal" not in payload["final_results"]
    assert "selected_pump_id" not in payload["final_results"]
    assert "selected_pump_internal_price" not in payload["final_results"]
    assert "pump_sale_coefficient" not in public_blob
    assert "internal_price_pt" not in public_blob
    assert "product_snapshot" not in public_blob
    assert "HEL-PUMP-" not in public_blob

    with app.app_context():
        db = get_db()
        saved = json.loads(db.execute("SELECT result_json FROM quote_requests").fetchone()["result_json"])
        internal_reference = saved["final_results"]["selected_pump_reference_internal"]
        saved_pump_line = next(item for item in saved["selected_equipment"] if item["component"] == "pump")
        db.execute(
            "UPDATE products SET sale_price = sale_price + 2000 WHERE reference = ?",
            (internal_reference,),
        )
        db.commit()
        saved_after = json.loads(db.execute("SELECT result_json FROM quote_requests").fetchone()["result_json"])

    saved_after_pump_line = next(item for item in saved_after["selected_equipment"] if item["component"] == "pump")
    assert saved_after["final_results"]["selected_pump_internal_price"] == pytest.approx(11000)
    assert saved_after_pump_line["unit_price"] == saved_pump_line["unit_price"]


def test_pumping_quote_form_accepts_french_decimal_numbers(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "pump-form.db")})
    client = app.test_client()

    response = client.post(
        "/api/calculate",
        json={
            "project": "pumping",
            "data": {"pump_existing": False, "flow_m3_h": "12,0", "hmt_m": "80,0"},
            "contact": {"name": "Client test", "phone": "0600000000"},
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["final_results"]["selected_pump_cv"] == pytest.approx(7.5)
    assert payload["final_results"]["flow_m3_h"] == pytest.approx(12)
    assert payload["final_results"]["hmt_m"] == pytest.approx(80)
