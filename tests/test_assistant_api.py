import json
from unittest.mock import MagicMock, Mock, patch

import requests

from app import create_app
from app.db import get_quote, list_company_settings, update_company_setting
from app.services.ai_service import ASSISTANT_FALLBACK_MESSAGE


def test_assistant_chat_valid_payload_calls_ollama(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "assistant-ok.db")})
    client = app.test_client()
    ollama_response = Mock()
    ollama_response.raise_for_status.return_value = None
    ollama_response.json.return_value = {"message": {"role": "assistant", "content": "Bonjour, je peux vous aider."}}

    with patch("app.services.ai_service.requests.post", return_value=ollama_response) as post:
        response = client.post(
            "/api/assistant/chat",
            json={"messages": [{"role": "user", "content": "Explique la difference entre MPPT et PWM"}]},
        )

    assert response.status_code == 200
    assert response.get_json() == {"role": "assistant", "content": "Bonjour, je peux vous aider."}
    assert post.call_args.kwargs["timeout"] == 45
    sent_payload = post.call_args.kwargs["json"]
    assert sent_payload["model"] == "heliantha-ai"
    assert sent_payload["stream"] is False
    sent_messages = sent_payload["messages"]
    assert sent_messages[0]["role"] == "system"
    assert "Tu es l'assistant de HELIANTHA" in sent_messages[0]["content"]
    assert "Maroc" in sent_messages[0]["content"]
    assert "05 30 13 35 83" in sent_messages[0]["content"]
    assert "+212 661-575128" in sent_messages[0]["content"]
    assert "contact@heliantha.ma" in sent_messages[0]["content"]
    assert "Casablanca" not in sent_messages[0]["content"]
    assert sent_messages[1:] == [{"role": "user", "content": "Explique la difference entre MPPT et PWM"}]


def test_assistant_system_prompt_uses_admin_company_settings(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "assistant-company.db")})
    client = app.test_client()
    ollama_response = Mock()
    ollama_response.raise_for_status.return_value = None
    ollama_response.json.return_value = {"message": {"content": "Reponse IA."}}

    values = {
        "company_name": "Solaire Test",
        "city": "Agadir",
        "address": "Zone Industrielle Ait Melloul",
        "phone": "0528000000",
        "whatsapp": "+212600000000",
        "email": "contact@solaire.test",
    }
    with app.app_context():
        for setting in list_company_settings():
            if setting["key"] in values:
                update_company_setting(setting["id"], values[setting["key"]])

    with patch("app.services.ai_service.requests.post", return_value=ollama_response) as post:
        response = client.post(
            "/api/assistant/chat",
            json={"messages": [{"role": "user", "content": "Explique MPPT et PWM"}]},
        )

    assert response.status_code == 200
    system_prompt = post.call_args.kwargs["json"]["messages"][0]["content"]
    assert "Tu es l'assistant de Solaire Test" in system_prompt
    assert "situee a Agadir, Zone Industrielle Ait Melloul" in system_prompt
    assert "0528000000" in system_prompt
    assert "+212600000000" in system_prompt
    assert "contact@solaire.test" in system_prompt
    assert "Casablanca" not in system_prompt


def test_assistant_chat_fast_path_skips_ollama(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "assistant-fast.db")})
    client = app.test_client()

    with patch("app.services.ai_service.requests.post") as post:
        response = client.post(
            "/api/assistant/chat",
            json={"messages": [{"role": "user", "content": "Bonjour"}]},
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert "conseiller heliantha" in payload["content"].lower()
    post.assert_not_called()


def test_assistant_unknown_local_intent_goes_to_ollama(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "assistant-unknown.db")})
    client = app.test_client()
    ollama_response = Mock()
    ollama_response.raise_for_status.return_value = None
    ollama_response.json.return_value = {"message": {"content": "Reponse specialisee depuis Ollama."}}

    with patch("app.services.ai_service.requests.post", return_value=ollama_response) as post:
        response = client.post(
            "/api/assistant/chat",
            json={"messages": [{"role": "user", "content": "Quelle difference entre onduleur hybride et micro-onduleur ?"}]},
        )

    assert response.status_code == 200
    assert response.get_json()["content"] == "Reponse specialisee depuis Ollama."
    post.assert_called_once()


