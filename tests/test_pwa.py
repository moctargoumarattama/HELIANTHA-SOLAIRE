from app import create_app


def test_pwa_manifest_and_service_worker_routes(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "pwa.db")})
    client = app.test_client()

    manifest_response = client.get("/manifest.webmanifest")
    assert manifest_response.status_code == 200
    manifest = manifest_response.get_json()
    assert manifest["name"] == "HELIANTHA"
    assert manifest["short_name"] == "HELIANTHA"
    assert any(icon["src"].endswith("/assets/helin.jpeg") for icon in manifest["icons"])

    sw_response = client.get("/service-worker.js")
    assert sw_response.status_code == 200
    sw_text = sw_response.get_data(as_text=True)
    assert "CACHE_NAME" in sw_text
    assert "/assets/helin.jpeg" in sw_text


def test_public_and_admin_pages_expose_pwa_controls(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "pwa-pages.db")})
    client = app.test_client()

    home_html = client.get("/").get_data(as_text=True)
    assert 'rel="manifest"' in home_html
    assert "js/pwa.js" in home_html
    assert "data-pwa-install" not in home_html

    login_html = client.get("/admin/login").get_data(as_text=True)
    assert 'rel="manifest"' in login_html
    assert "js/pwa.js" in login_html
    assert "data-pwa-install" not in login_html
