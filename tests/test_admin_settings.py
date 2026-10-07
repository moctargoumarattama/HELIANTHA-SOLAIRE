from app import create_app
from app.db import list_company_settings


def test_admin_settings_page_and_tabs(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test-settings.db")})
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["admin_user"] = "direction@heliantha.ma"

    page = client.get("/admin/parametres")
    assert page.status_code == 200
    html = page.data.decode("utf-8")
    assert "Paramètres Généraux" in html
    assert "Entreprise &amp; Contact" in html
    assert "Devis, Banque &amp; PDF" in html
    assert "Passerelle &amp; URLs" in html
    assert "company_name" in html


def test_admin_settings_post_update(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test-settings-update.db")})
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["admin_user"] = "direction@heliantha.ma"

    with app.app_context():
        settings = list_company_settings()
        company_setting = next(s for s in settings if s["key"] == "company_name")
        phone_setting = next(s for s in settings if s["key"] == "phone")

    res = client.post(
        "/admin/parametres",
        data={
            f"value_{company_setting['id']}": "HeliAntha Energy Maroc",
            f"value_{phone_setting['id']}": "05 30 99 88 77",
        },
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert "Paramètres enregistrés avec succès" in res.data.decode("utf-8")

    with app.app_context():
        updated_settings = {s["key"]: s["value"] for s in list_company_settings()}
        assert updated_settings["company_name"] == "HeliAntha Energy Maroc"
        assert updated_settings["phone"] == "05 30 99 88 77"
