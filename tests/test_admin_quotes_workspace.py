from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
import sqlite3

import pytest

import app as application
from app import Flask
from app.admin_quotes import group_quotes_by_client
from app.routes import bp


def quote(quote_id, **values):
    return {
        "id": quote_id, "quote_number": f"Q-{quote_id}", "customer_name": "Client Exemple",
        "phone": "0660000001", "email": "client@example.test", "company": "Ferme Exemple",
        "city": "Rabat", "project": "pumping", "status": "Nouveau",
        "created_at": "2026-10-07", "amount_ht": 100, "amount_ttc": 110,
        **values,
    }


def test_phone_variants_keep_one_client_and_all_quotes_without_mutating_records():
    rows = [quote(3, phone="+212 660 00 00 01"), quote(2, phone="0660 00 00 01"), quote(1, phone="00212660000001")]
    groups = group_quotes_by_client(rows)
    assert len(groups) == 1
    assert [row["id"] for row in groups[0]["quotes"]] == [3, 2, 1]
    assert all("display_status" not in row for row in rows)


def test_email_only_quote_joins_identifiable_phone_contact_and_keeps_complete_details():
    groups = group_quotes_by_client([quote(2, phone="", email="CLIENT@EXAMPLE.TEST", company=""), quote(1)])
    assert len(groups) == 1
    assert groups[0]["phone"] == "0660000001"
    assert groups[0]["company"] == "Ferme Exemple"
    assert len(groups[0]["quotes"]) == 2


def test_homonyms_and_shared_email_do_not_merge_different_phone_numbers():
    groups = group_quotes_by_client([quote(3), quote(2, phone="0660000002"), quote(1, phone="")])
    assert len(groups) == 3


def test_unidentified_contacts_are_separate_and_duplicate_quote_id_is_only_shown_once():
    rows = [quote(2, customer_name="", phone="", email=""), quote(1, customer_name="", phone="", email="")]
    groups = group_quotes_by_client([*rows, rows[0]])
    assert len(groups) == 2
    assert sum(len(group["quotes"]) for group in groups) == 2


def test_name_and_city_fallback_normalizes_spacing_case_and_accents():
    groups = group_quotes_by_client([
        quote(2, customer_name="Amélie  Client", phone="", email=""),
        quote(1, customer_name="amelie client", phone="", email="", city="RABAT"),
    ])
    assert len(groups) == 1


def test_workspace_can_read_beyond_old_limit_without_changing_default_listing():
    from app.db import list_quotes

    with sqlite3.connect(":memory:") as db:
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE quote_requests (id INTEGER PRIMARY KEY)")
        db.executemany("INSERT INTO quote_requests (id) VALUES (?)", [(i,) for i in range(1, 206)])
        with patch("app.db.get_db", return_value=db), patch("app.db.ensure_schema"):
            assert len(list_quotes(limit=None)) == 205
            assert len(list_quotes()) == 200


@pytest.fixture
def client():
    templates = Path(application.__file__).resolve().parent.parent / "templates"
    app = Flask("app", template_folder=str(templates))
    app.config.update(TESTING=True, SECRET_KEY="workspace-test")
    app.register_blueprint(bp)
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["admin_user"] = "test"
        yield client


def test_workspace_renders_contact_once_with_all_quote_links_and_no_visit_ui(client):
    with patch("app.routes.list_quotes", return_value=[quote(2), quote(1)]) as read:
        response = client.get("/admin/devis")
    assert response.status_code == 200
    read.assert_called_once_with(limit=None)
    html = response.get_data(as_text=True)
    assert html.count("<h2>Client Exemple</h2>") == 1
    assert html.count('data-quote-row ') == 2
    assert '/admin/devis/1' in html and '/admin/devis/2' in html
    assert "Clients / prospects" not in html and "Visite technique" not in html
    assert 'data-live-client-count' in html and 'data-live-quote-count' in html


def test_old_prospect_url_redirects_to_single_workspace_and_preserves_filters(client):
    with patch("app.routes.list_quotes") as read:
        response = client.get("/admin/prospects?q=Rabat&project=pumping&status=Nouveau")
    assert response.status_code == 302
    target = urlparse(response.headers["Location"])
    assert target.path == "/admin/devis"
    assert parse_qs(target.query) == {"q": ["Rabat"], "project": ["pumping"], "status": ["Nouveau"]}
    read.assert_not_called()


def test_quote_detail_preserves_pdf_and_status_actions_without_visit_panel(client):
    with patch("app.routes.get_quote", return_value=quote(1, visit_requests=[{"id": 1}])):
        response = client.get("/admin/devis/1")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '/admin/devis/1/pdf' in html and '/admin/devis/1/status' in html
    assert "visite-technique" not in html and "Visite demandée" not in html
    assert '<option value="Visite programmee"' not in html


def test_removed_visit_status_cannot_be_submitted_through_admin(client):
    with patch("app.routes.update_quote_status") as update:
        response = client.post("/admin/devis/1/status", data={"status": "Visite programmee"})
    assert response.status_code == 400
    update.assert_not_called()


def test_dashboard_does_not_advertise_removed_visit_feature(client):
    stats = {"latest_quotes": [quote(1, status="Visite programmee")], "project_breakdown": []}
    with patch("app.routes.dashboard_stats", return_value=stats):
        response = client.get("/admin/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Demandes visite" not in html and "Visite programmee" not in html
    assert "Étude" in html


@pytest.mark.parametrize("url", ["/admin/devis", "/admin/prospects"])
def test_workspace_and_old_route_still_require_login(client, url):
    with client.session_transaction() as session:
        session.clear()
    response = client.get(url)
    assert response.status_code == 302
    assert urlparse(response.headers["Location"]).path == "/admin/login"
