from app import create_app


def test_admin_pricing_page_hides_transport_rules(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "pricing-admin.db")})
    client = app.test_client()
    client.post("/admin/login", data={"password": "heliantha2026"})

    html = client.get("/admin/tarification").get_data(as_text=True)

    assert "Déplacement" not in html
    assert "Déplacement minimum" not in html
    assert "Prix par kilomètre" not in html
    assert "travel_fixed" not in html
    assert "travel_cost_per_km" not in html
    assert "Marge commerciale" not in html
    assert "TVA" in html


def test_transport_pricing_rules_are_removed_from_seed(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "pricing-seed.db")})

    with app.app_context():
        from app.db import get_db

        keys = {
            row["key"]
            for row in get_db().execute("SELECT key FROM pricing_rules").fetchall()
        }

    assert "travel_fixed" not in keys
    assert "travel_cost_per_km" not in keys
