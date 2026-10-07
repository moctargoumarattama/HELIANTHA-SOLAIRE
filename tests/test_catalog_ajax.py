"""Catalogue administration: focused AJAX updates and CSRF protection."""

import re

import pytest

from app import create_app
from app.db import get_db, get_product, save_product


@pytest.fixture
def catalogue(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "catalog-ajax.db")})
    client = app.test_client()
    with client.session_transaction() as session:
        session["admin_user"] = "test"
        session["admin_role"] = "admin"
    with app.app_context():
        product_id = get_db().execute(
            "SELECT id FROM products WHERE reference = 'ONGRID-PV-590'"
        ).fetchone()[0]
    return app, client, product_id


def ajax(client, path, data):
    return client.post(
        path,
        data=data,
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
    )


def test_catalogue_loads_light_list_and_requires_admin(catalogue):
    app, client, product_id = catalogue
    page = client.get("/admin/catalogue").get_data(as_text=True)
    assert 'id="catalog-products-data"' not in page
    assert 'admin_catalog.js' in page
    assert f'data-product-id="{product_id}"' in page
    assert 'data-catalog-active' in page
    with app.test_client() as guest:
        assert guest.get(f"/admin/catalogue/{product_id}/edit?format=json").status_code == 302
        assert guest.post(f"/admin/catalogue/{product_id}/toggle").status_code == 302


def test_editor_details_are_fetched_on_demand(catalogue):
    _app, client, product_id = catalogue
    response = client.get(f"/admin/catalogue/{product_id}/edit?format=json")
    assert response.status_code == 200 and response.is_json
    data = response.get_json()
    product = data["product"]
    assert data["success"] is True
    for key in ("id", "reference", "designation", "category", "power_w", "price_ht", "price_ttc", "en_stock", "is_active", "tech_specs", "active", "technical_specs"):
        assert key in product
    assert "stock" not in product and "vat_rate" not in product


def test_ajax_update_returns_row_counts_and_preserves_specs(catalogue):
    app, client, product_id = catalogue
    with app.app_context():
        before = get_product(product_id)
    response = ajax(client, f"/admin/catalogue/{product_id}/edit", {
        "power_w": "700 Wc", "model": "Panneau 700 Wc", "sale_price": "1350",
    })
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True and data["action"] == "updated"
    assert data["product"]["power_w"] == 700
    assert data["product"]["price_ht"] == 1350
    assert f'data-product-id="{product_id}"' in data["html_row"]
    assert "Panneau 700 Wc" in data["html_row"]
    assert data["counts"]["total"] > 0 and data["counts"]["active"] > 0
    with app.app_context():
        after = get_product(product_id)
    assert after["power_w"] == 700 and after["sale_price"] == 1350
    assert after["technical_specs"]["power_w"] == 700
    for key in ("stock", "vat_rate", "description", "datasheet_url"):
        assert after[key] == before[key]


def test_ajax_json_body_updates_numeric_fields_and_rejects_non_object(catalogue):
    app, client, product_id = catalogue
    path = f"/admin/catalogue/{product_id}/edit"
    bad = client.post(path, json=["invalid"], headers={"Accept": "application/json"})
    assert bad.status_code == 400 and bad.get_json()["success"] is False
    response = client.post(path, json={"sale_price": 1450, "power_w": 710}, headers={"Accept": "application/json"})
    assert response.status_code == 200 and response.get_json()["success"] is True
    with app.app_context():
        product = get_product(product_id)
    assert product["power_w"] == 710 and product["sale_price"] == 1450


def test_ajax_create_and_validation_leave_no_duplicate(catalogue):
    app, client, _product_id = catalogue
    form = {
        "reference": "AJAX-PV-725", "category": "panels", "brand": "HeliAntha",
        "model": "Panneau 725 Wc", "power_w": "725", "sale_price": "2100",
        "active": "on", "active_submitted": "1",
    }
    invalid = ajax(client, "/admin/catalogue/new", {**form, "power_w": "-725"})
    assert invalid.status_code == 400
    assert invalid.get_json()["success"] is False
    assert "power_w" in invalid.get_json()["errors"]
    created = ajax(client, "/admin/catalogue/new", form)
    assert created.status_code == 200
    data = created.get_json()
    assert data["success"] is True and data["action"] == "created"
    assert data["counts"]["total"] > 0
    assert f'data-product-id="{data["product"]["id"]}"' in data["html_row"]
    with app.app_context():
        rows = get_db().execute("SELECT id, power_w FROM products WHERE reference = ?", (form["reference"],)).fetchall()
    assert len(rows) == 1 and rows[0]["power_w"] == 725


def test_ajax_toggle_changes_status_once_and_reports_validation(catalogue):
    app, client, product_id = catalogue
    url = f"/admin/catalogue/{product_id}/toggle"
    first = ajax(client, url, {})
    assert first.status_code == 200
    payload = first.get_json()
    assert payload["success"] is True and payload["is_active"] is False
    assert "Désactiver" not in payload["badge_html"]
    assert f'data-product-id="{product_id}"' in payload["html_row"]
    with app.app_context():
        assert get_product(product_id)["active"] == 0
        save_product({"sale_price": 0, "active": 0}, product_id)
    blocked = ajax(client, url, {})
    assert blocked.status_code == 400 and blocked.get_json()["success"] is False
    with app.app_context():
        assert get_product(product_id)["active"] == 0


def test_ajax_admin_csrf_rejects_missing_and_accepts_valid_token(tmp_path):
    app = create_app({
        "TESTING": True, "DATABASE": str(tmp_path / "csrf-catalog.db"),
        "WTF_CSRF_ENABLED": True,
    })
    client = app.test_client()
    with client.session_transaction() as session:
        session["admin_user"] = "test"
        session["admin_role"] = "admin"
    with app.app_context():
        product_id = get_db().execute("SELECT id FROM products WHERE reference = 'ONGRID-PV-590'").fetchone()[0]
    path = f"/admin/catalogue/{product_id}/toggle"
    assert ajax(client, path, {}).status_code == 400
    page = client.get("/admin/catalogue").get_data(as_text=True)
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', page)
    assert token
    response = client.post(path, data={}, headers={
        "X-Requested-With": "XMLHttpRequest", "Accept": "application/json",
        "X-CSRFToken": token.group(1),
    })
    assert response.status_code == 200 and response.get_json()["success"] is True
