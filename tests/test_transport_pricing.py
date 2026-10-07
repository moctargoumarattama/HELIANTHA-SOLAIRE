from decimal import Decimal

from bs4 import BeautifulSoup
from flask import render_template
import pytest

from app import create_app
from app.calculators import CalculationEngine
from app.db import (
    ensure_schema, get_db, get_quote, invalidate_calculation_context,
    list_company_settings, load_calculation_context, update_company_settings,
    update_ongrid_parameters,
)
from app.routes import _display_equipment_lines
from app.tax import line_vat_amount, money
from app.transport import (
    TRANSPORT_DESCRIPTION, TransportValidationError, transport_rate,
    validate_transport_setting,
)


PUMP_DATA = {"pump_existing": True, "existing_pump_cv": 3}


def transport_line(result):
    lines = [line for line in result["selected_equipment"] if line["component"] == "transport"]
    assert len(lines) == 1
    return lines[0]


def assert_totals(result):
    financial = result["financial_breakdown"]
    lines = result["selected_equipment"]
    assert money(financial["total_ht"]) == sum(money(line["total_price"]) for line in lines)
    assert money(financial["vat"]) == sum(line_vat_amount(line) for line in lines)
    assert money(financial["total_ttc"]) == money(financial["total_ht"]) + money(financial["vat"])


def test_pumping_transport_for_twelve_panels_includes_central_vat_and_totals():
    result = CalculationEngine().calculate("pumping", PUMP_DATA, context={
        "company_settings": {"transport_pumping_rate": {"value": "75"}},
    })
    line = transport_line(result)
    assert line["description"] == TRANSPORT_DESCRIPTION
    assert line["quantity"] == 12
    assert line["total_price"] == 900
    assert line["vat_rate"] == .10
    assert line_vat_amount(line) == Decimal("90.00")
    assert result["final_results"]["transport_ttc"] == 990
    assert_totals(result)


def test_pumping_missing_tariff_uses_nonzero_fallback_and_saved_zero_is_respected():
    result = CalculationEngine().calculate("pumping", PUMP_DATA)
    assert transport_line(result)["unit_price"] == 60
    assert transport_line(result)["total_price"] == 720
    free = CalculationEngine().calculate("pumping", PUMP_DATA, context={
        "company_settings": {"transport_pumping_rate": "0"},
    })
    assert transport_line(free)["total_price"] == 0
    assert transport_line(free)["price_status"] == "rule_price"
    assert_totals(free)


def test_pumping_transport_uses_its_own_updated_vat_and_decimal_rounding():
    result = CalculationEngine().calculate("pumping", PUMP_DATA, context={
        "company_settings": {"transport_pumping_rate": "60.015"},
        "vat_rates": {"pumping_transport": {"value": "12.5"}},
    })
    line = transport_line(result)
    assert line["unit_price"] == 60.02
    assert line["total_price"] == 720.24
    assert line_vat_amount(line) == Decimal("90.03")
    assert result["final_results"]["transport_ttc"] == 810.27
    assert_totals(result)


@pytest.mark.parametrize("raw", ["-1", "-0.001", "NaN", "Infinity", "abc", "", "1e1000"])
def test_transport_rate_validation_rejects_invalid_amounts(raw):
    with pytest.raises(TransportValidationError):
        validate_transport_setting("transport_pumping_rate", raw)


def test_transport_legacy_and_invalid_context_fallback():
    assert transport_rate({"ongrid_parameters": {"transport_per_pv": {"value": "42,50"}}}, "hybrid") == Decimal("42.50")
    assert transport_rate({"company_settings": {"transport_pumping_rate": "invalid"}}, "pumping") == 60
    with pytest.raises(TransportValidationError):
        validate_transport_setting("transport_pumping_mode", "unknown")


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    return create_app({
        "TESTING": True, "WTF_CSRF_ENABLED": True,
        "DATABASE": str(tmp_path_factory.mktemp("transport") / "transport.db"),
    })


@pytest.fixture
def client(app):
    with app.app_context():
        db = get_db()
        settings = [tuple(row) for row in db.execute("SELECT key, value FROM company_settings")]
        legacy = db.execute("SELECT value FROM ongrid_parameters WHERE key = 'transport_per_pv'").fetchone()[0]
    client = app.test_client()
    with client.session_transaction() as session:
        session["admin_user"] = "direction@heliantha.ma"
    yield client
    with app.app_context():
        db = get_db()
        db.executemany("UPDATE company_settings SET value = ? WHERE key = ?", [(value, key) for key, value in settings])
        db.execute("UPDATE ongrid_parameters SET value = ? WHERE key = 'transport_per_pv'", (legacy,))
        db.commit()
        invalidate_calculation_context()


def settings_fields(app, client):
    response = client.get("/admin/parametres")
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, "html.parser")
    with app.app_context():
        ids = {row["key"]: f"value_{row['id']}" for row in list_company_settings()}
    return ids, soup.select_one('form.panel input[name="csrf_token"]')["value"]


