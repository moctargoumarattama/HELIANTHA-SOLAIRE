"""Regressions for explicit units, real catalogue facts and indicative PV sizing."""

import sqlite3
from unittest.mock import patch

import pytest
from flask import Flask

from app.services.ai_service import (
    find_catalog_products,
    is_quick_solar_power_query,
    quick_solar_power_response,
)


def user(content):
    return {"role": "user", "content": content}


@pytest.fixture
def panels():
    return [
        {
            "id": 101, "reference": "LOCAL-PV-A", "category": "panels",
            "brand": "Marque A", "model": "Modèle A", "name": "Marque A Modèle A",
            "power_w": 590, "price": 480, "currency": "DH", "en_stock": True,
            "datasheet_url": "https://example.com/panel-a.pdf", "source": "local_sqlite",
        },
        {
            "id": 202, "reference": "LOCAL-PV-B", "category": "panels",
            "brand": "Marque B", "model": "Modèle B", "name": "Marque B Modèle B",
            "power_w": 725, "price": 600, "currency": "MAD", "en_stock": True,
            "datasheet_url": "https://example.com/panel-b.pdf", "source": "local_sqlite",
        },
    ]


@pytest.mark.parametrize("text,total_w,total_kw", [
    ("590 Wc * 5", "2 950", "2.95"),
    ("590,5 Wc * 5", "2 952.5", "2.9525"),
    ("590.5 W x 5", "2 952.5", "2.9525"),
    ("0,5905 kWc × 5", "2 952.5", "2.9525"),
    ("0.59 KW X 5", "2 950", "2.95"),
    ("5 panneaux solaires de 590,5 Wc", "2 952.5", "2.9525"),
    ("5 × 0,59 kWc", "2 950", "2.95"),
])
def test_multiplication_uses_decimal_and_explicit_unit(text, total_w, total_kw):
    response = quick_solar_power_response([user(text)])
    assert f"= {total_w} Wc" in response["content"]
    assert f"soit {total_kw} kWc" in response["content"]


def test_only_latest_user_message_supplies_math():
    messages = [user("590 Wc * 5"), {"role": "assistant", "content": "715 Wc * 100"}]
    assert "2 950 Wc" in quick_solar_power_response(messages)["content"]
    messages.append(user("Bonjour"))
    assert quick_solar_power_response(messages) is None


@pytest.mark.parametrize("text,expected", [
    ("Combien de panneaux pour 10 kW ?", "10 000 Wc"),
    ("Combien de panneaux solaires pour 10kw ?", "10 000 Wc"),
    ("Combien faut-il de panneaux pour 8000 Wc ?", "8 000 Wc"),
    ("Nombre de panneaux photovoltaïques pour 5kw", "5 000 Wc"),
    ("Combien de panneaux faut-il pour 8000 Wc ?", "8 000 Wc"),
    ("Combien de panneaux pour 50 Wc ?", "50 Wc"),
    ("Combien de panneaux pour 10 ?", "10 000 Wc"),
    ("Combien de panneaux pour 10 000 Wc ?", "10 000 Wc"),
])
def test_target_is_scaled_by_unit_and_supports_french_variants(panels, text, expected):
    response = quick_solar_power_response([user(text)], products=panels)
    assert f"({expected})" in response["content"]
    assert [item["id"] for item in response["suggested_products"]] == [101, 202]
    assert "480 DH HT/unité" in response["content"]
    assert "600 DH HT/unité" in response["content"]
    assert "TEST-CS" not in response["content"]


@pytest.mark.parametrize("text,quantity", [
    ("Combien de panneaux pour 1770 Wc ?", 3),
    ("Combien de panneaux pour 0,5901 kWc ?", 2),
    ("Combien de panneaux pour 50 Wc ?", 1),
])
def test_ceil_handles_exact_boundary_and_small_targets(panels, text, quantity):
    response = quick_solar_power_response([user(text)], products=panels[:1])
    assert f"- {quantity} × 590 Wc" in response["content"]


