"""Regression coverage for the shared, editable residential and pumping VAT profiles."""

from decimal import Decimal, ROUND_HALF_UP
from html.parser import HTMLParser

import pytest
from werkzeug.datastructures import MultiDict

from app import create_app
from app.calculators import CalculationEngine
from app.db import (
    get_db,
    init_db,
    list_vat_rates,
    load_calculation_context,
    save_quote,
    update_vat_rates,
)
from app.tax import TaxValidationError, get_vat_rates, vat_rate_for_component


GROUPS = ("panels", "equipment", "accessories", "transport", "installation")
VAT_KEYS = tuple(f"{profile}_{group}" for profile in ("residential", "pumping") for group in GROUPS)
CENT = Decimal("0.01")
ON_GRID = {"meter_type": "numerique", "phase": "monophase", "monthly_consumption_kwh": 1000}
HYBRID = {"monthly_consumption_kwh": 450}
EXISTING_PUMP = {"pump_existing": True, "existing_pump_cv": 2}
NEW_PUMP = {"pump_existing": False, "flow_m3_h": 12, "hmt_m": 80}


class InputReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inputs = {}

    def handle_starttag(self, tag, attrs):
        if tag == "input":
            attrs = dict(attrs)
            if attrs.get("name"):
                self.inputs[attrs["name"]] = attrs


def percentages(value="10"):
    return {key: value for key in VAT_KEYS}


def stored_percentages():
    return {row["key"]: Decimal(str(row["value"])) for row in list_vat_rates()}


def decimal(value):
    return Decimal(str(value))


def assert_financial_sum(result):
    financial = result["financial_breakdown"]
    rows = financial.get("vat_breakdown") or []
    assert rows, "The financial summary must preserve the taxed line breakdown."
    vat = sum((decimal(row["vat"]) for row in rows), Decimal("0"))
    assert decimal(financial["vat"]) == vat
    assert decimal(financial["total_ttc"]) == decimal(financial["total_ht"]) + vat


@pytest.fixture
def app(tmp_path, monkeypatch):
    # Cache invalidation stays local to each temporary database, with no Redis dependency.
    monkeypatch.setattr("app.db._get_redis_client", lambda: None)
    from app.db import invalidate_calculation_context

    invalidate_calculation_context()
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "admin-tva.db")})
    yield app
    invalidate_calculation_context()


