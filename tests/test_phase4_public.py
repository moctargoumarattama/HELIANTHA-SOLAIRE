import json
from pathlib import Path

from app import create_app
from app.public_presenters import build_public_quote_payload, company_profile


def create_quote(client, project="ongrid", data=None):
    response = client.post(
        "/api/calculate",
        json={
            "project": project,
            "data": data or {"monthly_kwh": 900, "city": "Casablanca", "roof_area": 100},
            "contact": {"name": "Client Premium", "phone": "0600000000", "location": "Casablanca"},
        },
    )
    assert response.status_code == 200
    return response.get_json()


def test_public_homepage_renders_premium_sections(tmp_path):
    client = create_app({"TESTING": True, "DATABASE": str(tmp_path / "public-home.db")}).test_client()

    response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Votre projet solaire commence ici." in html
    assert "Quel est votre projet ?" in html
    assert "Comment Ã§a marche" not in html


def test_calculate_returns_public_url_and_public_page_uses_snapshot_prices(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "public-snapshot.db")})
    client = app.test_client()
    created = create_quote(client)

    with app.app_context():
        from app.db import get_db, get_quote_by_number, list_company_settings

        quote = get_quote_by_number(created["quote_number"])
        company = company_profile(list_company_settings())
        initial_payload = build_public_quote_payload(quote, company)

        get_db().execute("UPDATE products SET sale_price = sale_price + 5000")
        get_db().commit()

    response = client.get(created["public_url"])
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert created["quote_number"] in created["public_url"]
    assert initial_payload["recommended_offer"]["price_ttc_label"] in html


def test_public_offer_selection_is_saved_and_reused(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "public-offer.db")})
    client = app.test_client()
    created = create_quote(client, "offgrid", {"daily_kwh": 12, "peak_kw": 4, "city": "Marrakech"})

    response = client.post(
        f"/api/simulations/{created['quote_number']}/select-offer",
        json={"level": "essential"},
    )
    assert response.status_code == 200

    with app.app_context():
        from app.db import get_quote_by_number, list_company_settings

        quote = get_quote_by_number(created["quote_number"])
        payload = build_public_quote_payload(quote, company_profile(list_company_settings()))

    assert quote["selected_offer_level"] == "essential"
    assert payload["recommended_offer"]["level"] == "essential"


def test_public_pumping_existing_pump_payload_keeps_rule_fields_only(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "public-pump-rule.db")})
    client = app.test_client()
    created = create_quote(client, "pumping", {"pump_existing": True, "existing_pump_cv": 15})

    with app.app_context():
        from app.db import get_quote_by_number, list_company_settings

        quote = get_quote_by_number(created["quote_number"])
        payload = build_public_quote_payload(quote, company_profile(list_company_settings()))

    assert payload["final_results"]["pump_rule_mode"] == "existing_pump_cv"
    assert "flow_m3_h" not in payload["final_results"]
    assert "hmt_m" not in payload["final_results"]
    assert "flow_m3_h" not in payload["offers"][0]["diagram"]
    assert "hmt_m" not in payload["offers"][0]["diagram"]
    assert all(
        "débit" not in str(item.get("label", "")).lower()
        and "hauteur" not in str(item.get("label", "")).lower()
        for item in payload["metrics"]
    )


def test_public_pumping_existing_pump_page_hides_hydraulic_text(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "public-pump-page.db")})
    client = app.test_client()
    created = create_quote(client, "pumping", {"pump_existing": True, "existing_pump_cv": 15})

    response = client.get(created["public_url"])
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "flow_m3_h" not in html
    assert "hmt_m" not in html
    assert "Débit" not in html
    assert "Hauteur de pompage" not in html
    assert "Le champ photovoltaïque alimente le variateur puis la pompe, selon la configuration HeliAntha retenue." not in html


def test_public_pumping_existing_pump_step_uses_compact_picker():
    app_js = Path("static/js/app.js").read_text(encoding="utf-8")
    assert 'type: "pump-cv-picker"' in app_js
    assert "renderPumpCvStep" in app_js
    assert "pump-cv-sheet" in app_js
    assert 'choiceField("existing_pump_cv"' not in app_js


def test_public_pumping_existing_pump_picker_has_ten_values():
    app_js = Path("static/js/app.js").read_text(encoding="utf-8")
    for value in ["2 CV", "3 CV", "5,5 CV", "7,5 CV", "10 CV", "15 CV", "20 CV", "30 CV", "40 CV", "50 CV"]:
        assert value in app_js


def test_public_pumping_existing_pump_wizard_text_is_clean():
    app_js = Path("static/js/app.js").read_text(encoding="utf-8")

    assert "Voir mon estimation" in app_js
    assert "Vérifiez vos informations" in app_js
    assert "HeliAntha" in app_js
    assert "estimation" in app_js
    assert "Les puissances proposées sont indicatives" not in app_js
    assert "Toutes les valeurs sont modifiables" not in app_js
    assert "Le moteur réel travaille" not in app_js
    assert "Calculer ma solution" not in app_js
    assert "Choisir ce projet" not in app_js


def test_visit_request_is_saved_and_updates_quote_status(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "public-visit.db")})
    client = app.test_client()
    created = create_quote(client, "pumping", {"pump_existing": False, "flow_m3_h": 12, "hmt_m": 80})

    response = client.post(
        f"/api/simulations/{created['quote_number']}/visit",
        json={
            "preferred_date": "2026-09-02",
            "time_slot": "Matin",
            "address": "Douar test, Agadir",
            "phone": "0600000000",
            "comment": "Visite souhaitÃ©e en matinÃ©e.",
        },
    )

    assert response.status_code == 200
    with app.app_context():
        from app.db import get_db, get_quote_by_number

        quote = get_quote_by_number(created["quote_number"])
        visit = get_db().execute("SELECT * FROM visit_requests WHERE quote_number = ?", (created["quote_number"],)).fetchone()

    assert quote["status"] == "Visite programmee"
    assert visit["address"] == "Douar test, Agadir"
    assert visit["time_slot"] == "Matin"


