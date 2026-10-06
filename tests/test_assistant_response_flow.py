"""The JSON and NDJSON handlers share catalogue, quote and calculation priorities."""

import json
from types import SimpleNamespace

import pytest
from flask import Flask

from app.routes import bp
from app.services.anti_abuse import AssistantQuota


@pytest.fixture
def client(tmp_path):
    app = Flask("assistant-response-flow")
    app.config.update(TESTING=True, DATABASE=str(tmp_path / "unused.db"))
    app.extensions["assistant_quota"] = AssistantQuota()
    app.register_blueprint(bp)
    return app.test_client()


def final_payload(client, endpoint, message="Precision technique"):
    response = client.post(endpoint, json={"messages": [{"role": "user", "content": message}]})
    assert response.status_code == 200
    if endpoint.endswith("/stream"):
        events = [json.loads(line) for line in response.data.decode().splitlines()]
        assert events[-1]["type"] == "final"
        return events[-1]
    return response.get_json()


@pytest.mark.parametrize("endpoint", ["/api/assistant/chat", "/api/assistant/chat/stream"])
@pytest.mark.parametrize("branch", ["quote", "calculation", "general", "ollama"])
def test_every_final_branch_attaches_verified_products_and_obeys_priority(client, monkeypatch, endpoint, branch):
    events = []
    product = {"id": 912, "reference": "REAL-725", "name": "Panneau reel", "price": 600,
               "category": "panels", "power_w": 725, "source": "local_sqlite", "en_stock": True}

    def catalogue(messages):
        events.append("catalogue")
        return [product]

    def collect(messages, **kwargs):
        events.append("quote")
        return SimpleNamespace(handled=branch == "quote", content="Reponse quote")

    def calculate(messages, products=None):
        assert products == [product]
        events.append("calculation")
        return {"role": "assistant", "content": "Reponse calculation"} if branch == "calculation" else None

    def general(messages):
        events.append("general")
        return {"role": "assistant", "content": "Reponse general"} if branch == "general" else None

    def ollama(messages, products=None):
        assert products == [product]
        events.append("ollama")
        return {"role": "assistant", "content": "Reponse ollama"}

    def stream(messages, products=None):
        yield ollama(messages, products)["content"]

    monkeypatch.setattr("app.routes.find_catalog_products", catalogue)
    monkeypatch.setattr("app.routes.is_catalog_query", lambda messages: False)
    monkeypatch.setattr("app.routes.can_use_quote_manager", lambda messages: True)
    monkeypatch.setattr("app.routes.assistant_devis_manager.handle", collect)
    monkeypatch.setattr("app.routes.quick_solar_power_response", calculate)
    monkeypatch.setattr("app.routes.quick_assistant_response", general)
    monkeypatch.setattr("app.routes.chat_with_ollama", ollama)
    monkeypatch.setattr("app.routes.stream_ollama_chat", stream)

    result = final_payload(client, endpoint)
    expected = ["catalogue", "quote", "calculation", "general", "ollama"]
    terminal = {"quote": "quote", "calculation": "calculation", "general": "general", "ollama": "ollama"}[branch]
    assert events == expected[:expected.index(terminal) + 1]
    assert result["content"] == f"Reponse {branch}"
    assert result["suggested_products"] == [product]


def test_legacy_quote_marker_never_turns_hybrid_three_phase_into_single_phase(client, monkeypatch):
    monkeypatch.setattr("app.routes.find_catalog_products", lambda messages: [])
    monkeypatch.setattr("app.routes.can_use_quote_manager", lambda messages: False)
    monkeypatch.setattr("app.routes.quick_solar_power_response", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.routes.quick_assistant_response", lambda messages: None)
    monkeypatch.setattr("app.routes.chat_with_ollama", lambda *args, **kwargs: {
        "content": '<<<DEVIS_DATA:{"mode":"hybrid","phase":"triphase","consommation":1000}>>>'
    })

    def forbidden(*args, **kwargs):
        pytest.fail("The unsupported hybrid phase must not reach the quote engine")

    monkeypatch.setattr("app.routes._create_official_quote", forbidden)
    result = final_payload(client, "/api/assistant/chat")
    assert "triphase" in result["content"]
    assert not result.get("quote_ready")

