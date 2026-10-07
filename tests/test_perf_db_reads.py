"""Database initialization must never become work for ordinary admin reads."""
from unittest.mock import patch

import pytest
from flask import Flask

from app import create_app
from app import db as dbmod


def application(database, **overrides):
    return create_app({"TESTING": True, "DATABASE": str(database),
                       "ADMIN_PASSWORD": "known-test-password", **overrides})


@pytest.mark.parametrize("path", ["/admin/tva", "/admin/catalogue"])
def test_admin_read_has_no_hashing_migrations_or_writes_and_under_ten_queries(tmp_path, path):
    app = application(tmp_path / "reads.db")
    with app.app_context():
        connection = dbmod.get_db()
        connection.execute("UPDATE vat_rates SET value = '13' WHERE key = 'residential_panels'")
        connection.execute("UPDATE company_settings SET value = '73' WHERE key = 'transport_pumping_rate'")
        connection.execute("UPDATE products SET sale_price = 1234 WHERE reference = 'ONGRID-PV-590'")
        connection.commit()
    statements = []

    @app.before_request
    def trace_reads():
        dbmod.get_db().set_trace_callback(statements.append)

    client = app.test_client()
    with client.session_transaction() as session:
        session["admin_user"] = "direction@heliantha.ma"
    with patch.object(dbmod, "generate_password_hash") as hashing, patch.object(dbmod, "ensure_schema") as migration:
        response = client.get(path)
    assert response.status_code == 200
    hashing.assert_not_called()
    migration.assert_not_called()
    assert 0 < len(statements) < 10, statements
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in statements), statements
    html = response.get_data(as_text=True)
    if path == "/admin/tva":
        assert 'name="residential_panels"' in html and 'value="13"' in html
        assert 'name="transport_pumping_rate"' in html and 'value="73"' in html
    else:
        assert "1 234,00 DH" in html


def test_get_db_only_opens_connection_without_initializing(tmp_path):
    app = Flask(__name__)
    app.config["DATABASE"] = str(tmp_path / "empty.db")
    with app.app_context(), patch.object(dbmod, "ensure_schema") as migration:
        connection = dbmod.get_db()
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
        migration.assert_not_called()
        dbmod.close_db()


def test_read_bootstraps_a_new_database_once(tmp_path):
    app = Flask(__name__)
    app.config.update(TESTING=True, DATABASE=str(tmp_path / "new.db"), ADMIN_PASSWORD="known-test-password")
    with app.app_context(), patch.object(dbmod, "ensure_schema", wraps=dbmod.ensure_schema) as migration, patch.object(dbmod, "generate_password_hash", wraps=dbmod.generate_password_hash) as hashing:
        assert len(dbmod.list_vat_rates()) == 10
        assert dbmod.list_products()
        dbmod.list_company_settings()
        assert migration.call_count == 1
        assert hashing.call_count == 1
        dbmod.close_db()


@pytest.mark.parametrize("database_type", ["file", "memory"])
def test_initialized_database_survives_request_teardown(tmp_path, database_type):
    database = ":memory:" if database_type == "memory" else tmp_path / "contexts.db"
    app = application(database)
    with app.app_context():
        connection = dbmod.get_db()
        connection.execute("UPDATE company_settings SET value='83' WHERE key='transport_pumping_rate'")
        connection.commit()
    with app.app_context(), patch.object(dbmod, "generate_password_hash") as hashing, patch.object(dbmod, "ensure_schema") as migration:
        settings = {row["key"]: row["value"] for row in dbmod.list_company_settings()}
        assert settings["transport_pumping_rate"] == "83"
        assert len(dbmod.list_vat_rates()) == 10
        hashing.assert_not_called()
        migration.assert_not_called()
    if database_type == "memory":
        other = application(":memory:")
        with other.app_context():
            settings = {row["key"]: row["value"] for row in dbmod.list_company_settings()}
            assert settings["transport_pumping_rate"] == "60.00"


@pytest.mark.parametrize("missing_hash", [None, ""])
def test_explicit_migration_hashes_only_an_absent_password(tmp_path, missing_hash):
    app = application(tmp_path / "missing-password.db")
    with app.app_context():
        connection = dbmod.get_db()
        connection.execute("UPDATE users SET password_hash=? WHERE role='Direction'", (missing_hash,))
        connection.commit()
        with patch.object(dbmod, "generate_password_hash", wraps=dbmod.generate_password_hash) as hashing:
            dbmod.init_db()
            dbmod.init_db()
        assert hashing.call_count == 1
        assert dbmod.authenticate_user("direction@heliantha.ma", "known-test-password")


@pytest.mark.parametrize("legacy_admin", [False, True])
def test_existing_password_survives_explicit_migration(tmp_path, legacy_admin):
    app = application(tmp_path / "existing-password.db")
    with app.app_context():
        connection = dbmod.get_db()
        original_hash = connection.execute("SELECT password_hash FROM users WHERE role='Direction'").fetchone()[0]
        if legacy_admin:
            connection.execute("UPDATE users SET username='admin', role='Administrateur' WHERE role='Direction'")
            connection.commit()
        app.config["ADMIN_PASSWORD"] = "a-different-startup-password"
        with patch.object(dbmod, "generate_password_hash") as hashing:
            dbmod.init_db()
            dbmod.init_db()
            assert dbmod.authenticate_user("direction@heliantha.ma", "known-test-password")
        hashing.assert_not_called()
        assert connection.execute("SELECT password_hash FROM users WHERE role='Direction'").fetchone()[0] == original_hash


def test_restarting_preserves_catalogue_and_three_historical_quotes(tmp_path):
    database = tmp_path / "history.db"
    app = application(database)
    with app.app_context():
        connection = dbmod.get_db()
        connection.execute("UPDATE products SET sale_price=1234, stock=7 WHERE reference='ONGRID-PV-590'")
        connection.executemany("INSERT INTO quote_requests (quote_number, project, customer_name, request_json, result_json) VALUES (?, 'photovoltaic', 'Client test', '{}', '{}')", [(f'HISTORY-{i}',) for i in range(3)])
        connection.commit()
        before = {table: [tuple(row) for row in connection.execute(f'SELECT * FROM {table} ORDER BY id')] for table in ("products", "quote_requests", "users")}
    with patch.object(dbmod, "generate_password_hash") as hashing:
        restarted = application(database, ADMIN_PASSWORD="different-startup-password")
    hashing.assert_not_called()
    with restarted.app_context():
        connection = dbmod.get_db()
        after = {table: [tuple(row) for row in connection.execute(f'SELECT * FROM {table} ORDER BY id')] for table in before}
    assert after == before
    assert len(after["quote_requests"]) == 3


def test_new_file_replacing_old_path_is_initialized(tmp_path):
    database = tmp_path / "replaced.db"
    app = application(database)
    database.unlink()
    with app.app_context():
        assert len(dbmod.list_vat_rates()) == 10
        assert dbmod.list_products()