def test_visit_panel_bottom_button_is_bound_without_top_toggle(tmp_path):
    app_js = Path("static/js/public-result.js").read_text(encoding="utf-8")

    assert 'if (!panel || !form) return;' in app_js
    assert 'if (!panel || !toggle || !form) return;' not in app_js
    assert '#visit-toggle-bottom' in app_js


def test_visit_request_appears_in_admin_prospects_as_technical_visit(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "public-visit-admin.db")})
    client = app.test_client()
    created = create_quote(client, "pumping", {"pump_existing": False, "flow_m3_h": 12, "hmt_m": 80})

    client.post(
        f"/api/simulations/{created['quote_number']}/visit",
        json={
            "preferred_date": "2026-09-02",
            "time_slot": "Matin",
            "address": "Douar test, Agadir",
            "phone": "0600000000",
            "comment": "Visite souhaitee en matinnee.",
        },
    )
    client.post("/admin/login", data={"password": "heliantha2026"})

    response = client.get("/admin/prospects")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'href="/admin/devis/1#visite-technique"' in html
    assert "Visite programmée" in html

    detail = client.get("/admin/devis/1")
    detail_html = detail.get_data(as_text=True)
    assert detail.status_code == 200
    assert 'id="visite-technique"' in detail_html
    assert "Visite demandée" in detail_html


def test_admin_quote_visit_section_groups_repeated_requests(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "public-visit-grouped.db")})
    client = app.test_client()
    created = create_quote(client, "pumping", {"pump_existing": False, "flow_m3_h": 12, "hmt_m": 80})
    visit_payload = {
        "preferred_date": "2026-09-02",
        "time_slot": "Matin",
        "address": "Douar test, Agadir",
        "phone": "0600000000",
        "comment": "Visite souhaitee en matinnee.",
    }

    for _ in range(3):
        response = client.post(f"/api/simulations/{created['quote_number']}/visit", json=visit_payload)
        assert response.status_code == 200

    client.post("/admin/login", data={"password": "heliantha2026"})
    detail = client.get("/admin/devis/1#visite-technique")

    assert detail.status_code == 200
    html = detail.get_data(as_text=True)
    assert "Une seule fiche claire, sans répétition." in html
    assert "Cette même demande a été envoyée 3 fois." in html
    assert "Total reçu" not in html
    assert "Demandes uniques" not in html
    assert "Répétitions masquées" not in html
    assert html.count("Douar test, Agadir") == 1
    assert html.count("Visite souhaitee en matinnee.") == 1


def test_public_print_route_renders_from_snapshot(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "public-print.db")})
    client = app.test_client()
    created = create_quote(client, "thermal", {"people": 4, "building": "Maison", "city": "FÃ¨s"})

    response = client.get(f"/simulation/{created['quote_number']}/predevis")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Configuration retenue" in html
    assert "Net" in html
    assert created["quote_number"] in html


def test_admin_pdf_and_bilan_hide_placeholder_lines(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "admin-print.db")})
    client = app.test_client()
    client.post(
        "/api/calculate",
        json={
            "project": "pumping",
            "data": {"pump_existing": False, "flow_m3_h": 12, "hmt_m": 80},
        },
    )
    client.post("/admin/login", data={"password": "heliantha2026"})

    pdf_response = client.get("/admin/devis/1/pdf")
    detail_response = client.get("/admin/devis/1")

    pdf_html = pdf_response.get_data(as_text=True)
    detail_html = detail_response.get_data(as_text=True)

    assert pdf_response.status_code == 200
    assert "Pompe solaire 7.5 CV" in pdf_html
    assert "VEICHI 7.5 kW tri" in pdf_html
    assert "Panneaux photovoltaïques 590 Wc" in pdf_html
    assert "PV-590-HS" not in pdf_html
    assert "DRV-VEICHI-5.5" not in pdf_html
    assert "HeliAntha Select" not in detail_html
    assert "HeliAntha Structure" not in detail_html
    assert "HeliAntha Triphasé" not in detail_html
    assert "HeliAntha 12 panneaux" not in detail_html
    assert "HeliAntha Par panneau" not in detail_html
    assert "Panneaux photovoltaïques 590 Wc" in detail_html
    assert "Structure pour panneaux 590 Wc" in detail_html
    assert "Coffret de protection tri" in detail_html
    assert "Câblage et accessoires" in detail_html
    assert "Installation et mise en service" in detail_html
    assert "A confirmer" not in pdf_html
    assert "51 996.08 DH" in pdf_html

    assert detail_response.status_code == 200
    assert "Éléments du devis" in detail_html
    assert "7 ligne(s)" in detail_html
    assert "Raisonnement technique" not in detail_html
    assert "Formule" not in detail_html
    assert "Source" not in detail_html
    assert "BOM" not in detail_html


def test_calculate_returns_controlled_error_on_unexpected_failure(tmp_path, monkeypatch):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "public-error.db")})
    client = app.test_client()

    from app import routes

    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(routes.engine, "calculate", boom)

    response = client.post("/api/calculate", json={"project": "ongrid", "data": {"monthly_kwh": 600}})
    payload = response.get_json()

    assert response.status_code == 500
    assert "Nous n'avons pas pu terminer" in payload["error"]
