"""SQL-only dashboard figures and server-side quote browsing."""

from unittest.mock import patch

import pytest

from app import create_app
from app.db import dashboard_stats, get_dashboard_metrics, get_db, get_recent_quotes_summary, list_quotes_paginated


@pytest.fixture
def admin(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "quotes-pagination.db")})
    client = app.test_client()
    with client.session_transaction() as session:
        session["admin_user"] = "test"
    return app, client


def seed_quotes(app, rows):
    with app.app_context():
        db = get_db()
        db.executemany(
            """INSERT INTO quote_requests
               (quote_number, project, customer_name, phone, city, status,
                amount_ht, amount_ttc, request_json, result_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', '{}')""",
            rows,
        )
        db.commit()


def test_dashboard_metrics_aggregation_uses_only_projected_columns(admin):
    app, client = admin
    seed_quotes(app, [
        ("Q-SQL-1", "photovoltaic", "A", "0611111111", "Rabat", "Accepte", 9000, 10000),
        ("Q-SQL-2", "pumping", "B", "0622222222", "Fès", "Validé", 22000, 25000),
        ("Q-SQL-3", "hybrid", "C", "0633333333", "Agadir", "Nouveau", 13000, 15000),
        ("Q-SQL-4", "pumping", "D", "0644444444", "Meknès", "Refuse", 4500, 5000),
    ])
    with app.app_context():
        db = get_db()
        db.execute("UPDATE quote_requests SET quote_snapshot_json = ?", ("X" * 100000,))
        db.commit()
        statements = []
        db.set_trace_callback(statements.append)
        with patch("app.db.loads", side_effect=AssertionError("No JSON should be decoded")):
            metrics = get_dashboard_metrics(db=db)
            metric_reads = [sql for sql in statements if "from quote_requests" in sql.lower()]
            recent = get_recent_quotes_summary(db=db)
            stats = dashboard_stats()
        db.set_trace_callback(None)
        assert metrics["total_quotes"] == 4
        assert metrics["validated_count"] == 2
        assert metrics["pending_count"] == 1
        assert metrics["rejected_count"] == 1
        assert metrics["ca_validated"] == 35000
        assert metrics["ca_total_potentiel"] == 55000
        assert len(metric_reads) == 1
        assert stats["quotes_generated"] == 4
        assert stats["accepted_quotes"] == 2
        assert len(recent) == 4
        assert "quote_snapshot_json" not in recent[0]
        quote_reads = [sql.lower() for sql in statements if "from quote_requests" in sql.lower()]
        assert quote_reads
        assert all("select *" not in sql and "_json" not in sql for sql in quote_reads)
    assert client.get("/admin/dashboard").status_code == 200


def test_quotes_pagination_slicing_and_bounds(admin):
    app, client = admin
    seed_quotes(app, [
        (f"Q-PAGE-{i:03d}", "pumping", f"Client {i}", f"06{i:08d}", "Rabat", "Nouveau", 100, 110)
        for i in range(35)
    ])
    first = client.get("/admin/devis?page=1&per_page=20")
    second = client.get("/admin/quotes?page=2&per_page=20")
    assert first.status_code == second.status_code == 200
    first_html = first.get_data(as_text=True)
    second_html = second.get_data(as_text=True)
    assert first_html.count("data-quote-row ") == 20
    assert second_html.count("data-quote-row ") == 15
    assert "Affichage 1 à 20 sur 35 devis" in first_html
    assert "Affichage 21 à 35 sur 35 devis" in second_html
    assert "Suivant" in first_html and "Précédent" in second_html
    filtered = client.get("/admin/devis?page=1&per_page=20&q=Client&status=en_attente&type=pumping")
    filtered_html = filtered.get_data(as_text=True)
    assert filtered_html.count("data-quote-row ") == 20
    assert "q=Client" in filtered_html and "status=en_attente" in filtered_html and "type=pumping" in filtered_html
    assert client.get("/admin/devis?page=999&per_page=20").get_data(as_text=True).count("data-quote-row ") == 15
    assert client.get("/admin/devis?page=-1&per_page=20").get_data(as_text=True).count("data-quote-row ") == 20
    with app.app_context():
        assert list_quotes_paginated(page=2, per_page=20)["has_prev"] is True
        assert list_quotes_paginated(page=2, per_page=20)["has_next"] is False
        assert list_quotes_paginated(page="bad", per_page=1000)["per_page"] == 100


def test_quotes_server_search_filters_and_preserves_pagination_links(admin):
    app, client = admin
    seed_quotes(app, [
        ("Q-HASSAN", "photovoltaic", "Hassan Tazi", "0661112233", "Fès", "Accepte", 100, 110),
        ("Q-FATIMA", "hybrid", "Fatima Zahra", "0662223344", "Agadir", "Nouveau", 100, 110),
        ("Q-SUD", "pumping", "Société Solaire Sud", "0528112233", "Ouarzazate", "Refuse", 100, 110),
    ])
    for query, expected in (("Hassan", "Q-HASSAN"), ("0662223344", "Q-FATIMA"), ("Ouarzazate", "Q-SUD")):
        response = client.get("/admin/devis", query_string={"q": query})
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert html.count("data-quote-row ") == 1
        assert expected in html
    accepted = client.get("/admin/devis?status=valide&type=ongrid")
    assert accepted.get_data(as_text=True).count("data-quote-row ") == 1
    assert "Q-HASSAN" in accepted.get_data(as_text=True)
    assert client.get("/admin/devis?status=en_attente&type=hybride").get_data(as_text=True).count("data-quote-row ") == 1
    empty = client.get("/admin/devis?q=introuvable")
    assert "Aucun devis ne correspond" in empty.get_data(as_text=True)
    assert "Réinitialiser la recherche" in empty.get_data(as_text=True)
    assert client.get("/admin/devis?q=%27%20OR%201%3D1%20--").get_data(as_text=True).count("data-quote-row ") == 0


def test_quote_list_keeps_saved_financial_amounts_without_loading_snapshot(admin):
    app, client = admin
    seed_quotes(app, [
        ("Q-HISTORICAL", "photovoltaic", "Ancien client", "0600000001", "Rabat", "Nouveau", 9999, 9999),
    ])
    with app.app_context():
        db = get_db()
        db.execute(
            "UPDATE quote_requests SET financial_breakdown_json = ?, quote_snapshot_json = ?",
            ('{"total_ht": 1.05, "vat": 0.11, "total_ttc": 1.16}', "X" * 100000),
        )
        db.commit()
        page = list_quotes_paginated(db=db)
        assert "quote_snapshot_json" not in page["items"][0]
        assert page["items"][0]["financial_breakdown_json"]
    html = client.get("/admin/devis").get_data(as_text=True)
    assert "1,05 DH" in html and "0,11 DH" in html and "1,16 DH" in html

