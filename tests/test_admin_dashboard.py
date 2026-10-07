"""Tests for the modernized admin dashboard cockpit."""

from unittest.mock import patch
from app import create_app


def test_admin_dashboard_guest_redirect(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test-dash-guest.db")})
    client = app.test_client()
    res = client.get("/admin/")
    assert res.status_code == 302
    assert "/admin/login" in res.headers["Location"]


def test_admin_dashboard_renders_cockpit_elements(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test-dash.db")})
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["admin_user"] = "direction@heliantha.ma"

    res = client.get("/admin/")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Header and Cockpit elements
    assert "db-cockpit" in html
    assert "Vue d&#39;ensemble commerciale" in html or "Vue d'ensemble commerciale" in html
    assert "Gérer les devis" in html
    assert "Catalogue" in html
    assert "Passerelle WhatsApp" in html

    # KPI indicators
    assert "Prospects" in html
    assert "Devis générés" in html
    assert "En attente" in html
    assert "Devis acceptés" in html
    assert "En installation" in html
    assert "Refusés" in html

    # Shortcuts to calculation rules
    assert "/admin/regles-pompage" in html
    assert "/admin/regles-ongrid" in html
    assert "/admin/tva" in html
    assert "/admin/whatsapp" in html


def test_admin_dashboard_with_mocked_data(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test-dash-mock.db")})
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["admin_user"] = "direction@heliantha.ma"

    mock_stats = {
        "total_prospects": 15,
        "new_today": 3,
        "simulations": 15,
        "quotes_generated": 15,
        "pending_quotes": 5,
        "accepted_quotes": 7,
        "refused_quotes": 2,
        "installing_projects": 1,
        "project_breakdown": [
            {"key": "pumping", "label": "Pompage solaire", "count": 10},
            {"key": "ongrid", "label": "On-Grid", "count": 5},
        ],
        "latest_quotes": [
            {
                "id": 101,
                "quote_number": "Q-2026-0101",
                "customer_name": "Karim Bennani",
                "company": "Domaine Vert",
                "city": "Marrakech",
                "project": "pumping",
                "status": "Accepte",
                "amount_ttc": 125000,
            }
        ],
    }

    with patch("app.routes.dashboard_stats", return_value=mock_stats):
        res = client.get("/admin/")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "Q-2026-0101" in html
        assert "Karim Bennani" in html
        assert "Domaine Vert" in html
        assert "Marrakech" in html
        assert "Pompage" in html
        assert "15" in html
        assert "+3 aujourd&#39;hui" in html or "+3 aujourd'hui" in html
