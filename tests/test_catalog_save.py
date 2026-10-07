"""Admin catalogue edits must preserve technical data and refresh sizing."""
import json
from decimal import Decimal
from unittest.mock import patch

import pytest

from app import create_app
from app.catalog import ProductValidationError, validate_product
from app.calculators import CalculationEngine
from app.db import get_db, get_product, load_calculation_context, save_product, set_product_active
from app.routes import _product_from_form
from app.services.ongrid_service import calculate_ongrid


def panel(**updates):
    return {
        "reference": "TEST-PV", "category": "panels", "brand": "Test",
        "model": "Panneau 590 Wc", "power_w": 590, "sale_price": 1000,
        "stock": 5, "active": 1, "currency": "DH",
        "technical_specs": {"power_w": 590, "voc": 52, "isc": 14,
                            "efficiency": 22, "warranty_years": 25,
                            "dimensions": {"height": 2300, "width": 1100}},
        **updates,
    }


@pytest.mark.parametrize("power", ["700", "700 W", "700Wc", "700,5 Wc", "700 Watts-crête"])
def test_panel_power_accepts_watts_and_french_decimals(power):
    expected = 700.5 if "," in power else 700
    updated = validate_product({"power_w": power}, existing=panel(), submitted_fields={"power_w": power})
    assert updated["power_w"] == expected
    assert updated["technical_specs"]["power_w"] == expected
    assert updated["technical_specs"]["voc"] == 52


@pytest.mark.parametrize("power", ["-700", "0", "49", "1501", "sept cents", "700 kW", "NaN", "inf", ""])
def test_invalid_panel_power_is_rejected_without_falling_back_to_old_rating(power):
    with pytest.raises(ProductValidationError) as failure:
        validate_product({"power_w": power}, existing=panel(), submitted_fields={"power_w": power})
    assert "power_w" in failure.value.errors


def test_legacy_form_power_refreshes_column_and_json():
    updated = validate_product(panel(), existing=panel(), submitted_fields={"spec_power_w": "700"})
    assert updated["power_w"] == updated["technical_specs"]["power_w"] == 700


def test_conflicting_power_inputs_are_rejected():
    with pytest.raises(ProductValidationError):
        validate_product(panel(), existing=panel(), submitted_fields={"power_w": "700", "spec_power_w": "590"})


def test_title_rating_change_requires_explicit_power():
    with pytest.raises(ProductValidationError) as failure:
        validate_product({"model": "Panneau 700 Wc"}, existing=panel(), submitted_fields={"model": "Panneau 700 Wc"})
    assert "power_w" in failure.value.errors


def test_partial_update_keeps_columns_and_merges_nested_specs():
    existing = panel(description="Fiche technique", efficiency=22, warranty="25 ans", voltage=48, unit="piece", supplier="Fournisseur")
    updated = validate_product({"sale_price": "1200", "technical_specs": {"dimensions": {"height": 2400}}}, existing=existing)
    for key in ("description", "efficiency", "warranty", "voltage", "unit", "supplier", "stock", "active", "power_w"):
        assert updated[key] == existing[key]
    assert updated["technical_specs"]["dimensions"] == {"height": 2400, "width": 1100}
    assert updated["technical_specs"]["isc"] == 14


@pytest.mark.parametrize("price", ["-1", "NaN", "inf", "-inf", "prix"])
def test_invalid_prices_are_rejected(price):
    with pytest.raises(ProductValidationError) as failure:
        validate_product({"sale_price": price}, existing=panel())
    assert "sale_price" in failure.value.errors


def test_active_zero_price_is_blocked_but_inactive_draft_is_allowed():
    with pytest.raises(ProductValidationError):
        validate_product({"sale_price": 0}, existing=panel())
    assert validate_product({"sale_price": 0, "active": 0}, existing=panel())["active"] == 0


def test_negative_stock_is_rejected():
    with pytest.raises(ProductValidationError):
        validate_product({"stock": "-1"}, existing=panel())


def test_partial_form_preserves_activation_and_full_form_can_uncheck_it():
    assert _product_from_form({"sale_price": "1200"}, panel())["active"] == 1
    assert _product_from_form({"active_submitted": "1", "sale_price": "1200"}, panel())["active"] == 0


def test_explicit_nominal_inverter_power_refreshes_sql_counterpart():
    updated = validate_product({"sale_price": 1000}, existing={
        **panel(category="inverters", power_kw=5),
        "technical_specs": {"type": "hybrid", "phases": "monophase", "power_kw": 5, "voc": 52},
    }, submitted_fields={"spec_power_kw": "6"})
    assert updated["power_kw"] == updated["technical_specs"]["power_kw"] == 6
    assert updated["technical_specs"]["voc"] == 52


@pytest.fixture
def application(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "catalog-save.db")})
    client = app.test_client()
    with client.session_transaction() as session:
        session["admin_user"] = "test"
        session["admin_role"] = "admin"
    with app.app_context():
        product_id = get_db().execute("SELECT id FROM products WHERE reference = 'ONGRID-PV-590'").fetchone()[0]
    return app, client, product_id


