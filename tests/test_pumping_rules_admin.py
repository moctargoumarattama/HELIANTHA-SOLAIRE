from app import create_app


def test_admin_pumping_rules_page_is_compact_and_hides_variators(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "pumping-admin-page.db")})
    client = app.test_client()
    client.post("/admin/login", data={"password": "heliantha2026"})

    html = client.get("/admin/regles-pompage").get_data(as_text=True)

    assert "Variateurs" not in html
    assert "Réf. panneau" not in html
    assert "Prix panneau HT" not in html
    assert "Réf. variateur" not in html
    assert "Prix variateur HT" not in html
    assert html.count('data-section="pump_configuration"') == 10
    assert "Monophasé 2 CV → 3 CV" in html
    assert "0 CV \u2192 3 CV" not in html
    assert "+ Ajouter une règle" in html
    assert "Structures photovoltaïques" in html
    assert "Coffrets de protection" in html
    assert "Câblage DC et accessoires" in html
    assert "Installation et mise en service" in html
    assert "TVA Pompage solaire" in html


def test_admin_pumping_rule_can_be_modified(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "pumping-admin-edit.db")})
    client = app.test_client()
    client.post("/admin/login", data={"password": "heliantha2026"})

    with app.app_context():
        from app.db import get_db

        row = get_db().execute(
            "SELECT id, pump_cv, panel_count, panel_power_w, drive_power_kw, phase, drive_brand FROM pumping_solar_rules WHERE rule_key = 'pump-15cv'"
        ).fetchone()

    response = client.post(
        "/admin/regles-pompage",
        data={
            "action": "save_rule",
            "rule_id": row["id"],
            "rule_type": "pump_configuration",
            "field_pump_cv": row["pump_cv"],
            "field_panel_count": 25,
            "field_panel_power_w": row["panel_power_w"],
            "field_drive_power_kw": row["drive_power_kw"],
            "field_phase": row["phase"],
            "field_drive_brand": row["drive_brand"],
            "active": "on",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    with app.app_context():
        from app.db import get_db

        updated = get_db().execute(
            "SELECT panel_count FROM pumping_solar_rules WHERE rule_key = 'pump-15cv'"
        ).fetchone()

    assert int(updated["panel_count"]) == 25


def test_admin_pumping_rule_can_be_added(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "pumping-admin-add.db")})
    client = app.test_client()
    client.post("/admin/login", data={"password": "heliantha2026"})

    response = client.post(
        "/admin/regles-pompage",
        data={
            "action": "add_rule",
            "rule_type": "pump_configuration",
            "title": "25 CV",
            "active": "on",
            "field_pump_cv": "25",
            "field_panel_count": "32",
            "field_panel_power_w": "715",
            "field_drive_power_kw": "18",
            "field_phase": "triphase",
            "field_drive_brand": "VEICHI",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    with app.app_context():
        from app.db import get_db

        created = get_db().execute(
            "SELECT pump_cv, panel_count, panel_power_w, drive_brand FROM pumping_solar_rules WHERE pump_cv = 25 ORDER BY id DESC LIMIT 1"
        ).fetchone()

    assert created is not None
    assert float(created["pump_cv"]) == 25
    assert int(created["panel_count"]) == 32
    assert int(created["panel_power_w"]) == 715
    assert created["drive_brand"] == "VEICHI"
