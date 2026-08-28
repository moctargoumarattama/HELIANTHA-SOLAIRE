import json

import pytest

from app import create_app
from app.calculators import CalculationEngine, ValidationError
from app.parameter_views import enrich_parameter


def test_pumping_calculation_is_coherent():
    result = CalculationEngine().calculate("pumping", {
        "water_need": 30, "depth": 55, "elevation": 15, "distance": 80, "hours": 6
    })
    assert result["title"] == "Pompage solaire"
    assert len(result["offers"]) == 3
    assert result["offers"][1]["recommended"] is True
    assert result["offers"][1]["ttc"] > result["offers"][1]["ht"]


def test_ev_warns_when_requested_power_is_too_high():
    result = CalculationEngine().calculate("ev", {
        "available_power": 6, "charger_power": 22, "vehicle_battery": 60
    })
    assert result["warnings"]


def test_unknown_project_is_rejected():
    with pytest.raises(ValidationError):
        CalculationEngine().calculate("unknown", {})


def test_api_health_and_calculate(tmp_path):
    database = tmp_path / "test.db"
    client = create_app({"TESTING": True, "DATABASE": str(database)}).test_client()
    assert client.get("/health").status_code == 200
    response = client.post("/api/calculate", json={"project": "thermal", "data": {"people": 5}})
    assert response.status_code == 200
    assert response.get_json()["quote_number"].startswith("HSQ-")


def test_calculate_recovers_from_an_empty_database(tmp_path):
    database = tmp_path / "empty-after-startup.db"
    app = create_app({"TESTING": True, "DATABASE": str(database)})
    database.unlink()

    response = app.test_client().post(
        "/api/calculate",
        json={
            "project": "ongrid",
            "data": {"monthly_kwh": 600, "city": "Marrakech"},
            "contact": {"name": "Client test", "phone": "0600000000"},
        },
    )

    assert response.status_code == 200
    with app.app_context():
        from app.db import get_db

        count = get_db().execute("SELECT COUNT(*) FROM quote_requests").fetchone()[0]
        assert count == 1


def test_quote_saves_structured_calculation_detail(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "detail.db")})
    response = app.test_client().post(
        "/api/calculate",
        json={"project": "offgrid", "data": {"daily_kwh": 12, "peak_kw": 4, "city": "Agadir"}},
    )

    assert response.status_code == 200
    with app.app_context():
        from app.db import get_db

        row = get_db().execute("SELECT calculation_detail_json FROM quote_requests").fetchone()
        detail = json.loads(row["calculation_detail_json"])
        assert detail["inputs"]["daily_kwh"] == 12
        assert detail["parameters_used"]
        assert detail["intermediate_results"]
        assert detail["selected_equipment"]
        assert detail["calculation_version"] == "1.0"


def test_financial_breakdown_ht_plus_vat_equals_ttc():
    result = CalculationEngine().calculate("ongrid", {"monthly_kwh": 700, "city": "Marrakech", "roof_area": 80})
    financial = result["financial_breakdown"]
    assert financial["total_ht"] + financial["vat"] == financial["total_ttc"]
    assert financial["categories"]


def test_admin_routes_are_protected(tmp_path):
    client = create_app({"TESTING": True, "DATABASE": str(tmp_path / "admin.db")}).test_client()
    response = client.get("/admin/")
    assert response.status_code == 302
    assert "/admin/login" in response.headers["Location"]


def test_old_quote_keeps_snapshot_prices_after_catalog_change(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "snapshot-price.db")})
    client = app.test_client()
    response = client.post(
        "/api/calculate",
        json={"project": "ongrid", "data": {"monthly_kwh": 650, "city": "Casablanca", "roof_area": 60}},
    )
    assert response.status_code == 200
    quote = response.get_json()
    panel_line = next(item for item in quote["selected_equipment"] if item["category"] == "panels")

    with app.app_context():
        from app.db import get_db

        db = get_db()
        db.execute("UPDATE products SET sale_price = ? WHERE reference = ?", (950, panel_line["reference"]))
        db.commit()
        saved = json.loads(db.execute("SELECT result_json FROM quote_requests").fetchone()["result_json"])

    saved_panel_line = next(item for item in saved["selected_equipment"] if item["category"] == "panels")
    assert saved_panel_line["unit_price"] == panel_line["unit_price"]