def test_assistant_chat_returns_fallback_on_connection_error(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "assistant-error.db")})
    client = app.test_client()

    with patch("app.services.ai_service.requests.post", side_effect=requests.ConnectionError):
        response = client.post(
            "/api/assistant/chat",
            json={"messages": [{"role": "user", "content": "Ollama disponible ?"}]},
        )

    assert response.status_code == 200
    assert response.get_json() == {"role": "assistant", "content": ASSISTANT_FALLBACK_MESSAGE}


def test_assistant_chat_rejects_malformed_payloads(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "assistant-bad.db")})
    client = app.test_client()

    assert client.post("/api/assistant/chat", data="not json").status_code == 400
    assert client.post("/api/assistant/chat", json={"messages": []}).status_code == 400
    assert client.post("/api/assistant/chat", json={"messages": [{"role": "user", "content": ""}]}).status_code == 400


def test_assistant_chat_truncates_user_messages(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "assistant-truncate.db")})
    client = app.test_client()
    ollama_response = Mock()
    ollama_response.raise_for_status.return_value = None
    ollama_response.json.return_value = {"message": {"content": "Message recu."}}

    with patch("app.services.ai_service.requests.post", return_value=ollama_response) as post:
        response = client.post(
            "/api/assistant/chat",
            json={"messages": [{"role": "user", "content": "x" * 1200}]},
        )

    assert response.status_code == 200
    sent_content = post.call_args.kwargs["json"]["messages"][-1]["content"]
    assert len(sent_content) == 1000


def test_assistant_chat_generates_ongrid_quote_from_tag(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "assistant-quote.db")})
    client = app.test_client()
    ollama_response = Mock()
    ollama_response.raise_for_status.return_value = None
    ollama_response.json.return_value = {
        "message": {
            "content": (
                "J'ai les informations necessaires. "
                '<<<DEVIS_DATA:{"mode":"ongrid","nom":"Client IA","telephone":"0600000000",'
                '"ville":"Rabat","consommation":1000,"phase":"monophase"}>>>'
            )
        }
    }

    with patch("app.services.ai_service.requests.post", return_value=ollama_response):
        response = client.post(
            "/api/assistant/chat",
            json={"messages": [{"role": "user", "content": "Preparation finale client"}]},
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["quote_ready"] is True
    assert "<<<DEVIS_DATA" not in payload["content"]
    assert payload["quote"]["total_ttc"].endswith("DH")
    assert payload["quote"]["system_summary"].startswith("Systeme solaire")
    assert payload["quote"]["download_url"] == f"/api/quotes/{payload['quote']['id']}/document.pdf"
    assert payload["quote"]["view_url"] == f"/api/quotes/{payload['quote']['id']}"

    with app.app_context():
        quote = get_quote(payload["quote"]["id"])
    assert quote["customer_name"] == "Client IA"
    assert quote["phone"] == "0600000000"
    assert quote["city"] == "Rabat"
    assert quote["project"] == "photovoltaic"


def test_assistant_devis_manager_asks_for_missing_slots_without_ollama(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "assistant-slots.db")})
    client = app.test_client()

    with patch("app.services.ai_service.requests.post") as post:
        response = client.post(
            "/api/assistant/chat",
            json={"messages": [{"role": "user", "content": "Je veux un devis pompage solaire"}]},
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert "debit" in payload["content"].lower()
    assert "hmt" in payload["content"].lower()
    assert "quote_ready" not in payload
    post.assert_not_called()


def test_assistant_devis_manager_generates_ongrid_quote_without_ollama(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "assistant-direct-ongrid.db")})
    client = app.test_client()

    with patch("app.services.ai_service.requests.post") as post:
        response = client.post(
            "/api/assistant/chat",
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Je veux un devis autoconsommation. Nom: Client Direct. "
                            "Telephone: 0600000000. Ville: Rabat. Conso 1000 kWh par mois. Monophase."
                        ),
                    }
                ]
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["quote_ready"] is True
    assert "<<<DEVIS_DATA" not in payload["content"]
    assert payload["quote"]["ref"].startswith("HSQ-")
    assert payload["quote"]["total_ttc"].endswith("DH")
    assert payload["quote"]["kwc"] > 0
    assert payload["quote"]["panels"] > 0
    assert payload["quote"]["download_url"] == f"/api/quotes/{payload['quote']['id']}/document.pdf"
    post.assert_not_called()

    with app.app_context():
        quote = get_quote(payload["quote"]["id"])
    assert quote["customer_name"] == "Client Direct"
    assert quote["project"] == "photovoltaic"
    assert quote["request"]["data"]["monthly_consumption_kwh"] == 1000
    assert "facture_mad" not in json.dumps(quote["request"])


