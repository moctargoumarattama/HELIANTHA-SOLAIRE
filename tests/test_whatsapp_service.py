from unittest.mock import Mock, patch

import requests

from app.services.whatsapp_service import notify_quote_created, send_whatsapp_raw


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


def test_notify_quote_created_sends_client_and_admin_messages():
    quote_data = {
        "client_name": "Client Test",
        "client_phone": "0611111111",
        "city": "Rabat",
        "project_type": "Pompage Solaire",
        "total_ttc": "48 500 DH",
        "pdf_url": "/devis/12/pdf",
    }

    with (
        patch("app.services.whatsapp_service.BASE_URL", "https://devis.test"),
        patch("app.services.whatsapp_service.ADMIN_PHONE", "0684056613"),
        patch("app.services.whatsapp_service.send_whatsapp_raw", return_value=True) as send,
    ):
        notify_quote_created(quote_data)

    assert send.call_count == 2
    client_call, admin_call = send.call_args_list
    assert client_call.args[0] == "0611111111"
    assert "https://devis.test/devis/12/pdf" in client_call.args[1]
    assert admin_call.args[0] == "0684056613"
    assert "Client Test" in admin_call.args[1]


def test_notify_quote_created_uses_admin_gateway_settings():
    quote_data = {
        "client_name": "Client Test",
        "client_phone": "0611111111",
        "project_type": "On-Grid",
        "total_ttc": "35 810 DH",
        "pdf_url": "/devis/42/pdf",
        "whatsapp_gateway_url": "http://127.0.0.1:3999/send-message",
        "admin_whatsapp": "0699999999",
        "app_base_url": "https://example.test",
    }

    with patch("app.services.whatsapp_service.send_whatsapp_raw", return_value=True) as send:
        notify_quote_created(quote_data)

    assert send.call_count == 2
    assert send.call_args_list[0].kwargs["gateway_url"] == "http://127.0.0.1:3999/send-message"
    assert send.call_args_list[1].args[0] == "0699999999"
    assert "https://example.test/devis/42/pdf" in send.call_args_list[0].args[1]
