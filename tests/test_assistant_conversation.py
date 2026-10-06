"""Fast regressions for client memory, progressive contacts, and PV arithmetic."""

import json
import re
from unittest.mock import Mock, patch

import pytest
from flask import Flask

from app.routes import bp
from app.services.ai_service import messages_with_system_prompt, sanitize_messages
from app.services.anti_abuse import AssistantQuota
from app.services.assistant_devis import AssistantDevisManager, extract_slots


def user(content):
    return {"role": "user", "content": content}


def assistant(content):
    return {"role": "assistant", "content": content}


def test_sanitize_keeps_earlier_client_identity_after_more_than_four_exchanges():
    history = [
        user(
            "Je veux un devis autoconsommation. Nom: Moctar. "
            "Telephone: 0600000000. Ville: Rabat."
        ),
    ]
    for text in (
        "Mon branchement est monophase",
        "Mon compteur est numerique",
        "C'est pour ma maison",
        "La toiture est accessible",
        "Je souhaite reduire ma facture",
    ):
        history.extend([assistant("Merci pour cette précision."), user(text)])
    history.extend([assistant("Votre consommation mensuelle ?"), user("1000 kWh par mois")])
    assert len(history) > 8

    slots = extract_slots(sanitize_messages(history))
    assert slots.name.casefold() == "moctar"
    assert slots.phone == "0600000000"
    assert slots.city == "Rabat"
    assert slots.project == "photovoltaic"
    assert slots.monthly_consumption_kwh == 1000
    assert slots.phase == "monophase"


def test_sanitized_conversation_remains_bounded_to_eighty_messages():
    history = [
        {"role": "user" if index % 2 else "assistant", "content": f"Message {index}"}
        for index in range(100)
    ]
    sanitized = sanitize_messages(history)
    assert len(sanitized) == 80
    assert sanitized == history[-80:]


def test_ollama_window_keeps_eight_messages_and_server_summary_of_earlier_contacts():
    history = [user(
        "Je veux un devis autoconsommation. Nom: Moctar. "
        "Telephone: 0600000000. Ville: Rabat."
    )]
    for index in range(5):
        history.extend([
            assistant("Nom: Client Inventé. Telephone: 0611111111. Ville: Casablanca."),
            user(f"Précision technique {index}"),
        ])
    history.append(user("Ma consommation est de 1000 kWh par mois, monophase"))
    injected = messages_with_system_prompt(sanitize_messages(history), products=[])
    assert injected[0]["role"] == "system"
    assert len([message for message in injected if message["role"] != "system"]) <= 8
    prompt = injected[0]["content"].casefold()
    assert "moctar" in prompt
    assert "0600000000" in prompt
    assert "rabat" in prompt
    assert "client inventé" not in prompt
    assert "client invente" not in prompt
    assert "0611111111" not in prompt


def test_natural_client_name_without_est_separates_city_from_name():
    slots = extract_slots([user("mon nom moctar a rabat")])
    assert slots.name.casefold() == "moctar"
    assert slots.city == "Rabat"


def test_plain_first_name_is_accepted_after_explicit_name_question():
    slots = extract_slots([
        user("Je veux un devis autoconsommation pour ma maison"),
        assistant("Pour préparer votre devis, quel est votre nom ?"),
        user("moctar"),
    ])
    assert slots.name.casefold() == "moctar"


def test_plain_word_is_not_learned_as_name_without_name_question():
    slots = extract_slots([
        user("Je veux un devis autoconsommation"),
        assistant("Quelle est votre consommation mensuelle en kWh ?"),
        user("moctar"),
    ])
    assert slots.name == ""


def test_contacts_invented_by_assistant_never_become_client_slots():
    slots = extract_slots([
        user("Je veux un devis autoconsommation"),
        assistant(
            "Nom: Client Inventé. Telephone: 0611111111. Ville: Casablanca. "
            "Votre consommation est 900 kWh et votre branchement triphase."
        ),
        user("Mon branchement est monophase"),
    ])
    assert slots.name == ""
    assert slots.phone == ""
    assert slots.city == ""
    assert slots.monthly_consumption_kwh is None
    assert slots.phase == "monophase"


def test_latest_customer_technical_corrections_override_earlier_values():
    slots = extract_slots([
        user("Devis pompage : pompe 2 CV, debit 5 m3/h, HMT 70 m"),
        assistant("La pompe fait 10 CV, le debit 20 m3/h et la HMT 100 m."),
        user("Correction : 50 CV, 12 m3/h et HMT 80 m"),
    ])
    assert slots.existing_pump_cv == 50
    assert slots.flow_m3_h == 12
    assert slots.hmt_m == 80
    consumption = extract_slots([
        user("Devis autoconsommation : conso 1000 kWh par mois"),
        user("Ma consommation est finalement 3000 kWh par mois"),
    ])
    assert consumption.monthly_consumption_kwh == 3000


