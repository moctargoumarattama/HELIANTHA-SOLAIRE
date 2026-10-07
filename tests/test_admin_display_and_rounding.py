"""Mobile labels and monetary displays must match saved quote amounts."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
import json
import re

from bs4 import BeautifulSoup
import pytest

import app as application
import app.routes as routes
from app import create_app
from app.admin_quotes import group_quotes_by_client
from app.calculators.engine import ContextView
from app.db import get_db, get_quote, save_quote
from app.public_presenters import format_money_fr, sanitize_calculation_result_for_public
from app.services.pdf_service import _money as pdf_money
from app.services.pricing import PricingEngine
from app.tax import VAT_FIELDS, format_currency, money


ROOT = Path(routes.__file__).resolve().parent.parent


def quote(**updates):
    return {
        "id": 17, "quote_number": "HSQ-DISPLAY-17", "customer_name": "Client test",
        "phone": "", "city": "Rabat", "project": "photovoltaic", "status": "Nouveau",
        "created_at": "07/10/2026", "amount_ht": 9999, "amount_ttc": 9999,
        "financial_breakdown_json": json.dumps({"total_ht": 1.05, "vat": 0.11, "total_ttc": 1.16}),
        "financial_breakdown": {"total_ht": 1.05, "vat": 0.11, "total_ttc": 1.16},
        "selected_equipment": [{"component": "panel", "category": "panels", "quantity": 1,
                                "description": "Panneau solaire", "unit_price": "1.045",
                                "total_price": "1.045", "vat_rate": "0.1"}],
        **updates,
    }


@pytest.fixture
def client():
    app = application.Flask("app", template_folder=str(ROOT / "templates"))
    app.config.update(TESTING=True, SECRET_KEY="display-tests")
    app.register_blueprint(routes.bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["admin_user"] = "test"
    return client


def assert_table_labels(table):
    headers = [cell.get_text(strip=True) for cell in table.select("thead th")]
    for row in table.select("tbody tr"):
        cells = row.find_all("td", recursive=False)
        if any(cell.has_attr("colspan") for cell in cells):
            continue
        assert len(cells) == len(headers)
        assert [cell.get("data-label") for cell in cells] == headers


def test_list_data_labels_match_headers_and_ttc_never_appears_under_ht(client):
    original = quote()
    with patch("app.routes.list_quotes", return_value=[original]):
        response = client.get("/admin/devis")
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, "html.parser")
    table = soup.select_one(".quotes-table-wrap table")
    assert_table_labels(table)
    row = table.select_one("tbody tr")
    assert row.select_one('td[data-label="Total HT"]').get_text(strip=True) == "1,05 DH"
    assert row.select_one('td[data-label="TVA"]').get_text(strip=True) == "0,11 DH"
    ttc = row.select_one('td[data-label="Total TTC"]')
    assert ttc.get_text(strip=True) == "1,16 DH"
    assert "amount-ttc" in ttc.get("class", []) and ttc.find("strong")
    assert original["amount_ht"] == 9999  # Read the snapshot, don't mutate SQL rows.


def test_detail_data_labels_match_headers_and_amounts_match_rounded_ht(client):
    with patch("app.routes.get_quote", return_value=quote()):
        response = client.get("/admin/devis/17")
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, "html.parser")
    assert_table_labels(soup.select_one(".simple-quote-table"))
    assert soup.select_one('td[data-label="PU HT"]').get_text(strip=True) == "1,05 DH"
    assert "0,11 DH" in soup.select_one('td[data-label="TVA"]').get_text()
    assert soup.select_one('td[data-label="Total TTC"]').get_text(strip=True) == "1,16 DH"


def test_html_pdf_labels_match_headers(client):
    from flask import render_template
    with client.application.test_request_context():
        html = render_template("admin/quote_pdf.html", quote=quote(), company={},
                               display_equipment_lines=routes._display_equipment_lines(quote()["selected_equipment"]))
    soup = BeautifulSoup(html, "html.parser")
    assert_table_labels(soup.select_one(".proposal-table"))
    assert soup.select_one('.proposal-table td[data-label="Total TTC"]').get_text(strip=True) == "1,16"


def test_mobile_quote_labels_come_from_attributes_and_are_separate_from_amount_values():
    css = (ROOT / "static/css/admin.css").read_text(encoding="utf-8")
    mobile = css[css.index("@media screen and (max-width:768px)"):]
    assert re.search(r"td\[data-label\]::before\s*\{[^}]*content:\s*attr\(data-label\)", mobile)
    assert "grid-template-columns:minmax(84px, .9fr) minmax(0, 1.4fr)" in mobile
    assert not re.search(r"nth-(?:child|of-type)\([^)]*\)::before\s*\{\s*content:\s*[\"'](?:HT|TTC|Total HT|Total TTC)", css)


@pytest.mark.parametrize("value,expected", [
    ("0.005", "0,01"), ("0.015", "0,02"), ("0.995", "1,00"),
    ("2.675", "2,68"), ("10000.005", "10 000,01"), ("-0.005", "-0,01"),
])
def test_html_public_and_pdf_formats_share_half_up_rounding(value, expected, client):
    assert format_currency(value) == f"{expected} DH"
    assert format_money_fr(value) == f"{expected} DH"
    assert pdf_money(value) == f"{expected} MAD"
    with client.application.app_context():
        assert client.application.jinja_env.from_string("{{ value|format_currency }}").render(value=value) == f"{expected} DH"


@pytest.mark.parametrize("value", ["0.005", "0.015", "0.995", "1.045", "2.675"])
def test_critical_prices_keep_line_sum_ht_vat_ttc_invariant_in_engine_admin_and_api(value):
    equipment = [{"component": "panel", "category": "panels", "quantity": 1,
                  "unit_price": value, "total_price": value, "vat_rate": "0.1",
                  "price_status": "rule_price", "description": "Panneau solaire"} for _ in range(2)]
    context = ContextView({"vat_rates": {field["key"]: "10" for field in VAT_FIELDS}, "products": []})
    financial = PricingEngine().breakdown("pumping", equipment, context)
    public = sanitize_calculation_result_for_public({"project": "pumping", "selected_equipment": equipment,
                                                   "financial_breakdown": financial})
    admin = routes._display_equipment_lines(equipment)
    ht = sum((money(row["display_total_price_ht"]) for row in admin), Decimal(0))
    vat = sum((money(row["display_vat_amount"]) for row in admin), Decimal(0))
    ttc = sum((money(row["display_total_ttc"]) for row in admin), Decimal(0))
    assert money(financial["total_ht"]) == ht
    assert money(financial["vat"]) == vat
    assert money(financial["total_ttc"]) == ht + vat == ttc
    assert money(financial["total_ttc"]) == money(Decimal(str(financial["total_ht"])) + Decimal(str(financial["vat"])))
    for visible, displayed in zip(public["selected_equipment"], admin):
        assert money(visible["total_price_ttc"]) == money(displayed["display_total_ttc"])
        assert money(visible["vat_amount"]) == money(displayed["display_vat_amount"])


def test_legacy_quote_without_financial_json_uses_saved_ht_ttc_only():
    q = quote(financial_breakdown=None, financial_breakdown_json="", amount_ht=100.01, amount_ttc=120.02)
    displayed = group_quotes_by_client([q])[0]["quotes"][0]
    assert money(displayed["amount_vat"]) == Decimal("20.01")
    assert money(displayed["amount_ttc"]) == Decimal("120.02")


def test_new_save_aligns_sql_json_snapshot_html_and_public_labels_without_mutating_input(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "cent-save.db")})
    raw = {"total_ht": 10000.005, "vat": 0.015, "total_ttc": 10000.020}
    result = {"project": "photovoltaic", "financial_breakdown": raw,
              "quote_snapshot": {"financial_breakdown": deepcopy(raw)},
              "offers": [{"level": "optimal", "recommended": True, "ht": raw["total_ht"], "ttc": raw["total_ttc"],
                          "financial_breakdown": deepcopy(raw)}]}
    original = deepcopy(result)
    with app.app_context():
        quote_id = save_quote("HSQ-CENTS", "photovoltaic", {}, {"name": "Client test"}, result)
        stored = get_quote(quote_id)
        row = get_db().execute("SELECT amount_ht, amount_ttc, result_json, financial_breakdown_json, quote_snapshot_json FROM quote_requests WHERE id=?", (quote_id,)).fetchone()
        financial = json.loads(row["financial_breakdown_json"])
        assert money(row["amount_ht"]) == money(financial["total_ht"]) == Decimal("10000.01")
        assert money(row["amount_ttc"]) == money(financial["total_ttc"]) == Decimal("10000.03")
        assert money(financial["vat"]) == Decimal("0.02")
        assert json.loads(row["result_json"])["financial_breakdown"] == financial
        assert json.loads(row["quote_snapshot_json"])["financial_breakdown"] == financial
        public = routes.build_public_quote_payload(stored, {"currency": "DH"})
        assert public["recommended_offer"]["price_ttc_label"] == "10 000,03 DH"
        sql_before = tuple(row)
    client = app.test_client()
    with client.session_transaction() as session:
        session["admin_user"] = "test"
    html = client.get("/admin/devis").get_data(as_text=True)
    assert '10 000,03 DH' in html
    assert '10 000,01 DH' in html
    assert result == original
    with app.app_context():
        assert tuple(get_db().execute("SELECT amount_ht, amount_ttc, result_json, financial_breakdown_json, quote_snapshot_json FROM quote_requests WHERE id=?", (quote_id,)).fetchone()) == sql_before


@pytest.mark.parametrize("project,data", [
    ("photovoltaic", {"phase": "monophase", "meter_type": "numerique", "monthly_consumption_kwh": 1000}),
    ("hybrid", {"monthly_consumption_kwh": 450}),
    ("pumping", {"pump_existing": True, "existing_pump_cv": 2}),
])
def test_real_simulations_persist_the_same_cents_as_the_api_and_admin(tmp_path, project, data):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / f"{project}-cents.db")})
    with app.app_context():
        db = get_db()
        db.execute("UPDATE products SET sale_price=100.005 WHERE category='panels'")
        db.commit()
    client = app.test_client()
    with patch("app.routes._notify_quote_created_safely"):
        response = client.post("/api/calculate", json={"project": project, "data": data})
    assert response.status_code == 200
    api = response.get_json()
    with app.app_context():
        stored = get_quote(api["quote_id"])
    financial = api["financial_breakdown"]
    assert money(financial["total_ttc"]) == money(financial["total_ht"]) + money(financial["vat"])
    assert financial["total_ht"] == stored["amount_ht"]
    assert financial["total_ttc"] == stored["amount_ttc"]
    assert financial["vat"] == stored["financial_breakdown"]["vat"]
    with client.session_transaction() as session:
        session["admin_user"] = "test"
    soup = BeautifulSoup(client.get("/admin/devis").data, "html.parser")
    assert soup.select_one('td[data-label="Total TTC"]').get_text(strip=True) == format_currency(stored["amount_ttc"])
    assert soup.select_one('td[data-label="Total HT"]').get_text(strip=True) == format_currency(stored["amount_ht"])


def test_engine_product_line_preserves_cents_instead_of_rounding_to_whole_dirhams():
    from app.calculators import CalculationEngine
    row = CalculationEngine._line({"sale_price": "1.045", "category": "panels"}, 3, "Panneaux")
    assert money(row["unit_price"]) == Decimal("1.05")
    assert money(row["total_price"]) == Decimal("3.15")
