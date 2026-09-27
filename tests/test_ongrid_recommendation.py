import pytest

from app import create_app
from app.calculators import CalculationEngine
from app.db import get_db, load_calculation_context, update_ongrid_parameters


def calculate(data, context=None):
    return CalculationEngine().calculate("photovoltaic", data, context=context)


def line(result, component):
    return next(item for item in result["selected_equipment"] if item["component"] == component)


def test_ongrid_boss_reference_case_1000_kwh_monophase(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "ongrid-boss.db")})
    with app.app_context():
        result = calculate(
            {
                "meter_type": "numerique",
                "phase": "monophase",
                "monthly_consumption_kwh": 1000,
            },
            context=load_calculation_context(),
        )

    final = result["final_results"]
    assert final["target_kwp"] == pytest.approx(6.67)
    assert final["panel_power_w"] == 590
    assert final["raw_panel_count"] == pytest.approx(11.30)
    assert final["panel_count"] == 14
    assert final["string_count"] == 2
    assert final["string_layout"] == [7, 7]
    assert final["installed_power_kwp"] == pytest.approx(8.26)
    assert final["inverter_power_kw"] >= 8.26

    assert line(result, "protection_acdc")["total_price"] == pytest.approx(1820)
    assert line(result, "protection_acdc")["vat_rate"] == pytest.approx(0.20)
    assert line(result, "cabling_acdc")["total_price"] == pytest.approx(1120)
    assert line(result, "injection_limiter")["total_price"] == pytest.approx(2000)
    assert line(result, "installation")["total_price"] == pytest.approx(2800)
    assert line(result, "transport")["total_price"] == pytest.approx(700)
    assert line(result, "transport")["vat_rate"] == pytest.approx(0.10)


@pytest.mark.parametrize(
    ("phase", "monthly", "expected_panel"),
    [
        ("monophase", 500, 400),
        ("monophase", 1000, 590),
        ("monophase", 1500, 630),
        ("triphase", 800, 400),
        ("triphase", 2000, 590),
        ("triphase", 3500, 630),
        ("triphase", 6500, 715),
    ],
)
def test_ongrid_panel_power_thresholds(tmp_path, phase, monthly, expected_panel):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / f"ongrid-threshold-{phase}-{monthly}.db")})
    with app.app_context():
        result = calculate(
            {"meter_type": "numerique", "phase": phase, "monthly_consumption_kwh": monthly},
            context=load_calculation_context(),
        )

    assert result["final_results"]["panel_power_w"] == expected_panel


def test_ongrid_triphasic_injection_limiter_tiers(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "ongrid-limiter.db")})
    with app.app_context():
        low = calculate(
            {"meter_type": "numerique", "phase": "triphase", "monthly_consumption_kwh": 2000},
            context=load_calculation_context(),
        )
        high = calculate(
            {"meter_type": "numerique", "phase": "triphase", "monthly_consumption_kwh": 6500},
            context=load_calculation_context(),
        )

    assert low["final_results"]["installed_power_kwp"] <= 20
    assert line(low, "injection_limiter")["total_price"] == pytest.approx(3000)
    assert high["final_results"]["installed_power_kwp"] > 20
    assert line(high, "injection_limiter")["total_price"] == pytest.approx(7000)


def test_ongrid_admin_parameter_change_is_immediate(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "ongrid-admin.db")})
    with app.app_context():
        update_ongrid_parameters({"protection_acdc_per_pv": "160"}, changed_by="test")
        result = calculate(
            {"meter_type": "numerique", "phase": "monophase", "monthly_consumption_kwh": 1000},
            context=load_calculation_context(),
        )

    assert result["final_results"]["panel_count"] == 14
    assert line(result, "protection_acdc")["unit_price"] == pytest.approx(160)
    assert line(result, "protection_acdc")["total_price"] == pytest.approx(2240)


def test_ongrid_strict_vat_policy(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "ongrid-vat.db")})
    with app.app_context():
        result = calculate(
            {"meter_type": "mecanique", "phase": "monophase", "monthly_consumption_kwh": 1000},
            context=load_calculation_context(),
        )

    assert line(result, "panel")["vat_rate"] == pytest.approx(0.10)
    assert line(result, "transport")["vat_rate"] == pytest.approx(0.10)
    for component in ("inverter", "structure", "protection_acdc", "cabling_acdc", "injection_limiter", "installation"):
        assert line(result, component)["vat_rate"] == pytest.approx(0.20)


def test_ongrid_api_and_admin_page_are_available(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "ongrid-api.db")})
    client = app.test_client()

    response = client.post(
        "/api/calculate",
        json={
            "project": "photovoltaic",
            "project_type": "photovoltaic",
            "data": {"meter_type": "numerique", "phase": "monophase", "monthly_consumption_kwh": 1000},
            "contact": {"name": "Client OnGrid", "phone": "0600000000"},
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["project"] == "photovoltaic"
    assert payload["final_results"]["panel_count"] == 14
    assert "public_url" in payload

    with client.session_transaction() as session:
        session["admin_user"] = "direction@heliantha.ma"
    admin_response = client.get("/admin/regles-ongrid")
    assert admin_response.status_code == 200
    assert b"protection_acdc_per_pv" in admin_response.data


def test_ongrid_seed_does_not_overwrite_admin_values(tmp_path):
    database = tmp_path / "ongrid-seed.db"
    app = create_app({"TESTING": True, "DATABASE": str(database)})
    with app.app_context():
        db = get_db()
        db.execute("UPDATE ongrid_parameters SET value = '177' WHERE key = 'protection_acdc_per_pv'")
        db.commit()

    restarted = create_app({"TESTING": True, "DATABASE": str(database)})
    with restarted.app_context():
        db = get_db()
        value = db.execute("SELECT value FROM ongrid_parameters WHERE key = 'protection_acdc_per_pv'").fetchone()[0]

    assert value == "177"
