from unittest.mock import patch

from app import create_app
from app.db import enqueue_whatsapp_message, list_whatsapp_outbox
from app.services.whatsapp_service import notify_quote_created, process_outbox


def test_notify_quote_created_enqueues_pending_messages(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "outbox-create.db")})
    quote_data = {
        "client_name": "Client Test",
        "client_phone": "0611111111",
        "project_type": "On-Grid",
        "total_ttc": "35 810 DH",
        "pdf_url": "/devis/1/pdf",
        "admin_whatsapp": "0684056613",
        "app_base_url": "https://devis.test",
    }

    with app.app_context(), patch(
        "app.services.whatsapp_service.get_gateway_status",
        return_value={"connected": False, "online": False},
    ):
        notify_quote_created(quote_data)
        rows = list_whatsapp_outbox(limit=10)

    assert len(rows) == 2
    assert {row["status"] for row in rows} == {"PENDING"}
    assert {row["msg_type"] for row in rows} == {"document"}


def test_process_outbox_keeps_pending_when_gateway_offline(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "outbox-offline.db")})

    with app.app_context():
        enqueue_whatsapp_message("0611111111", "text", caption="Bonjour")
        with patch(
            "app.services.whatsapp_service.get_gateway_status",
            return_value={"connected": False, "online": False},
        ):
            result = process_outbox()
        rows = list_whatsapp_outbox(limit=1)

    assert result["processed"] == 0
    assert rows[0]["status"] == "PENDING"
    assert rows[0]["attempts"] == 0


def test_process_outbox_marks_sent_when_gateway_succeeds(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "outbox-sent.db")})

    with app.app_context():
        enqueue_whatsapp_message(
            "0611111111",
            "document",
            pdf_url="https://devis.test/devis/1/pdf",
            filename="Devis_HeliAntha_1.pdf",
            caption="Votre devis",
        )
        with (
            patch("app.services.whatsapp_service.time.sleep", return_value=None),
            patch(
                "app.services.whatsapp_service.get_gateway_status",
                return_value={"connected": True, "online": True},
            ),
            patch("app.services.whatsapp_service.send_whatsapp_document", return_value=True),
        ):
            result = process_outbox()
        rows = list_whatsapp_outbox(limit=1)

    assert result["processed"] == 1
    assert result["sent"] == 1
    assert rows[0]["status"] == "SENT"
    assert rows[0]["sent_at"]
