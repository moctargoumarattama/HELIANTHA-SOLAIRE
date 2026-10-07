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


def test_admin_whatsapp_outbox_filter_and_item_actions(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "admin-wa-outbox.db")})
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["admin_user"] = "admin"

    with app.app_context():
        from app.db import enqueue_whatsapp_message, get_db

        id_failed = enqueue_whatsapp_message("0611111111", "text", caption="Msg Echoue")
        id_sent = enqueue_whatsapp_message("0622222222", "text", caption="Msg Envoye")
        with get_db() as conn:
            conn.execute("UPDATE whatsapp_outbox SET status = 'FAILED', attempts = 5 WHERE id = ?", (id_failed,))
            conn.execute("UPDATE whatsapp_outbox SET status = 'SENT', attempts = 1 WHERE id = ?", (id_sent,))
            conn.commit()

    # 1. Vue par defaut (failed) : exclut les messages SENT
    res_default = client.get("/admin/whatsapp")
    assert res_default.status_code == 200
    assert b"0611111111" in res_default.data
    assert b"0622222222" not in res_default.data

    # 2. Vue envoyes : montre seulement les messages SENT
    res_sent = client.get("/admin/whatsapp?view=sent")
    assert res_sent.status_code == 200
    assert b"0622222222" in res_sent.data
    assert b"0611111111" not in res_sent.data

    # 3. Vue tous : montre les deux
    res_all = client.get("/admin/whatsapp?view=all")
    assert res_all.status_code == 200
    assert b"0611111111" in res_all.data
    assert b"0622222222" in res_all.data

    # 4. Relance unitaire d'un message échoué
    with patch("app.routes.process_outbox", return_value={"processed": 1, "sent": 1, "failed": 0}):
        res_retry = client.post(f"/admin/whatsapp/outbox/{id_failed}/retry")
        assert res_retry.status_code == 200
        assert res_retry.get_json()["success"] is True

    # 5. Suppression unitaire d'un message
    res_del = client.post(f"/admin/whatsapp/outbox/{id_failed}/delete")
    assert res_del.status_code == 200
    assert res_del.get_json()["success"] is True

    # Vérification que le message supprimé n'apparaît plus
    res_all_after = client.get("/admin/whatsapp?view=all")
    assert b"0611111111" not in res_all_after.data

    # 6. Purge des messages envoyés
    res_purge = client.post("/admin/whatsapp/outbox/purge", json={"status": "SENT"})
    assert res_purge.status_code == 200
    assert res_purge.get_json()["count"] >= 1

    res_sent_after = client.get("/admin/whatsapp?view=sent")
    assert b"0622222222" not in res_sent_after.data

