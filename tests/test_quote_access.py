"""Quote credentials and all public PDF aliases are tested on temporary databases."""
import sqlite3
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest

from app import create_app
from app.db import _migrate_quote_requests, get_db, get_quote_access_token, save_quote


PDF_PATHS = (
    "/api/quotes/{quote_id}/document.pdf",
    "/devis/{quote_id}/pdf",
    "/devis/{quote_id}/document.pdf",
    "/simulation/{quote_number}/predevis",
)
JSON_PATHS = (
    "/api/quotes/{quote_id}",
    "/api/quotes/by-number/{quote_number}",
    "/devis/{quote_id}",
    "/simulation/{quote_number}",
)


@pytest.fixture
def quote_context(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db._get_redis_client", lambda: None)
    app = create_app({
        "TESTING": True, "DATABASE": str(tmp_path / "quote-access.db"),
        "ADMIN_PASSWORD": "quote-access-test-password",
    })
    client = app.test_client()
    created = client.post("/api/calculate", json={
        "project": "photovoltaic",
        "data": {"meter_type": "numerique", "phase": "monophase",
                 "monthly_consumption_kwh": 1000},
        "contact": {"name": "Client PDF", "phone": "0600000000"},
    })
    assert created.status_code == 200
    quote = created.get_json()
    with app.app_context():
        other_id = save_quote("ACCESS-OTHER", "photovoltaic", {}, {}, {})
        other_token = get_quote_access_token(other_id)
    return app, client, quote, other_id, other_token


def test_creation_returns_unique_persisted_credentials_and_protected_urls(quote_context):
    app, client, quote, _, other_token = quote_context
    token = quote["access_token"]
    assert len(token) == 32 and token != other_token
    with app.app_context():
        assert get_quote_access_token(quote["quote_id"]) == token
    for key in ("quote_url", "pdf_url", "public_url"):
        assert parse_qs(urlsplit(quote[key]).query) == {"token": [token]}
        assert client.get(quote[key]).status_code == 200


@pytest.mark.parametrize("path_template", PDF_PATHS)
@pytest.mark.parametrize("invalid_token", [None, "", "incorrect", "\u00e9"])
def test_pdf_aliases_reject_missing_wrong_or_non_ascii_tokens_before_generation(
    quote_context, path_template, invalid_token
):
    _, client, quote, _, _ = quote_context
    path = path_template.format(**quote)
    query = {} if invalid_token is None else {"token": invalid_token}
    with patch("app.routes.build_quote_pdf") as generate_pdf:
        response = client.get(path, query_string=query)
    assert response.status_code == 403
    assert "no-store" in response.headers["Cache-Control"]
    generate_pdf.assert_not_called()


@pytest.mark.parametrize("path_template", PDF_PATHS)
def test_each_pdf_alias_accepts_only_its_quotes_token(quote_context, path_template):
    _, client, quote, _, other_token = quote_context
    path = path_template.format(**quote)
    assert client.get(path, query_string={"token": other_token}).status_code == 403
    response = client.get(path, query_string={"token": quote["access_token"]})
    assert response.status_code == 200
    assert response.mimetype == "application/pdf" and response.data.startswith(b"%PDF-")
    assert response.headers["Referrer-Policy"] == "no-referrer"


@pytest.mark.parametrize("path_template", JSON_PATHS)
def test_json_aliases_cannot_disclose_pdf_credentials_without_authorization(
    quote_context, path_template
):
    _, client, quote, _, other_token = quote_context
    path = path_template.format(**quote)
    for query in ({}, {"token": other_token}):
        response = client.get(path, query_string=query)
        assert response.status_code == 403
        assert quote["access_token"] not in response.get_data(as_text=True)
    response = client.get(path, query_string={"token": quote["access_token"]})
    assert response.status_code == 200
    assert response.json["access_token"] == quote["access_token"]
    assert parse_qs(urlsplit(response.json["pdf_url"]).query) == {
        "token": [quote["access_token"]]
    }


def test_valid_admin_session_can_read_without_token_and_inactive_session_cannot(quote_context):
    app, client, quote, _, _ = quote_context
    login = client.post("/admin/login", data={
        "email": "direction@heliantha.ma", "password": "quote-access-test-password",
    })
    assert login.status_code == 302
    for template in (*PDF_PATHS, *JSON_PATHS, "/admin/devis/{quote_id}/pdf"):
        assert client.get(template.format(**quote)).status_code == 200
    with app.app_context(), get_db() as db:
        db.execute("UPDATE users SET active = 0 WHERE username = 'direction@heliantha.ma'")
    with patch("app.routes.build_quote_pdf") as generate_pdf:
        response = client.get(f"/devis/{quote['quote_id']}/pdf")
    assert response.status_code == 403
    generate_pdf.assert_not_called()


def test_nonexistent_session_and_forged_admin_headers_cannot_bypass(quote_context):
    _, client, quote, _, _ = quote_context
    path = f"/devis/{quote['quote_id']}/pdf"
    assert client.get(path, headers={
        "X-Admin": "true", "Authorization": "Bearer fake-admin",
    }).status_code == 403
    with client.session_transaction() as session:
        session["admin_user"] = "does-not-exist"
    assert client.get(path).status_code == 403


def test_active_account_outside_admin_portal_cannot_bypass(quote_context):
    app, client, quote, _, _ = quote_context
    with app.app_context(), get_db() as db:
        db.execute("UPDATE users SET role = 'Client' WHERE username = 'direction@heliantha.ma'")
    with client.session_transaction() as session:
        session["admin_user"] = "direction@heliantha.ma"
    assert client.get(f"/devis/{quote['quote_id']}/pdf").status_code == 403


def test_historical_migration_preserves_saved_values_and_existing_tokens():
    with sqlite3.connect(":memory:") as db:
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE quote_requests (id INTEGER PRIMARY KEY, "
                   "quote_number TEXT, request_json TEXT, result_json TEXT, amount_ttc REAL)")
        db.executemany("INSERT INTO quote_requests VALUES (?, ?, ?, ?, ?)", (
            (1, "HISTORICAL-1", '{"customer":"saved"}', '{"price":123.45}', 123.45),
            (2, "HISTORICAL-2", '{}', '{"price":678.90}', 678.90),
        ))
        before = [dict(row) for row in db.execute("SELECT * FROM quote_requests ORDER BY id")]
        _migrate_quote_requests(db)
        migrated = [dict(row) for row in db.execute("SELECT * FROM quote_requests ORDER BY id")]
        for old, new in zip(before, migrated):
            assert all(new[key] == value for key, value in old.items())
            assert len(new["access_token"]) == 32
        assert migrated[0]["access_token"] != migrated[1]["access_token"]
        _migrate_quote_requests(db)
        assert [dict(row) for row in db.execute("SELECT * FROM quote_requests ORDER BY id")] == migrated
        indexes = {row["name"] for row in db.execute("PRAGMA index_list(quote_requests)")}
        assert "idx_quote_requests_access_token" in indexes
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE quote_requests SET access_token = ? WHERE id = 2",
                       (migrated[0]["access_token"],))