@pytest.fixture
def client(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session["admin_user"] = "direction@heliantha.ma"
    return client


@pytest.mark.parametrize("method", ["get", "post"])
def test_tva_requires_admin_session(app, method):
    response = getattr(app.test_client(), method)("/admin/tva")
    assert response.status_code == 302
    assert "/admin/login" in response.headers["Location"]


def test_tva_page_has_ten_prefilled_percentage_inputs(client):
    response = client.get("/admin/tva")
    assert response.status_code == 200
    parser = InputReader()
    parser.feed(response.get_data(as_text=True))
    assert set(VAT_KEYS).issubset(parser.inputs)
    for key in VAT_KEYS:
        field = parser.inputs[key]
        expected = Decimal("10") if key.endswith(("_panels", "_transport")) else Decimal("20")
        assert decimal(field["value"]) == expected
        assert field.get("type") == "number"
        assert field.get("min") == "0"
        assert field.get("max") == "30"


def test_tva_post_success_updates_all_profiles_and_next_quote(app, client):
    response = client.post("/admin/tva", data=percentages("10"))
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/tva")
    assert "Taux de TVA mis à jour avec succès" in client.get("/admin/tva").get_data(as_text=True)
    with app.app_context():
        assert stored_percentages() == {key: Decimal("10") for key in VAT_KEYS}
        result = CalculationEngine().calculate("photovoltaic", ON_GRID, context=load_calculation_context())
    assert result["selected_equipment"]
    assert all(decimal(line["vat_rate"]) == Decimal("0.1") for line in result["selected_equipment"])
    assert_financial_sum(result)


@pytest.mark.parametrize(
    ("project", "data"),
    [("photovoltaic", ON_GRID), ("hybrid", HYBRID), ("pumping", EXISTING_PUMP), ("pumping", NEW_PUMP)],
    ids=["on-grid", "hybrid", "existing-pump", "new-pump"],
)
def test_zero_vat_has_no_fallback_in_any_quote_engine(app, client, project, data):
    assert client.post("/admin/tva", data=percentages("0")).status_code == 302
    with app.app_context():
        result = CalculationEngine().calculate(project, data, context=load_calculation_context())
    assert result["selected_equipment"]
    for line in result["selected_equipment"]:
        assert decimal(line["vat_rate"]) == 0, line.get("component")
    financial = result["financial_breakdown"]
    assert decimal(financial["vat"]) == 0
    assert decimal(financial["total_ttc"]) == decimal(financial["total_ht"])
    if project == "pumping" and not data["pump_existing"]:
        assert any(line.get("component") == "pump" for line in result["selected_equipment"])
    assert_financial_sum(result)


@pytest.mark.parametrize("project,data", [("photovoltaic", ON_GRID), ("hybrid", HYBRID), ("pumping", NEW_PUMP)])
def test_component_groups_use_their_own_profile_rate(app, client, project, data):
    profile = "pumping" if project == "pumping" else "residential"
    rates = {"panels": "5", "equipment": "7", "accessories": "9", "transport": "11", "installation": "13"}
    form = percentages("20")
    form.update({f"{profile}_{group}": value for group, value in rates.items()})
    assert client.post("/admin/tva", data=form).status_code == 302
    with app.app_context():
        result = CalculationEngine().calculate(project, data, context=load_calculation_context())
    components = {}
    for line in result["selected_equipment"]:
        component = line.get("component") or line.get("category")
        components[component] = decimal(line["vat_rate"])
    assert components["panel"] == Decimal("0.05")
    if project == "pumping":
        assert components["pump"] == components["pump_drive"] == Decimal("0.07")
    else:
        assert components["inverter"] == Decimal("0.07")
        if project == "hybrid":
            assert components["battery"] == Decimal("0.07")
    assert components["structure"] == Decimal("0.09")
    assert components["installation"] == Decimal("0.13")
    if "transport" in components:
        assert components["transport"] == Decimal("0.11")
    assert_financial_sum(result)


@pytest.mark.parametrize("raw,expected", [("1", "0.01"), ("0.5", "0.005"), ("0,5", "0.005"), ("30", "0.3")])
def test_low_fractional_and_upper_boundary_percentages_are_not_ratios(app, client, raw, expected):
    assert client.post("/admin/tva", data=percentages(raw)).status_code == 302
    with app.app_context():
        context = load_calculation_context()
        assert vat_rate_for_component(context, "photovoltaic", "panel") == Decimal(expected)
        assert vat_rate_for_component(context, "pumping", "pump_drive") == Decimal(expected)
        result = CalculationEngine().calculate("photovoltaic", ON_GRID, context=context)
    assert all(decimal(line["vat_rate"]) == Decimal(expected) for line in result["selected_equipment"])
    assert_financial_sum(result)


@pytest.mark.parametrize("bad", ["-5", "35", "pas un nombre", "", "NaN", "Infinity", "-Infinity", "true"])
def test_invalid_admin_form_is_rejected_without_partial_save(app, client, bad):
    with app.app_context():
        before = stored_percentages()
    form = percentages("15")
    form["pumping_installation"] = bad
    response = client.post("/admin/tva", data=form)
    assert response.status_code == 400
    html = response.get_data(as_text=True)
    assert "Traceback" not in html
    assert "TVA" in html
    with app.app_context():
        assert stored_percentages() == before


def test_missing_admin_form_field_does_not_apply_the_other_nine_rates(app, client):
    with app.app_context():
        before = stored_percentages()
    form = percentages("15")
    del form["residential_transport"]
    assert client.post("/admin/tva", data=form).status_code == 400
    with app.app_context():
        assert stored_percentages() == before


@pytest.mark.parametrize("bad", ["NaN", True])
def test_database_update_validates_every_value_before_writing(app, bad):
    with app.app_context():
        before = stored_percentages()
        with pytest.raises(TaxValidationError):
            update_vat_rates({"residential_panels": "15", "pumping_transport": bad}, changed_by="test")
        assert stored_percentages() == before


def test_central_zero_overrides_legacy_rates_and_splits_group_mapping():
    context = {
        "vat_rates": percentages("0"),
        "ongrid_parameters": {"vat_pv_rate": {"value": "20"}, "vat_standard_rate": {"value": "30"}},
        "pumping_solar_rules": {"old": {"rule_type": "vat_pricing", "applies_to": "others", "vat_rate": "0.20", "active": 1}},
    }
    assert get_vat_rates(context) == {key: Decimal("0") for key in VAT_KEYS}
    for project in ("photovoltaic", "hybrid", "pumping"):
        for component in ("panel", "inverter", "battery", "pump", "pump_drive", "structure", "cabling", "transport", "installation"):
            assert vat_rate_for_component(context, project, component) == 0


@pytest.mark.parametrize("raw,expected", [("1", "0.01"), ("0", "0")])
def test_legacy_pumping_form_still_treats_input_as_a_percentage(raw, expected):
    from app.routes import _pumping_rule_payload

    form = MultiDict({"field_vat_rate": raw, "field_applies_to": "panels", "active": "on"})
    payload = _pumping_rule_payload("vat_pricing", form, {"vat_rate": 0.20, "applies_to": "panels"})
    assert decimal(payload["vat_rate"]) == Decimal(expected)


def test_legacy_migration_preserves_zero_custom_rates_and_reseeding_is_idempotent(app):
    with app.app_context():
        db = get_db()
        db.executemany(
            "UPDATE ongrid_parameters SET value = ? WHERE key = ?",
            [("0", "vat_pv_rate"), ("17.5", "vat_transport_rate"), ("7", "vat_standard_rate")],
        )
        db.executemany(
            "UPDATE pumping_solar_rules SET vat_rate = ? WHERE rule_key = ?",
            [(0, "vat-panels"), (0.175, "vat-transport"), (0.07, "vat-others"), (0, "pump-sale-parameters")],
        )
        # Simulate a pre-feature database while retaining all real legacy tables.
        db.execute("DROP TABLE vat_rates")
        db.commit()
        init_db()
        values = stored_percentages()
        assert values["residential_panels"] == 0
        assert values["residential_transport"] == Decimal("17.5")
        assert values["residential_equipment"] == values["residential_accessories"] == values["residential_installation"] == Decimal("7")
        assert values["pumping_panels"] == values["pumping_equipment"] == 0
        assert values["pumping_transport"] == Decimal("17.5")
        assert values["pumping_accessories"] == values["pumping_installation"] == Decimal("7")
        update_vat_rates({"residential_panels": "1.5", "pumping_equipment": "0"}, changed_by="test")
        expected = stored_percentages()
        init_db()
        init_db()
        assert stored_percentages() == expected
        assert len(list_vat_rates()) == 10


def test_changing_vat_never_reprices_an_existing_quote_snapshot(app):
    with app.app_context():
        result = CalculationEngine().calculate("photovoltaic", ON_GRID, context=load_calculation_context())
        quote_id = save_quote("HSQ-TVA-HISTORICAL", "photovoltaic", ON_GRID, {"name": "Client test"}, result)
        sql = "SELECT result_json, financial_breakdown_json, selected_equipment_json, quote_snapshot_json, amount_ht, amount_ttc FROM quote_requests WHERE id = ?"
        before = tuple(get_db().execute(sql, (quote_id,)).fetchone())
        update_vat_rates(percentages("0"), changed_by="test")
        init_db()
        after = tuple(get_db().execute(sql, (quote_id,)).fetchone())
        assert after == before
        updated = CalculationEngine().calculate("photovoltaic", ON_GRID, context=load_calculation_context())
        assert decimal(updated["financial_breakdown"]["vat"]) == 0
        assert decimal(result["financial_breakdown"]["vat"]) > 0


def test_half_cent_rounds_up_and_admin_totals_match_the_financial_breakdown():
    from app.calculators.engine import ContextView
    from app.routes import _display_equipment_lines
    from app.services.pricing import PricingEngine

    lines = [
        {
            "component": "panel", "category": "panels", "quantity": 1,
            "unit_price": "0.05", "total_price": "0.05", "vat_rate": "0.1",
            "price_status": "rule_price", "description": f"Ligne {index}",
        }
        for index in (1, 2)
    ]
    context = ContextView({"vat_rates": percentages("10"), "products": []})
    financial = PricingEngine().breakdown("pumping", lines, context)
    display = _display_equipment_lines(lines)
    expected_vat = (Decimal("0.05") * Decimal("0.1")).quantize(CENT, rounding=ROUND_HALF_UP)
    assert expected_vat == Decimal("0.01")
    assert all(decimal(row["display_vat_amount"]) == expected_vat for row in display)
    assert decimal(financial["vat"]) == Decimal("0.02")
    assert decimal(financial["vat"]) == sum(decimal(row["display_vat_amount"]) for row in display)
    assert decimal(financial["total_ttc"]) == sum(decimal(row["display_total_ttc"]) for row in display)


def test_public_amounts_match_admin_and_pricing_at_a_half_cent_boundary():
    from app.calculators.engine import ContextView
    from app.public_presenters import _sanitize_public_equipment
    from app.routes import _display_equipment_lines
    from app.services.pricing import PricingEngine

    equipment = [{
        "component": "panel", "category": "panels", "quantity": 1,
        "unit_price": "0.15", "total_price": "0.15", "vat_rate": "0.1",
        "price_status": "rule_price", "description": "Panneau solaire",
        "product_id": 999, "purchase_price": "0.08", "supplier": "Interne",
        "technical_specs": {"power_w": 590, "internal_price_pt": "0.08"},
    }]
    context = ContextView({"vat_rates": percentages("10"), "products": []})
    financial = PricingEngine().breakdown("pumping", equipment, context)
    admin = _display_equipment_lines(equipment)[0]
    public = _sanitize_public_equipment(equipment, project="pumping")[0]
    assert decimal(public["total_price_ht"]) == decimal(admin["display_total_price_ht"]) == Decimal("0.15")
    assert decimal(public["vat_amount"]) == decimal(admin["display_vat_amount"]) == decimal(financial["vat"]) == Decimal("0.02")
    assert decimal(public["total_price_ttc"]) == decimal(admin["display_total_ttc"]) == decimal(financial["total_ttc"]) == Decimal("0.17")
    assert decimal(public["total_price_ttc"]) == decimal(public["total_price_ht"]) + decimal(public["vat_amount"])
    assert public["technical_specs"] == {"power_w": 590}
    assert all(key not in public for key in ("product_id", "purchase_price", "supplier"))


def test_public_pump_preserves_contractual_ttc_without_exposing_internal_pt():
    from app.calculators.engine import ContextView
    from app.public_presenters import _sanitize_public_equipment
    from app.routes import _display_equipment_lines
    from app.services.pricing import PricingEngine

    equipment = [{
        "component": "pump", "category": "pumps", "quantity": 1,
        "unit_price": "0.03", "total_price": "0.03", "vat_rate": "0.2",
        "price_status": "catalog_price", "description": "Pompe solaire 2 CV",
        "brand": "Marque interne", "model": "Référence interne", "reference": "PT-INTERNE",
        "product_id": 999, "purchase_price": "0.046", "supplier": "Interne",
        "technical_specs": {
            "price_tax_basis": "internal_pt", "internal_price_pt": "0.046",
            "pump_sale_coefficient_1": "0.5", "pump_sale_coefficient_2": "1.3",
            "pump_sale_price_ttc": "0.03", "outlet_diameter": '2"', "power_hp": 2,
        },
    }]
    context = ContextView({"vat_rates": percentages("20"), "products": []})
    financial = PricingEngine().breakdown("pumping", equipment, context)
    admin = _display_equipment_lines(equipment)[0]
    public = _sanitize_public_equipment(equipment, project="pumping")[0]
    assert decimal(public["total_price_ht"]) == decimal(admin["display_total_price_ht"]) == Decimal("0.03")
    assert decimal(public["vat_amount"]) == decimal(admin["display_vat_amount"]) == decimal(financial["vat"]) == 0
    assert decimal(public["total_price_ttc"]) == decimal(admin["display_total_ttc"]) == decimal(financial["total_ttc"]) == Decimal("0.03")
    assert decimal(public["total_price_ttc"]) == decimal(public["total_price_ht"]) + decimal(public["vat_amount"])
    assert public["technical_specs"] == {"outlet_diameter": '2"', "power_hp": 2}
    for key in ("product_id", "purchase_price", "supplier", "internal_price_pt", "price_tax_basis", "pump_sale_price_ttc", "pump_sale_coefficient_1", "pump_sale_coefficient_2"):
        assert key not in public
        assert key not in public["technical_specs"]
    assert not public.get("brand")
    assert not public.get("model")
    assert not public.get("reference")