@pytest.mark.parametrize("text", [
    "Combien de panneaux pour 1200 DH ?",
    "590 kWh * 5",
    "Batterie 10 kWh",
])
def test_energy_and_money_never_become_power(text, panels):
    assert quick_solar_power_response([user(text)], products=panels) is None


@pytest.mark.parametrize("text", [
    "Combien de panneaux pour 1000 kWh ?",
    "Combien de panneaux pour 10kWh ?",
])
def test_energy_target_without_period_requires_clarification(text, panels):
    response = quick_solar_power_response([user(text)], products=panels)
    assert "Précisez une seule période" in response["content"]
    assert "puissance cible" not in response["content"]


@pytest.mark.parametrize("text", [
    "Combien de panneaux pour -50 Wc ?",
    "590 Wc * -5",
    "-5 panneaux de 590 Wc",
    "1e100 WH",
    "Combien de panneaux pour " + "9" * 150 + " Wc ?",
    "Ma facture est de " + "9" * 150 + " DH par mois",
    "590 Wc * " + "9" * 150,
])
def test_negative_and_excessive_values_return_clarification_without_exception(text, panels):
    response = quick_solar_power_response([user(text)], products=panels)
    assert "strictement positive" in response["content"]
    assert "valeur usuelle" in response["content"]


@pytest.mark.parametrize("field,value", [
    ("category", "inverters"), ("power_w", 0), ("price", 0),
    ("en_stock", False), ("active", 0), ("demo", 1), ("currency", "EUR"),
])
def test_ineligible_panels_are_never_recommended(panels, field, value):
    unavailable = dict(panels[0], **{field: value})
    response = quick_solar_power_response([user("Combien de panneaux pour 10 kw ?")], products=[unavailable])
    assert response["suggested_products"] == []
    assert "Aucun panneau réel" in response["content"]
    assert "LOCAL-PV-A" not in response["content"]


def test_missing_database_is_not_created_by_fallback(tmp_path):
    database = tmp_path / "unused.db"
    app = Flask(__name__)
    app.config["DATABASE"] = str(database)
    with app.app_context(), patch("app.db.list_products") as list_products:
        response = quick_solar_power_response([user("Combien de panneaux pour 10 kw ?")], products=[])
    list_products.assert_not_called()
    assert not database.exists()
    assert response["suggested_products"] == []


def test_fallback_normalizes_only_real_available_database_rows(tmp_path, panels):
    database = tmp_path / "catalogue.db"
    database.touch()
    app = Flask(__name__)
    app.config["DATABASE"] = str(database)
    row = dict(panels[0], sale_price=491.25, active=1, demo=0, stock=3)
    row.pop("price")
    row.pop("name")
    row["description"] = "Module vérifié"
    unavailable = dict(row, id=999, reference="UNAVAILABLE", stock=0)
    with app.app_context(), patch("app.db.list_products", return_value=[row, unavailable]) as list_products:
        response = quick_solar_power_response([user("Combien de panneaux pour 10 kw ?")])
    list_products.assert_called_once_with(category="panels", active="1", stock="available")
    assert len(response["suggested_products"]) == 1
    assert response["suggested_products"][0]["id"] == 101
    assert response["suggested_products"][0]["price"] == 491.25
    assert response["suggested_products"][0]["datasheet_url"] == row["datasheet_url"]
    assert "491.25 DH HT/unité" in response["content"]


def test_injected_catalogue_is_used_without_database_read(panels):
    with patch("app.db.list_products") as list_products:
        response = quick_solar_power_response([user("Nombre de panneaux pour 10kw")], products=panels)
    list_products.assert_not_called()
    assert response["suggested_products"][0]["reference"] == panels[0]["reference"]


