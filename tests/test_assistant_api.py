from unittest.mock import Mock, patch

import requests

from app import create_app
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
            json={"messages": [{"role": "user", "content": "Bonjour, je cherche une pompe"}]},
        )

    assert response.status_code == 200
    assert response.get_json() == {"role": "assistant", "content": "Bonjour, je peux vous aider."}
    assert post.call_args.kwargs["timeout"] == 45
    sent_payload = post.call_args.kwargs["json"]
    assert sent_payload["model"] == "heliantha-ai"
    assert sent_payload["stream"] is False
    assert sent_payload["messages"] == [{"role": "user", "content": "Bonjour, je cherche une pompe"}]


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
    sent_content = post.call_args.kwargs["json"]["messages"][0]["content"]
    assert len(sent_content) == 1000
