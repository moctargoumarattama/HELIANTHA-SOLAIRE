from unittest.mock import Mock, patch

import requests

from app import create_app
from app import routes as routes_module
from app.services.whatsapp_service import (
    gateway_logout,
    get_gateway_qr,
    get_gateway_status,
    get_whatsapp_base_url,
    notify_quote_created,
    send_whatsapp_document,
    send_whatsapp_raw,
)


def test_send_whatsapp_raw_success():
    response = Mock()
    response.json.return_value = {"success": True}

    with patch("app.services.whatsapp_service.requests.post", return_value=response) as post:
        assert send_whatsapp_raw("0600000000", "Bonjour") is True

    post.assert_called_once()
    assert post.call_args.kwargs["json"] == {"phone": "0600000000", "message": "Bonjour"}
    assert post.call_args.kwargs["timeout"] == 5


def test_send_whatsapp_raw_failure_returns_false():
    response = Mock()
    response.json.return_value = {"success": False, "error": "gateway offline"}

    with patch("app.services.whatsapp_service.requests.post", return_value=response):
        assert send_whatsapp_raw("0600000000", "Bonjour") is False


def test_send_whatsapp_raw_connection_error_returns_false():
    with patch("app.services.whatsapp_service.requests.post", side_effect=requests.ConnectionError):
        assert send_whatsapp_raw("0600000000", "Bonjour") is False


def test_send_whatsapp_document_success():
    response = Mock()
    response.json.return_value = {"success": True}

    with patch("app.services.whatsapp_service.requests.post", return_value=response) as post:
        assert send_whatsapp_document(
            "0600000000",
            "https://devis.test/devis/12/document.pdf",
            "Devis_HeliAntha_12.pdf",
            "Voici votre devis",
            gateway_url="http://127.0.0.1:3001/send-message",
        ) is True

    post.assert_called_once()
    assert post.call_args.args[0] == "http://127.0.0.1:3001/send-document"
    assert post.call_args.kwargs["json"] == {
        "phone": "0600000000",
        "pdf_url": "https://devis.test/devis/12/document.pdf",
        "filename": "Devis_HeliAntha_12.pdf",
        "caption": "Voici votre devis",
    }
    assert post.call_args.kwargs["timeout"] == 15


def test_notify_quote_created_sends_client_and_admin_documents(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "whatsapp-service.db")})
    quote_data = {
        "client_name": "Client Test",
        "client_phone": "0611111111",
        "city": "Rabat",
        "project_type": "Pompage Solaire",
        "total_ttc": "48 500 DH",
        "pdf_url": "/devis/12/document.pdf",
    }

    with (
        patch("app.services.whatsapp_service.BASE_URL", "https://devis.test"),
        patch("app.services.whatsapp_service.ADMIN_PHONE", "0684056613"),
        patch("app.services.whatsapp_service.get_gateway_status", return_value={"connected": True, "online": True}),
        patch("app.services.whatsapp_service.send_whatsapp_document", return_value=True) as send_document,
        patch("app.services.whatsapp_service.send_whatsapp_raw", return_value=True) as send,
    ):
        with app.app_context():
            notify_quote_created(quote_data)

    assert send_document.call_count == 2
    client_call, admin_call = send_document.call_args_list
    assert client_call.args[0] == "0611111111"
    assert client_call.args[1] == "https://devis.test/devis/12/document.pdf"
    assert client_call.args[2] == "Devis_HeliAntha.pdf"
    assert "48 500 DH" in client_call.args[3]
    assert admin_call.args[0] == "0684056613"
    assert admin_call.args[1] == "https://devis.test/devis/12/document.pdf"
    assert "Client Test" in admin_call.args[3]
    assert send.call_count == 0


def test_route_whatsapp_pdf_filename_uses_quote_number(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "whatsapp-route-filename.db")})

    with app.test_request_context("/"):
        app.config["TESTING"] = False
        with patch("app.routes.notify_quote_created") as notify:
            routes_module._notify_quote_created_safely(
                quote_id=12,
                project="photovoltaic",
                contact={"name": "Client Test", "phone": "0611111111"},
                data={"city": "Rabat"},
                result={
                    "quote_number": "HSQ-20261004-1234",
                    "financial_breakdown": {"total_ttc": 35810},
                },
            )

    payload = notify.call_args.args[0]
    assert payload["pdf_filename"] == "Devis_HSQ-20261004-1234.pdf"
    assert payload["pdf_url"] == "/devis/12/document.pdf"