def test_admin_post_refreshes_sql_json_cache_and_ongrid_calculation(application):
    app, client, product_id = application
    with app.app_context():
        before = load_calculation_context()
        assert calculate_ongrid({"phase": "monophase", "monthly_consumption_kwh": 1000}, before)["final_results"]["panel_power_w"] == 590
    response = client.post(f"/admin/catalogue/{product_id}/edit", data={"power_w": "700 Wc", "model": "Panneau 700 Wc"})
    assert response.status_code == 302
    with app.app_context():
        row = get_db().execute("SELECT power_w, technical_specs_json FROM products WHERE id = ?", (product_id,)).fetchone()
        assert row["power_w"] == 700
        assert json.loads(row["technical_specs_json"])["power_w"] == 700
        context = load_calculation_context()
        # Legacy catalogue VAT must not override the central tax profile.
        for product in context["products"]:
            product["vat_rate"] = 0.30
        result = CalculationEngine().calculate("photovoltaic", {
            "phase": "monophase", "meter_type": "numerique", "monthly_consumption_kwh": 1000,
        }, context=context)
        final = result["final_results"]
        selected = next(item for item in result["selected_equipment"] if item["component"] == "panel")
        assert selected["product_id"] == product_id
        assert selected["power_w"] == final["panel_power_w"] == 700
        assert selected["vat_rate"] == 0.10
        assert final["installed_power_kwp"] == pytest.approx(final["panel_count"] * 0.7)
        assert final["raw_panel_count"] == pytest.approx(9.52)
        assert final["inverter_power_kw"] >= final["installed_power_kwp"]


def test_admin_partial_post_preserves_hidden_json_and_sql_fields(application):
    app, client, product_id = application
    with app.app_context():
        product = get_product(product_id)
        original = panel()["technical_specs"]
        save_product({**product, "technical_specs": original, "efficiency": 22,
                      "description": "Description conservée", "voltage": 48,
                      "technology": "TOPCon", "supplier": "Fournisseur", "warranty": "25 ans"}, product_id)
        before = get_product(product_id)
    # A stale form must no longer modify inventory or VAT through the catalogue.
    assert client.post(f"/admin/catalogue/{product_id}/edit", data={"sale_price": "1350", "model": "Nouveau nom", "stock": "999", "vat_rate": "30"}).status_code == 302
    with app.app_context():
        after = get_product(product_id)
    assert after["technical_specs"] == before["technical_specs"]
    for key in ("reference", "category", "brand", "description", "voltage", "efficiency", "technology", "supplier", "warranty", "unit", "subcategory", "stock", "active"):
        assert after[key] == before[key]
    assert after["sale_price"] == 1350
    assert after["vat_rate"] == before["vat_rate"]
    editor_data = client.get(f"/admin/catalogue/{product_id}/edit?format=json").get_json()["product"]
    assert "stock" not in editor_data and "stock_label" not in editor_data
    assert "vat_rate" not in editor_data


def test_rejected_admin_posts_leave_database_intact_and_report_errors(application):
    app, client, product_id = application
    with app.app_context():
        before = get_product(product_id)
    for form in ({"power_w": "-700"}, {"power_w": "texte"}, {"sale_price": "-2"}, {"sale_price": "0", "active": "on"}, {"model": "Panneau 700 Wc"}):
        response = client.post(f"/admin/catalogue/{product_id}/edit", data=form)
        assert response.status_code == 200  # Existing admin validation contract.
        assert "Corrigez les champs signalés" in response.get_data(as_text=True)
        with client.session_transaction() as session:
            assert not session.get("_flashes")  # Display once, without a stale error on the next successful save.
        with app.app_context():
            assert get_product(product_id) == before
    success = client.post(f"/admin/catalogue/{product_id}/edit", data={"sale_price": "1500"}, follow_redirects=True)
    assert "pas été enregistrée" not in success.get_data(as_text=True)


def test_activation_blocks_free_draft_and_toggle_refreshes_cache(application):
    app, client, product_id = application
    with app.app_context():
        save_product({"sale_price": 0, "active": 0}, product_id)
        assert not next(p for p in load_calculation_context()["products"] if p["id"] == product_id)["active"]
    response = client.post(f"/admin/catalogue/{product_id}/toggle", follow_redirects=True)
    assert "prix supérieur à 0 DH" in response.get_data(as_text=True)
    with app.app_context():
        assert get_product(product_id)["active"] == 0
        save_product({"sale_price": 1000}, product_id)
        set_product_active(product_id, True)
        assert next(p for p in load_calculation_context()["products"] if p["id"] == product_id)["active"] == 1
        set_product_active(product_id, False)
        assert next(p for p in load_calculation_context()["products"] if p["id"] == product_id)["active"] == 0


def test_duplicate_reference_rolls_back_without_invalidating_cache(application):
    app, _client, product_id = application
    with app.app_context():
        before = get_product(product_id)
        with patch("app.db.invalidate_calculation_context") as invalidate:
            with pytest.raises(ProductValidationError):
                save_product({"reference": "ONGRID-PV-400", "power_w": 700}, product_id)
            invalidate.assert_not_called()
        assert get_product(product_id) == before


def test_editor_uses_shared_power_metadata(application):
    _app, client, product_id = application
    html = client.get(f"/admin/catalogue/{product_id}/edit").get_data(as_text=True)
    assert 'name="power_w"' in html
    assert 'min="50"' in html and 'max="1500"' in html
    assert "Puissance réelle en Watts utilisée par le calculateur de dimensionnement" in html
    assert 'id="catalog-field-definitions"' in html
    for url in ("/admin/catalogue", "/admin/catalogue/new"):
        page = client.get(url).get_data(as_text=True)
        assert 'name="stock"' not in page
        assert 'modal-f-stock' not in page
        assert '"stock":' not in page
        assert 'name="vat_rate"' not in page
        assert 'modal-f-vat' not in page
        assert '"vat_rate":' not in page
    assert 'name="stock"' not in html
    assert 'name="vat_rate"' not in html


def test_ongrid_fractional_power_uses_exact_rating_without_truncation():
    products = [panel(reference="ONGRID-PV-590", power_w=700.5)]
    from app.services.ongrid_service import select_panel
    assert select_panel(products, 590)["power_w"] == 700.5