def test_old_quote_keeps_technical_parameters_after_parameter_change(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "snapshot-param.db")})
    response = app.test_client().post(
        "/api/calculate",
        json={"project": "offgrid", "data": {"daily_kwh": 9, "peak_kw": 3, "city": "Rabat"}},
    )
    assert response.status_code == 200

    with app.app_context():
        from app.db import get_db

        db = get_db()
        saved_before = json.loads(db.execute("SELECT technical_parameters_json FROM quote_requests").fetchone()["technical_parameters_json"])
        db.execute("UPDATE calculation_parameters SET value = ? WHERE key = 'battery_dod'", (0.5,))
        db.commit()
        saved_after = json.loads(db.execute("SELECT technical_parameters_json FROM quote_requests").fetchone()["technical_parameters_json"])

    assert saved_before["battery_dod"]["value"] == saved_after["battery_dod"]["value"]


def test_deactivated_product_is_not_selected_for_new_quote(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "inactive-product.db")})
    with app.app_context():
        from app.db import get_db

        db = get_db()
        db.execute("UPDATE products SET active = 0 WHERE reference = 'PV-590-HS'")
        db.commit()

    response = app.test_client().post(
        "/api/calculate",
        json={"project": "ongrid", "data": {"monthly_kwh": 600, "city": "Agadir", "roof_area": 80}},
    )

    assert response.status_code == 200
    references = {item["reference"] for item in response.get_json()["selected_equipment"]}
    assert "PV-590-HS" not in references
    assert "PV-550-HS" in references


def test_technical_warning_is_saved(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "warning.db")})
    response = app.test_client().post(
        "/api/calculate",
        json={"project": "ev", "data": {"available_power": 6, "charger_power": 22, "vehicle_battery": 60}},
    )
    assert response.status_code == 200

    with app.app_context():
        from app.db import get_db

        detail = json.loads(get_db().execute("SELECT calculation_detail_json FROM quote_requests").fetchone()["calculation_detail_json"])

    assert any(item["code"] == "EV_POWER_NOT_FEASIBLE" for item in detail["warnings"])


def test_admin_pages_render_after_login(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "admin-render.db")})
    client = app.test_client()
    client.post(
        "/api/calculate",
        json={"project": "thermal", "data": {"people": 4}, "contact": {"name": "Client Admin"}},
    )
    login = client.post("/admin/login", data={"password": "heliantha2026"})
    assert login.status_code == 302

    paths = [
        "/admin/",
        "/admin/devis",
        "/admin/devis/1",
        "/admin/devis/1/pdf",
        "/admin/prospects",
        "/admin/catalogue",
        "/admin/catalogue/new",
        "/admin/parametres-calcul",
        "/admin/tarification",
        "/admin/parametres",
        "/admin/utilisateurs",
    ]
    for path in paths:
        assert client.get(path).status_code == 200


def test_admin_users_crud_and_direction_protection(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "admin-users.db")})
    client = app.test_client()
    client.post("/admin/login", data={"password": "heliantha2026"})

    create_response = client.post(
        "/admin/utilisateurs",
        data={
            "action": "save",
            "email": "commercial1@heliantha.ma",
            "password": "secret123",
        },
        follow_redirects=False,
    )
    assert create_response.status_code == 302

    with app.app_context():
        from app.db import get_db

        db = get_db()
        created = db.execute("SELECT * FROM users WHERE username = 'commercial1@heliantha.ma'").fetchone()
        direction = db.execute("SELECT * FROM users WHERE role = 'Direction'").fetchone()
        assert created is not None
        assert created["display_name"] == "commercial1@heliantha.ma"
        assert created["role"] == "Commercial"
        assert direction is not None

    user_id = created["id"]
    update_response = client.post(
        "/admin/utilisateurs",
        data={
            "action": "save",
            "user_id": user_id,
            "email": "commercial-terrain@heliantha.ma",
            "password": "",
        },
        follow_redirects=False,
    )
    assert update_response.status_code == 302

    with app.app_context():
        from app.db import get_db

        updated = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        assert updated["username"] == "commercial-terrain@heliantha.ma"
        assert updated["display_name"] == "commercial-terrain@heliantha.ma"
        assert updated["role"] == "Commercial"

    delete_response = client.post(
        "/admin/utilisateurs",
        data={"action": "delete", "user_id": user_id},
        follow_redirects=False,
    )
    assert delete_response.status_code == 302

    with app.app_context():
        from app.db import get_db

        deleted = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        assert deleted is None

        direction_row = get_db().execute("SELECT * FROM users WHERE role = 'Direction'").fetchone()
        blocked = client.post(
            "/admin/utilisateurs",
            data={"action": "delete", "user_id": direction_row["id"]},
            follow_redirects=False,
        )
        assert blocked.status_code == 200