def test_route_whatsapp_pdf_filename_falls_back_to_quote_id(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "whatsapp-route-fallback.db")})

    with app.test_request_context("/"):
        app.config["TESTING"] = False
        with patch("app.routes.notify_quote_created") as notify:
            routes_module._notify_quote_created_safely(
                quote_id=12,
                project="photovoltaic",
                contact={"name": "Client Test", "phone": "0611111111"},
                data={"city": "Rabat"},
                result={"financial_breakdown": {"total_ttc": 35810}},
            )

    payload = notify.call_args.args[0]
    assert payload["pdf_filename"] == "Devis_HeliAntha_12.pdf"


def test_notify_quote_created_uses_admin_gateway_settings(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "whatsapp-service-settings.db")})
    quote_data = {
        "client_name": "Client Test",
        "client_phone": "0611111111",
        "project_type": "On-Grid",
        "total_ttc": "35 810 DH",
        "pdf_url": "/devis/42/document.pdf",
        "whatsapp_gateway_url": "http://127.0.0.1:3999/send-message",
        "admin_whatsapp": "0699999999",
        "app_base_url": "https://example.test",
    }

    with (
        patch("app.services.whatsapp_service.get_gateway_status", return_value={"connected": True, "online": True}),
        patch("app.services.whatsapp_service.send_whatsapp_document", return_value=True) as send_document,
        patch("app.services.whatsapp_service.send_whatsapp_raw", return_value=True) as send,
    ):
        with app.app_context():
            notify_quote_created(quote_data)

    assert send_document.call_count == 2
    assert send_document.call_args_list[0].kwargs["gateway_url"] == "http://127.0.0.1:3999/send-message"
    assert send_document.call_args_list[1].args[0] == "0699999999"
    assert send_document.call_args_list[1].args[1] == "https://example.test/devis/42/document.pdf"
    assert send.call_count == 0


def test_notify_quote_created_keeps_message_pending_when_document_fails(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "whatsapp-service-fail.db")})
    quote_data = {
        "client_name": "Client Test",
        "client_phone": "0611111111",
        "project_type": "On-Grid",
        "total_ttc": "35 810 DH",
        "pdf_url": "/devis/42/document.pdf",
        "admin_whatsapp": "",
        "app_base_url": "https://example.test",
    }

    with (
        patch("app.services.whatsapp_service.get_gateway_status", return_value={"connected": True, "online": True}),
        patch("app.services.whatsapp_service.send_whatsapp_document", return_value=False),
        patch("app.services.whatsapp_service.send_whatsapp_raw", return_value=True) as send,
    ):
        with app.app_context():
            notify_quote_created(quote_data)

    assert send.call_count == 0


def test_get_whatsapp_base_url_strips_send_message_path():
    assert get_whatsapp_base_url("http://127.0.0.1:3001/send-message") == "http://127.0.0.1:3001"
    assert get_whatsapp_base_url("http://127.0.0.1:3001/send-document") == "http://127.0.0.1:3001"
    assert get_whatsapp_base_url("http://127.0.0.1:3001") == "http://127.0.0.1:3001"


def test_gateway_status_and_qr_use_base_endpoints():
    status_response = Mock()
    status_response.json.return_value = {"connected": True, "phone": "2126", "has_qr": False}
    qr_response = Mock()
    qr_response.json.return_value = {"connected": False, "qr": "data:image/png;base64,abc"}

    with patch("app.services.whatsapp_service.requests.get", side_effect=[status_response, qr_response]) as get:
        status = get_gateway_status("http://127.0.0.1:3001/send-message")
        qr = get_gateway_qr("http://127.0.0.1:3001/send-message")

    assert status["online"] is True
    assert status["connected"] is True
    assert qr["qr"].startswith("data:image")
    assert get.call_args_list[0].args[0] == "http://127.0.0.1:3001/status"
    assert get.call_args_list[1].args[0] == "http://127.0.0.1:3001/qr"


def test_gateway_helpers_return_offline_on_errors():
    with patch("app.services.whatsapp_service.requests.get", side_effect=requests.ConnectionError):
        assert get_gateway_status()["online"] is False
        assert get_gateway_qr()["qr"] is None

    with patch("app.services.whatsapp_service.requests.post", side_effect=requests.ConnectionError):
        assert gateway_logout() is False
