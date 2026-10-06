from unittest.mock import patch
from app import create_app


def test_admin_whatsapp_page_and_proxy_routes(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "admin-whatsapp.db")})
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["admin_user"] = "admin"

    page = client.get("/admin/whatsapp")
    assert page.status_code == 200
    assert b"Passerelle WhatsApp" in page.data
    assert b"QR code WhatsApp" in page.data

    with (
        patch("app.routes.get_gateway_status", return_value={"online": False, "connected": False}),
        patch("app.routes.get_gateway_qr", return_value={"qr": None}),
        patch("app.routes.send_whatsapp_raw", return_value=False),
    ):
        status = client.get("/admin/whatsapp/status")
        assert status.status_code == 200
        assert status.get_json()["online"] is False

        qr = client.get("/admin/whatsapp/qr")
        assert qr.status_code == 200
        assert qr.get_json()["qr"] is None

        test = client.post("/admin/whatsapp/test", json={"phone": "0600000000", "message": "Test"})
        assert test.status_code == 200
        assert test.get_json()["success"] is False