def test_old_reference_admin_route_redirects_to_calculation_parameters(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "admin-reference-redirect.db")})
    client = app.test_client()
    client.post("/admin/login", data={"password": "heliantha2026"})

    response = client.get("/admin/referentiel-technique", follow_redirects=False)

    assert response.status_code == 302
    assert "/admin/parametres-calcul" in response.headers["Location"]


def test_admin_menu_no_longer_shows_reference_link(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "admin-menu-clean.db")})
    client = app.test_client()
    client.post("/admin/login", data={"password": "heliantha2026"})

    html = client.get("/admin/").get_data(as_text=True)

    assert "Référentiel technique" not in html


def test_percent_parameter_edit_is_stored_as_decimal_and_history_is_saved(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "parameter-edit.db")})
    client = app.test_client()
    client.post("/admin/login", data={"password": "heliantha2026"})

    with app.app_context():
        from app.db import get_db

        param = get_db().execute("SELECT id FROM calculation_parameters WHERE key = 'battery_dod'").fetchone()

    response = client.post(
        "/admin/parametres-calcul",
        data={
            "parameter_id": param["id"],
            "display_value": "85",
            "source_type": "heliantha",
            "source_name": "Responsable technique HeliAntha",
            "source_reference": "Validation interne",
            "validated_by": "Admin",
            "validated_at": "2026-08-26",
            "change_comment": "Valeur validée pour test",
            "active": "on",
        },
    )

    assert response.status_code == 302
    with app.app_context():
        from app.db import get_db

        db = get_db()
        updated = db.execute("SELECT value, source_type FROM calculation_parameters WHERE key = 'battery_dod'").fetchone()
        history = db.execute("SELECT old_value, new_value, change_comment FROM calculation_parameter_history").fetchone()

    assert updated["value"] == pytest.approx(0.85)
    assert updated["source_type"] == "heliantha"
    assert history["old_value"] == pytest.approx(0.80)
    assert history["new_value"] == pytest.approx(0.85)
    assert history["change_comment"] == "Valeur validée pour test"


def test_locked_physical_constant_cannot_be_edited(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "locked-param.db")})
    client = app.test_client()
    client.post("/admin/login", data={"password": "heliantha2026"})

    with app.app_context():
        from app.db import get_db

        param = get_db().execute("SELECT id FROM calculation_parameters WHERE key = 'gravity'").fetchone()

    response = client.post(
        "/admin/parametres-calcul",
        data={
            "parameter_id": param["id"],
            "display_value": "10",
            "source_type": "physical_constant",
            "active": "on",
        },
    )

    assert response.status_code == 403
    with app.app_context():
        from app.db import get_db

        row = get_db().execute("SELECT value, editable FROM calculation_parameters WHERE key = 'gravity'").fetchone()
        history_count = get_db().execute("SELECT COUNT(*) FROM calculation_parameter_history").fetchone()[0]

    assert row["value"] == pytest.approx(9.81)
    assert row["editable"] == 0
    assert history_count == 0


def test_parameter_source_is_kept_in_quote_snapshot(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "source-snapshot.db")})
    response = app.test_client().post(
        "/api/calculate",
        json={"project": "offgrid", "data": {"daily_kwh": 8, "peak_kw": 3, "city": "Agadir"}},
    )

    assert response.status_code == 200
    with app.app_context():
        from app.db import get_db

        detail = json.loads(get_db().execute("SELECT calculation_detail_json FROM quote_requests").fetchone()["calculation_detail_json"])

    battery_dod = detail["parameters_used"]["battery_dod"]
    assert battery_dod["display_name"] == "Part utilisable par defaut de la batterie"
    assert battery_dod["source_type"] == "heliantha"
    assert battery_dod["source_badge"] == "✅ HeliAntha"


def test_human_parameter_formatting_keeps_integer_units():
    panel = enrich_parameter({
        "key": "pv_panel_default_w",
        "name": "Puissance panneau",
        "display_kind": "power_w",
        "value": 590,
        "unit": "W",
        "category": "Photovoltaique",
        "source_type": "heliantha",
        "editable": 1,
        "active": 1,
    })
    water = enrich_parameter({
        "key": "water_density",
        "name": "Densite eau",
        "display_kind": "density",
        "value": 1000,
        "unit": "kg/m3",
        "category": "Pompage",
        "source_type": "physical_constant",
        "editable": 0,
        "active": 1,
    })

    assert panel["display_value"] == "590 W"
    assert water["display_value"] == "1000 kg/m³"
