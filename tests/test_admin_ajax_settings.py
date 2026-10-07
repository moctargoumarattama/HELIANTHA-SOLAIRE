"""AJAX saves keep the HTML admin contract and protect configuration writes."""

import re

import pytest

from app import create_app
from app.db import get_db, list_vat_rates, save_quote


@pytest.fixture
def admin(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "admin-ajax.db")})
    client = app.test_client()
    with client.session_transaction() as session:
        session["admin_user"] = "test"
        session["admin_role"] = "admin"
    return app, client


def ajax(client, path, data):
    return client.post(path, data=data, headers={
        "X-Requested-With": "XMLHttpRequest", "Accept": "application/json",
    })


def test_vat_ajax_success_validation_and_html_fallback(admin):
    app, client = admin
    with app.app_context():
        values = {row["key"]: row["value"] for row in list_vat_rates()}
    values["residential_panels"] = "11"
    result = ajax(client, "/admin/tva", values)
    assert result.status_code == 200 and result.is_json
    assert result.get_json()["success"] is True
    assert result.get_json()["updated_values"]["residential_panels"] == "11"
    rejected = ajax(client, "/admin/tva", {**values, "residential_panels": "-5"})
    assert rejected.status_code == 400
    assert "residential_panels" in rejected.get_json()["errors"]
    with app.app_context():
        stored = {row["key"]: row["value"] for row in list_vat_rates()}
    assert stored["residential_panels"] == "11"
    ordinary = client.post("/admin/tva", data=values)
    assert ordinary.status_code == 302 and ordinary.headers["Location"].endswith("/admin/tva")


def test_transport_and_settings_ajax_use_separate_pages(admin):
    app, client = admin
    result = ajax(client, "/admin/tva", {
        "action": "save_transport", "transport_ongrid_rate": "75",
        "transport_pumping_rate": "80", "transport_pumping_mode": "per_panel",
    })
    assert result.status_code == 200
    assert result.get_json()["updated_values"]["transport_pumping_rate"] == "80.00"
    invalid = ajax(client, "/admin/tva", {
        "action": "save_transport", "transport_pumping_rate": "-1",
    })
    assert invalid.status_code == 400
    assert "transport_pumping_rate" in invalid.get_json()["errors"]
    with app.app_context():
        db = get_db()
        assert db.execute("SELECT value FROM company_settings WHERE key='transport_pumping_rate'").fetchone()[0] == "80.00"
        row = db.execute("SELECT id FROM company_settings WHERE key='company_name'").fetchone()
    settings = ajax(client, "/admin/settings", {f"value_{row['id']}": "HeliAntha Essai"})
    assert settings.status_code == 200 and settings.get_json()["success"] is True
    with app.app_context():
        assert get_db().execute("SELECT value FROM company_settings WHERE key='company_name'").fetchone()[0] == "HeliAntha Essai"
    assert client.get("/admin/parametres").status_code == 200


def test_ongrid_and_pumping_rules_ajax_save_without_redirect(admin):
    app, client = admin
    ongrid = ajax(client, "/admin/regles-ongrid", {"value_protection_acdc_per_pv": "145"})
    assert ongrid.status_code == 200 and ongrid.get_json()["success"] is True
    with app.app_context():
        db = get_db()
        assert db.execute("SELECT value FROM ongrid_parameters WHERE key='protection_acdc_per_pv'").fetchone()[0] == "145"
        rule = db.execute("SELECT id, pump_cv, panel_power_w, drive_power_kw, phase, drive_brand FROM pumping_solar_rules WHERE rule_key='pump-15cv'").fetchone()
    pumping = ajax(client, "/admin/regles-pompage", {
        "action": "save_rule", "rule_type": "pump_configuration", "rule_id": rule["id"],
        "field_pump_cv": str(rule["pump_cv"]), "field_panel_count": "26",
        "field_panel_power_w": str(rule["panel_power_w"]),
        "field_drive_power_kw": str(rule["drive_power_kw"]),
        "field_phase": rule["phase"], "field_drive_brand": rule["drive_brand"],
        "active": "on",
    })
    assert pumping.status_code == 200
    payload = pumping.get_json()
    assert payload["success"] is True and payload["rule_id"] == rule["id"]
    assert 'id="pr-cockpit"' in payload["page_html"]
    with app.app_context():
        assert get_db().execute("SELECT panel_count FROM pumping_solar_rules WHERE id=?", (rule["id"],)).fetchone()[0] == 26


def test_quote_status_ajax_updates_badge_and_database(admin):
    app, client = admin
    with app.app_context():
        quote_id = save_quote("HSQ-AJAX-STATUS", "photovoltaic", {}, {"name": "Client"}, {})
    response = ajax(client, f"/admin/devis/{quote_id}/status", {"status": "Accepte"})
    assert response.status_code == 200 and response.is_json
    data = response.get_json()
    assert data["success"] is True and data["quote_id"] == quote_id
    assert data["new_status"] == "Accepte" and data["badge_class"] == "crm-st-success"
    with app.app_context():
        assert get_db().execute("SELECT status FROM quote_requests WHERE id=?", (quote_id,)).fetchone()[0] == "Accepte"
    assert 'crm-inline-status-form' in client.get("/admin/devis").get_data(as_text=True)
    detail = client.get(f"/admin/devis/{quote_id}").get_data(as_text=True)
    assert 'qc-status-form' in detail
    assert 'qc-badge-status status crm-st-success' in detail
    invalid = ajax(client, f"/admin/devis/{quote_id}/status", {"status": "Visite programmee"})
    assert invalid.status_code == 400 and "status" in invalid.get_json()["errors"]
    ordinary = client.post(f"/admin/devis/{quote_id}/status", data={"status": "Contacte"})
    assert ordinary.status_code == 302


def test_ajax_csrf_header_is_required_when_enabled(tmp_path):
    app = create_app({
        "TESTING": True, "DATABASE": str(tmp_path / "csrf-admin-ajax.db"),
        "WTF_CSRF_ENABLED": True,
    })
    client = app.test_client()
    with client.session_transaction() as session:
        session["admin_user"] = "test"
    with app.app_context():
        values = {row["key"]: row["value"] for row in list_vat_rates()}
    assert ajax(client, "/admin/tva", values).status_code == 400
    page = client.get("/admin/tva").get_data(as_text=True)
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', page)
    assert token
    response = client.post("/admin/tva", data=values, headers={
        "X-Requested-With": "XMLHttpRequest", "Accept": "application/json",
        "X-CSRFToken": token.group(1),
    })
    assert response.status_code == 200 and response.get_json()["success"] is True
