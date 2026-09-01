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
            "price_tax_basis": "unconfirmed",
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
                "curve_points": [
                    {"flow_m3_h": flow, "hmt_m": hmt}
                    for flow, hmt in curve_points
                ],
                "price_tax_basis": "unconfirmed",
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
            pump_product("PUMP-A", 5.5, 7000, [(5, 80)], stock=999, product_id=1),
            pump_product("PUMP-B", 5.5, 6500, [(5, 80)], stock=0, product_id=2),
        ],
        5,
        70,
    )

    assert selection["selected_pump_cv"] == pytest.approx(5.5)
    assert selection["current_price"] == pytest.approx(6500)
    assert selection["product"]["reference"] == "PUMP-B"


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
    assert pump_line["unit_price"] == pytest.approx(11000)
    assert pump_line["description"] == "Pompe solaire 7.5 CV"
    assert panel_line["quantity"] == 14
    assert panel_line["power_w"] == 590
    assert drive_line["brand"] == "VEICHI"
    assert drive_line["model"] == "7.5 kW tri"


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
    pump_line = next(item for item in payload["selected_equipment"] if item["component"] == "pump")

    with app.app_context():
        db = get_db()
        internal_reference = payload["final_results"]["selected_pump_reference_internal"]
        db.execute(
            "UPDATE products SET sale_price = sale_price + 2000 WHERE reference = ?",
            (internal_reference,),
        )
        db.commit()
        saved = json.loads(db.execute("SELECT result_json FROM quote_requests").fetchone()["result_json"])

    saved_pump_line = next(item for item in saved["selected_equipment"] if item["component"] == "pump")
    assert saved_pump_line["unit_price"] == pump_line["unit_price"]


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