def test_admin_tariffs_update_immediately_and_stored_quote_keeps_previous_tariff(app, client):
    ids, token = settings_fields(app, client)
    assert client.post("/admin/parametres", data={ids["transport_pumping_rate"]: "50", "csrf_token": token}).status_code == 302
    first = client.post("/api/calculate", json={"project": "pumping", "data": PUMP_DATA})
    assert first.status_code == 200
    first = first.get_json()
    assert transport_line(first)["total_price_ht"] == 600
    response = client.post("/admin/parametres", data={ids["transport_pumping_rate"]: "75", "csrf_token": token}, follow_redirects=True)
    assert response.status_code == 200
    assert "enregistrés avec succès" in response.get_data(as_text=True)
    second = client.post("/api/calculate", json={"project": "pumping", "data": PUMP_DATA})
    assert second.status_code == 200
    second = second.get_json()
    assert transport_line(second)["total_price_ht"] == 900
    with app.app_context():
        old_quote = get_quote(first["quote_id"])
        assert transport_line(old_quote)["total_price"] == 600
    assert money(first["financial_breakdown"]["total_ttc"]) + Decimal("330.00") == money(second["financial_breakdown"]["total_ttc"])


@pytest.mark.parametrize("raw", ["-1", "NaN", "abc"])
def test_admin_invalid_tariff_is_atomic_and_preserves_other_settings(app, client, raw):
    ids, token = settings_fields(app, client)
    with app.app_context():
        previous = {row["key"]: row["value"] for row in list_company_settings()}
    response = client.post("/admin/parametres", data={
        ids["transport_pumping_rate"]: raw, ids["company_name"]: "Should not be saved", "csrf_token": token,
    })
    assert response.status_code == 400
    with app.app_context():
        assert {row["key"]: row["value"] for row in list_company_settings()} == previous


def test_admin_transport_csrf_and_single_settings_block(app, client):
    ids, _ = settings_fields(app, client)
    response = client.post("/admin/parametres", data={ids["transport_pumping_rate"]: "75"})
    assert response.status_code == 400
    soup = BeautifulSoup(client.get("/admin/parametres").data, "html.parser")
    assert len(soup.select("#transport-heading")) == 1
    for key in ("transport_ongrid_rate", "transport_pumping_rate"):
        fields = soup.select(f'input[name="{ids[key]}"]')
        assert len(fields) == 1 and fields[0]["min"] == "0"


def test_ongrid_and_hybrid_tariffs_are_independent_from_pumping(app, client):
    with app.app_context():
        update_company_settings({"transport_ongrid_rate": "37.50", "transport_pumping_rate": "75"})
        context = load_calculation_context()
    for project in ("photovoltaic", "hybrid"):
        result = CalculationEngine().calculate(project, {"monthly_consumption_kwh": 600, "phase": "monophase"}, context=context)
        line = transport_line(result)
        assert line["unit_price"] == 37.50
        assert money(line["total_price"]) == money(Decimal(str(line["quantity"])) * Decimal("37.50"))
        assert line["vat_rate"] == .10
        assert_totals(result)
    assert transport_line(CalculationEngine().calculate("pumping", PUMP_DATA, context=context))["unit_price"] == 75


def test_legacy_admin_ongrid_tariff_updates_canonical_setting(app, client):
    with app.app_context():
        update_ongrid_parameters({"transport_per_pv": "42.50"})
        assert transport_rate(load_calculation_context(), "photovoltaic") == Decimal("42.50")
        with pytest.raises(TransportValidationError):
            update_ongrid_parameters({"transport_per_pv": "-1"})


def test_transport_migration_preserves_custom_legacy_rate(app, client):
    with app.app_context():
        db = get_db()
        db.execute("DELETE FROM company_settings WHERE category = 'transport'")
        db.execute("UPDATE ongrid_parameters SET value = '61.25' WHERE key = 'transport_per_pv'")
        db.commit()
        ensure_schema(db)
        settings = {row["key"]: row["value"] for row in list_company_settings()}
        assert settings["transport_ongrid_rate"] == "61.25"
        assert settings["transport_pumping_rate"] == "60.00"
        assert settings["transport_pumping_mode"] == "per_panel"


def test_transport_is_rendered_in_admin_html_template_and_binary_pdf(app, client):
    response = client.post("/api/calculate", json={"project": "pumping", "data": PUMP_DATA})
    assert response.status_code == 200
    result = response.get_json()
    detail = client.get(f"/admin/devis/{result['quote_id']}")
    assert detail.status_code == 200
    assert TRANSPORT_DESCRIPTION in detail.get_data(as_text=True)
    pdf = client.get(f"/admin/devis/{result['quote_id']}/pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF-")
    assert b"Transport, livraison et logistique sur" in pdf.data
    assert b"site" in pdf.data
    with app.test_request_context():
        quote = get_quote(result["quote_id"])
        html = render_template("admin/quote_pdf.html", quote=quote, company={},
                               display_equipment_lines=_display_equipment_lines(quote["selected_equipment"]))
        soup = BeautifulSoup(html, "html.parser")
        row = next(row for row in soup.select("tbody tr") if TRANSPORT_DESCRIPTION in row.get_text())
        text = row.get_text(" ", strip=True)
        assert "10 %" in text and "720,00" in text and "792,00" in text


def test_undefined_pumping_configuration_does_not_invent_panel_transport():
    result = CalculationEngine().calculate("pumping", {"pump_existing": False, "flow_m3_h": 40, "hmt_m": 400})
    assert not result["selected_equipment"]
