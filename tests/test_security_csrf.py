import re

from app import create_app


def _app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": True,
            "DATABASE": str(tmp_path / "csrf.db"),
            "SECRET_KEY": "csrf-test-secret",
        }
    )


def _admin_client(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session["admin_user"] = "direction@heliantha.ma"
    return client


def _token(response):
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True))
    assert match, "Le formulaire doit exposer un jeton CSRF"
    return match.group(1)


def test_admin_post_without_csrf_is_rejected(tmp_path):
    app = _app(tmp_path)
    response = _admin_client(app).post("/admin/tva", data={})
    assert response.status_code == 400


def test_admin_post_with_csrf_token_is_accepted(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    token = _token(client.get("/admin/login"))
    response = client.post(
        "/admin/login",
        data={"email": "unknown@example.test", "password": "wrong", "csrf_token": token},
    )
    assert response.status_code != 400


def test_public_json_api_is_not_blocked_by_csrf(tmp_path):
    app = _app(tmp_path)
    response = app.test_client().post("/api/calculate", json={})
    assert response.status_code != 400 or b"CSRF" not in response.data


def test_secret_key_is_configured(tmp_path):
    app = _app(tmp_path)
    assert app.config["SECRET_KEY"]
