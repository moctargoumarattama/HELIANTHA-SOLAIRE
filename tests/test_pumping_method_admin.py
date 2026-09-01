from app import create_app
from app.db import get_db, save_product
from app.services import pump_selector as pump_selector_module
import app.routes as routes_module


def login(client):
    client.post("/admin/login", data={"password": "heliantha2026"})


def table_counts():
    db = get_db()
    return {
        "products": db.execute("SELECT COUNT(1) FROM products").fetchone()[0],
        "pump_curve_points": db.execute("SELECT COUNT(1) FROM pump_curve_points").fetchone()[0],
        "pumping_solar_rules": db.execute("SELECT COUNT(1) FROM pumping_solar_rules").fetchone()[0],
        "quote_requests": db.execute("SELECT COUNT(1) FROM quote_requests").fetchone()[0],
    }


def add_readonly_test_pump(reference, power_hp, price, points):
    save_product(
        {
            "reference": reference,
            "category": "pumps",
            "brand": "HeliAntha Test",
            "model": "",
            "description": f"Pompe solaire {power_hp:g} CV",
            "sale_price": price,
            "currency": "DH",
            "unit": "piece",
            "active": 1,
            "stock": 0,
            "technical_specs": {
                "power_hp": power_hp,
                "power_kw": round(power_hp * 0.7355, 2),
                "voltage_v": 380,
                "current_a": 10,
                "phase": "triphase",
                "curve_points": [{"flow_m3_h": flow, "hmt_m": hmt} for flow, hmt in points],
            },
            "pump_curve_points": [{"flow_m3_h": flow, "hmt_m": hmt} for flow, hmt in points],
        },
        submitted_fields={
            "reference": reference,
            "category": "pumps",
            "brand": "HeliAntha Test",
            "model": "",
            "sale_price": str(price),
            "currency": "DH",
            "unit": "piece",
            "active": "1",
            "stock": "0",
            "power_hp": str(power_hp),
            "power_kw": str(round(power_hp * 0.7355, 2)),
            "voltage_v": "380",
            "current_a": "10",
            "phase": "triphase",
            "curve_points": "\n".join(f"{flow}:{hmt}" for flow, hmt in points),
        },
    )


def page_content(html):
    start = html.index('<main class="admin-content">')
    end = html.index("</main>", start)
    return html[start:end]


def test_admin_pumping_method_page_is_accessible_and_linked(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "method-admin.db")})
    client = app.test_client()

    response = client.get("/admin/pompage/methode")
    assert response.status_code == 302
    assert "/admin/login" in response.headers["Location"]

    login(client)
    response = client.get("/admin/pompage/methode")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Méthode Pompage" in html
    assert "Méthode de sélection Pompage" in html
    assert "Pompes utilisées dans la méthode" in html
    assert "95" in html
    assert "17" in html
    assert "749" in html


def test_admin_pumping_method_page_is_readonly_and_does_not_mutate_db(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "method-readonly.db")})
    client = app.test_client()
    login(client)

    with app.app_context():
        before = table_counts()

    response = client.get("/admin/pompage/methode?flow_m3_h=12&hmt_m=80")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    content = page_content(html)
    assert 'method="post"' not in content
    for forbidden in ("Modifier", "Supprimer", "Ajouter", "Enregistrer", "Changer"):
        assert f">{forbidden}<" not in content

    with app.app_context():
        after = table_counts()
    assert after == before


def test_admin_pumping_method_uses_real_selector_and_displays_decision(tmp_path, monkeypatch):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "method-selector.db")})
    client = app.test_client()
    login(client)
    calls = {}

    def spy(products, requested_flow_m3_h, requested_hmt_m):
        calls["flow"] = requested_flow_m3_h
        calls["hmt"] = requested_hmt_m
        return pump_selector_module.select_pump_for_duty(products, requested_flow_m3_h, requested_hmt_m)

    monkeypatch.setattr(routes_module, "select_pump_for_duty", spy)

    response = client.get("/admin/pompage/methode?flow_m3_h=12&hmt_m=80")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert calls == {"flow": 12.0, "hmt": 80.0}
    assert "Analyse des candidats" in html
    assert "Insuffisant" in html
    assert "Compatible" in html
    assert "7,5 CV retenu" in html
    assert "La règle HeliAntha retient la plus petite puissance CV suffisante." in html
    assert "14 × 590 W" in html
    assert "8,26 kWp" in html
    assert "VEICHI 7,5 kW" in html
    assert "Triphasé" in html


def test_admin_pumping_method_no_standard_pump_case_is_displayed(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "method-no-pump.db")})
    client = app.test_client()
    login(client)

    response = client.get("/admin/pompage/methode?flow_m3_h=75&hmt_m=30")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Aucune pompe standard ne couvre ce besoin." in html
    assert "Une configuration HeliAntha personnalisée est nécessaire." in html
    assert "Aucun fallback" in html


def test_admin_pumping_method_selected_cv_without_solar_rule_is_displayed(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "method-no-rule.db")})
    client = app.test_client()
    login(client)

    with app.app_context():
        add_readonly_test_pump("METHOD-PUMP-12-5", 12.5, 12345, [(75, 35), (80, 30)])

    response = client.get("/admin/pompage/methode?flow_m3_h=75&hmt_m=30")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "12,5 CV retenu" in html
    assert "Pompe adaptée identifiée : 12,5 CV" in html
    assert "La configuration solaire HeliAntha correspondante n’est pas encore définie." in html


def test_admin_pumping_method_performance_and_solar_rules_are_readonly_tables(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "method-tables.db")})
    client = app.test_client()
    login(client)

    response = client.get("/admin/pompage/methode")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Performances Débit/HMT par CV" in html
    assert "Voir les détails" in html
    assert "Variante technique" in html
    assert "Règles solaires" in html
    assert "2 CV" in html
    assert "6 × 400 W" in html
    assert "50 CV" in html
    assert "75 × 715 W" in html