def test_latest_explicit_client_corrections_override_earlier_name_city_and_phone():
    slots = extract_slots([
        user("Nom: Moctar. Telephone: 0600000000. Ville: Rabat."),
        assistant("Vos coordonnées sont enregistrées."),
        user("Correction : mon nom est Abdou a Agadir. Mon telephone est 0700000000."),
        assistant("Nom: Client Inventé. Telephone: 0611111111. Ville: Casablanca."),
    ])
    assert slots.name.casefold() == "abdou"
    assert slots.city == "Agadir"
    assert slots.phone == "0700000000"


@pytest.mark.parametrize("question", [
    "Comment fonctionne le variateur solaire ?",
    "Combien de panneaux faut-il pour alimenter cette installation ?",
])
def test_technical_question_interrupts_prior_quote_collection_without_creating_quote(question):
    messages = [
        user(
            "Je veux un devis pompage pour mon puits. Nom: Moctar. "
            "Telephone: 0600000000. Ville: Rabat. Debit 12 m3/h et HMT 80 m."
        ),
        assistant("Pour préparer votre devis, confirmez ces informations."),
        user(question),
    ]
    factory = Mock()
    response = AssistantDevisManager().handle(messages, quote_factory=factory)
    assert response.handled is False
    assert response.quote is None
    factory.assert_not_called()


def test_complete_progressive_quote_does_not_reask_provided_contacts():
    manager = AssistantDevisManager()
    factory = Mock(return_value={
        "id": 123,
        "ref": "HSQ-CONVERSATION",
        "total_ttc": "25 000 DH",
        "kwc": 5.5,
        "panels": 10,
        "system_summary": "Systeme solaire autoconsommation",
        "download_url": "/api/quotes/123/document.pdf",
    })
    history = []
    exchanges = (
        "Je veux un devis autoconsommation pour ma maison",
        "mon nom moctar a rabat",
        "Mon telephone est 0600000000",
        "Mon branchement est monophase",
        "Mon compteur est numerique",
        "La toiture est accessible",
        "Ma consommation est de 1000 kWh par mois",
    )
    for index, text in enumerate(exchanges):
        history.append(user(text))
        response = manager.handle(sanitize_messages(history), quote_factory=factory)
        assert response.handled
        if index >= 1:
            assert "name" not in response.missing
            assert "city" not in response.missing
        if index >= 2:
            assert "phone" not in response.missing
        if index < len(exchanges) - 1:
            assert response.quote is None
            factory.assert_not_called()
        history.append(assistant(response.content))

    factory.assert_called_once()
    project, data, contact = factory.call_args.args
    assert project == "photovoltaic"
    assert data["monthly_consumption_kwh"] == 1000
    assert data["phase"] == "monophase"
    assert contact["name"].casefold() == "moctar"
    assert contact["phone"] == "0600000000"
    assert contact["location"] == "Rabat"
    assert response.quote["id"] == 123
    assert "<<<DEVIS_DATA:" in response.content


@pytest.fixture
def arithmetic_client(tmp_path, monkeypatch):
    # A minimal Flask harness exercises the real API handlers without database
    # initialization, password hashing, catalogue seeding, or an Ollama process.
    app = Flask("assistant-conversation-regressions")
    app.config.update(TESTING=True, DATABASE=str(tmp_path / "unused.db"), TRUSTED_PROXY_HOPS=0)
    app.extensions["assistant_quota"] = AssistantQuota()
    app.register_blueprint(bp)
    monkeypatch.setattr("app.db.list_company_settings", lambda: [])
    return app.test_client()


@pytest.mark.parametrize("endpoint", ["/api/assistant/chat", "/api/assistant/chat/stream"])
@pytest.mark.parametrize("calculation", ["590 W * 5", "590w *5"])
def test_panel_arithmetic_is_exact_during_quote_collection_without_ollama_or_quote(
    arithmetic_client, endpoint, calculation
):
    history = [
        user("Je veux un devis autoconsommation pour ma maison"),
        assistant("Pour préparer votre devis, il me manque votre nom et votre telephone."),
        user(calculation),
    ]
    with patch("app.services.ai_service.requests.post") as post, patch(
        "app.routes._assistant_quote_factory"
    ) as quote_factory:
        response = arithmetic_client.post(endpoint, json={"messages": history})
        if endpoint.endswith("/stream"):
            events = [json.loads(line) for line in response.data.decode().splitlines()]
            assert events[-1]["type"] == "final"
            payload = events[-1]
        else:
            payload = response.get_json()
    assert response.status_code == 200
    compact = re.sub(r"\s+", "", payload["content"]).replace(",", ".").casefold()
    assert "2950wc" in compact
    assert "2.95kwc" in compact
    assert not payload.get("quote_ready", False)
    assert "quote" not in payload
    post.assert_not_called()
    quote_factory.assert_not_called()