@pytest.mark.parametrize("text,kwh_month,target", [
    ("Ma facture de 1200 DH par mois", "923.08", "6.8"),
    ("Facture de 1000 kWh", "1 000", "7.4"),
    ("1000 kWh par mois", "1 000", "7.4"),
    ("Consommation de 30 kWh par jour", "900", "6.7"),
    ("30 kWh/j", "900", "6.7"),
])
def test_consumption_pre_sizing_states_tariff_days_psh_and_validation(panels, text, kwh_month, target):
    response = quick_solar_power_response([user(text)], products=panels)
    content = response["content"]
    assert f"{kwh_month} kWh/mois" in content
    assert f"{target} kWc" in content
    assert "30 jours" in content
    assert "4.5 heures" in content
    assert "Prédimensionnement solaire indicatif" in content
    assert "devis officiel" in content
    assert "On-Grid ou Hybride" in content
    assert "LiFePO4 de 5 à 10 kWh" in content
    assert "compatibilité vérifiée" in content
    if "DH" in text:
        assert "tarif indicatif de 1.30 DH/kWh" in content
    assert [item["id"] for item in response["suggested_products"]] == [101, 202]


def test_annual_consumption_requires_period_clarification(panels):
    response = quick_solar_power_response([user("Consommation de 12000 kWh par an")], products=panels)
    assert "Précisez une seule période" in response["content"]
    assert "puissance cible" not in response["content"]


@pytest.mark.parametrize("text", [
    "Batterie de 10 kWh pour ma consommation de 1000 kWh par mois",
    "Ma consommation de 1000 kWh par mois et une batterie de 10 kWh",
    "Panneau à 480 DH ; ma facture est de 1300 DH par mois",
])
def test_battery_capacity_and_product_price_do_not_replace_consumption(text, panels):
    response = quick_solar_power_response([user(text)], products=panels)
    assert "1 000 kWh/mois" in response["content"]
    assert "7.4 kWc" in response["content"]


def test_pumping_consumption_does_not_recommend_household_hybrid_system(panels):
    response = quick_solar_power_response([user("Ma pompe consomme 30 kWh/j")], products=panels)
    assert "plaque moteur" in response["content"]
    assert "HMT" in response["content"]
    assert "LiFePO4" not in response["content"]
    assert "On-Grid" not in response["content"]


def test_numerical_intent_detector_never_reads_database():
    with patch("app.db.list_products") as list_products:
        assert is_quick_solar_power_query([user("590,5 Wc × 5")])
        assert is_quick_solar_power_query([user("Facture de 1200 DH par mois")])
        assert not is_quick_solar_power_query([user("Batterie 10 kWh")])
    list_products.assert_not_called()


def test_catalogue_products_include_real_technical_metadata_without_write(tmp_path):
    database = tmp_path / "readonly-products.db"
    with sqlite3.connect(database) as connection:
        connection.execute("""CREATE TABLE products (
            id INTEGER, reference TEXT, category TEXT, brand TEXT, model TEXT,
            description TEXT, power_w REAL, power_kw REAL, capacity_kwh REAL,
            voltage REAL, sale_price REAL, preferred INTEGER, priority INTEGER,
            datasheet_url TEXT, active INTEGER, demo INTEGER, stock REAL, currency TEXT
        )""")
        connection.execute("""INSERT INTO products VALUES (
            42, 'SQLITE-REAL', 'panels', 'Marque réelle', 'Modèle réel', 'Module 725 W',
            725, NULL, NULL, NULL, 605.25, 1, 2, 'https://example.com/real.pdf', 1, 0, 7, 'MAD'
        )""")
        connection.execute("""INSERT INTO products SELECT
            43, 'SQLITE-DEMO', category, brand, model, description, power_w, power_kw,
            capacity_kwh, voltage, sale_price, preferred, priority, datasheet_url, active, 1, stock, currency
            FROM products WHERE id = 42""")
    before = database.read_bytes()
    app = Flask(__name__)
    app.config["DATABASE"] = str(database)
    with app.app_context():
        products = find_catalog_products([user("Je veux des panneaux solaires")])
    assert database.read_bytes() == before
    assert len(products) == 1
    product = products[0]
    assert product["id"] == 42
    assert product["category"] == "panels"
    assert product["power_w"] == 725
    assert product["brand"] == "Marque réelle"
    assert product["model"] == "Modèle réel"
    assert product["datasheet_url"] == "https://example.com/real.pdf"
    assert product["price"] == 605.25