def test_assistant_chat_generates_pumping_quote_from_tag(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "assistant-pump-quote.db")})
    client = app.test_client()
    ollama_response = Mock()
    ollama_response.raise_for_status.return_value = None
    ollama_response.json.return_value = {
        "message": {
            "content": (
                "Voici votre estimation pompage. "
                '<<<DEVIS_DATA:{"mode":"pumping","name":"Agriculteur","phone":"0611111111",'
                '"city":"Fes","debit":12,"hmt":80}>>>'
            )
        }
    }

    with patch("app.services.ai_service.requests.post", return_value=ollama_response):
        response = client.post(
            "/api/assistant/chat",
            json={"messages": [{"role": "user", "content": "Dimensionnement agricole 12 m3/h 80m"}]},
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["quote_ready"] is True
    assert payload["quote"]["system_summary"].startswith("Pompage solaire")

    with app.app_context():
        quote = get_quote(payload["quote"]["id"])
    assert quote["project"] == "pumping"
    assert quote["customer_name"] == "Agriculteur"


def test_assistant_devis_manager_stream_generates_pumping_quote_without_visible_marker(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "assistant-direct-stream.db")})
    client = app.test_client()

    with patch("app.services.ai_service.requests.post") as post:
        response = client.post(
            "/api/assistant/chat/stream",
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Devis pompage solaire pour Nom: Agriculteur Direct. "
                            "Telephone: 0611111111. Ville: Fes. Debit 12 m3/h et HMT 80 m."
                        ),
                    }
                ]
            },
        )

    assert response.status_code == 200
    events = [json.loads(line) for line in response.data.decode().splitlines()]
    assert events[-1]["type"] == "final"
    assert events[-1]["quote_ready"] is True
    assert "<<<DEVIS_DATA" not in events[-1]["content"]
    assert events[-1]["quote"]["system_summary"].startswith("Pompage solaire")
    post.assert_not_called()


def test_assistant_chat_streams_ollama_chunks(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "assistant-stream.db")})
    client = app.test_client()
    ollama_response = MagicMock()
    ollama_response.__enter__.return_value = ollama_response
    ollama_response.raise_for_status.return_value = None
    ollama_response.iter_lines.return_value = [
        json.dumps({"message": {"content": "Bonjour, "}}),
        json.dumps({"message": {"content": "je vous ecoute."}}),
    ]

    with patch("app.services.ai_service.requests.post", return_value=ollama_response) as post:
        response = client.post(
            "/api/assistant/chat/stream",
            json={"messages": [{"role": "user", "content": "Explique MPPT simplement"}]},
        )

    assert response.status_code == 200
    events = [json.loads(line) for line in response.data.decode().splitlines()]
    token_text = "".join(event.get("content", "") for event in events if event["type"] == "token")
    assert events[-1]["type"] == "final"
    assert token_text == "Bonjour, je vous ecoute."
    assert events[-1]["content"] == "Bonjour, je vous ecoute."
    assert post.call_args.kwargs["json"]["stream"] is True


def test_assistant_stream_unknown_local_intent_goes_to_ollama(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "assistant-stream-unknown.db")})
    client = app.test_client()
    ollama_response = MagicMock()
    ollama_response.__enter__.return_value = ollama_response
    ollama_response.raise_for_status.return_value = None
    ollama_response.iter_lines.return_value = [
        json.dumps({"message": {"content": "Analyse "}}),
        json.dumps({"message": {"content": "Ollama."}}),
    ]

    with patch("app.services.ai_service.requests.post", return_value=ollama_response) as post:
        response = client.post(
            "/api/assistant/chat/stream",
            json={"messages": [{"role": "user", "content": "Comment dimensionner une protection DC ?"}]},
        )

    assert response.status_code == 200
    token_text = "".join(
        event.get("content", "")
        for event in (json.loads(line) for line in response.data.decode().splitlines())
        if event["type"] == "token"
    )
    assert token_text == "Analyse Ollama."
    post.assert_called_once()
