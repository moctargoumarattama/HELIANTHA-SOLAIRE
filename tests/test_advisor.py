import json

from app import create_app


def post_message(client, message, state=None):
    return client.post(
        "/api/advisor/message",
        json={"message": message, "state": state or {}},
    )


def test_advisor_detects_pumping_and_extracts_multiple_values(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "advisor-pumping.db")})
    client = app.test_client()

    payload = post_message(client, "J'ai un forage de 60 m a Marrakech et je veux 25 m3 par jour.").get_json()

    assert payload["state"]["project_type"] == "pumping"
    assert payload["state"]["collected_data"]["city"] == "Marrakech"
    assert payload["state"]["collected_data"]["water_need"] == 25
    assert payload["state"]["collected_data"]["depth"] == 60
    assert any(action["action"] == "calculate" for action in payload["actions"])


def test_advisor_short_yes_depends_on_last_question(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "advisor-yes.db")})
    client = app.test_client()

    state = {
        "project_type": "pumping",
        "last_question_id": "pump_existing",
        "collected_data": {"water_need": 20},
    }
    payload = post_message(client, "oui", state=state).get_json()

    assert payload["state"]["collected_data"]["pump_existing"] is True
    assert "profondeur" in payload["reply"].lower()


def test_advisor_can_change_project_without_staying_blocked(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "advisor-switch.db")})
    client = app.test_client()

    first = post_message(client, "je veux installer une pompe").get_json()
    second = post_message(client, "off grid", state=first["state"]).get_json()

    assert first["state"]["project_type"] == "pumping"
    assert second["state"]["project_type"] == "offgrid"
    assert "consommation" in second["reply"].lower()


def test_advisor_answers_faq_and_resumes_flow(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "advisor-faq.db")})
    client = app.test_client()
    state = {"project_type": "hybrid", "collected_data": {"bill": 900}}

    payload = post_message(client, "c'est quoi un onduleur ?", state=state).get_json()

    assert "transforme" in payload["reply"].lower()
    assert "continuer" in payload["reply"].lower()
    assert "coupures" in payload["reply"].lower()


def test_advisor_unknown_message_is_saved(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "advisor-unknown.db")})
    client = app.test_client()

    post_message(client, "xyz totalement incomprehensible")

    with app.app_context():
        from app.db import get_db

        row = get_db().execute("SELECT * FROM advisor_unknown_messages").fetchone()
        assert row is not None
        assert row["status"] == "new"


def test_advisor_calculates_real_quote_when_ready(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "advisor-calc.db")})
    client = app.test_client()
    state = {
        "project_type": "pumping",
        "collected_data": {"water_need": 25, "depth": 60, "city": "Marrakech"},
    }

    payload = client.post("/api/advisor/calculate", json={"state": state}).get_json()

    assert payload["quote"]["quote_reference"].startswith("HSQ-")
    assert payload["quote"]["quote_id"] is not None
    assert any("predevis" in action.get("href", "") for action in payload["actions"])

    with app.app_context():
        from app.db import get_db

        saved = get_db().execute("SELECT * FROM quote_requests").fetchone()
        assert saved is not None
        result = json.loads(saved["result_json"])
        assert result["project"] == "pumping"


def test_advisor_disambiguates_house_solar_then_detects_hybrid(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "advisor-hybrid.db")})
    client = app.test_client()

    first = post_message(client, "salut je veux solaire maison").get_json()
    second = post_message(client, "oui mais bcp de coupure", state=first["state"]).get_json()

    assert "reseau electrique" in first["reply"].lower()
    assert second["state"]["project_type"] == "hybrid"
    assert second["state"]["collected_data"]["network_existing"] is True
    assert second["state"]["collected_data"]["outages"] is True
    assert "facture" in second["reply"].lower() or "consommation" in second["reply"].lower()


def test_advisor_records_bill_and_answers_battery_question_in_same_message(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "advisor-bill-faq.db")})
    client = app.test_client()
    state = {
        "project_type": "hybrid",
        "last_question_id": "monthly_kwh",
        "pending_question_id": "monthly_kwh",
        "collected_data": {},
    }

    payload = post_message(client, "900 dh et batterie dure combien", state=state).get_json()

    assert payload["state"]["collected_data"]["bill"] == 900
    assert "duree depend" in payload["reply"].lower()
    assert "continuer" in payload["reply"].lower()
    assert "appareils" in payload["reply"].lower() or "coupures" in payload["reply"].lower()


def test_advisor_city_correction_replaces_previous_city(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "advisor-city.db")})
    client = app.test_client()
    state = {"project_type": "ongrid", "last_question_id": "city", "pending_question_id": "city"}

    first = post_message(client, "marrakech", state=state).get_json()
    second = post_message(client, "finalement rabat", state=first["state"]).get_json()

    assert first["state"]["collected_data"]["city"] == "Marrakech"
    assert second["state"]["collected_data"]["city"] == "Rabat"


def test_advisor_depth_correction_replaces_previous_depth(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "advisor-depth.db")})
    client = app.test_client()
    state = {"project_type": "pumping", "last_question_id": "depth", "pending_question_id": "depth"}

    first = post_message(client, "60m", state=state).get_json()
    second = post_message(client, "non c'est pas 60 c'est 85m", state=first["state"]).get_json()

    assert first["state"]["collected_data"]["depth"] == 60
    assert second["state"]["collected_data"]["depth"] == 85


def test_advisor_changes_project_from_ev_to_house_solar(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "advisor-ev-switch.db")})
    client = app.test_client()

    first = post_message(client, "je veux une borne").get_json()
    second = post_message(client, "non je parle pas voiture, je veux solaire maison", state=first["state"]).get_json()
    third = post_message(client, "oui", state=second["state"]).get_json()

    assert first["state"]["project_type"] == "ev"
    assert "reseau electrique" in second["reply"].lower()
    assert third["state"]["project_type"] in {"ongrid", "hybrid"}
    assert third["state"]["project_type"] != "ev"


def test_advisor_learns_intent_example_from_admin_action(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "advisor-learn-intent.db")})
    client = app.test_client()

    with app.app_context():
        from app.db import add_advisor_unknown, get_db

        add_advisor_unknown(
            "session-test",
            "je veux qu'un technicien passe voir mon terrain",
            "je veux qu un technicien passe voir mon terrain",
            {"project_type": "", "current_intent": "give_information"},
            "Compréhension insuffisante",
        )
        item_id = get_db().execute("SELECT id FROM advisor_unknown_messages ORDER BY id DESC LIMIT 1").fetchone()["id"]

    client.post(
        "/admin/conseiller",
        data={
            "action": "save_intent",
            "item_id": item_id,
            "intent": "request_visit",
            "example_text": "je veux qu'un technicien passe voir mon terrain",
            "project_type": "",
        },
        follow_redirects=True,
    )
    payload = post_message(client, "un technicien peut venir chez moi ?").get_json()

    assert payload["state"]["current_intent"] == "request_visit"
    assert "visite" in payload["reply"].lower() or "rappeler" in payload["reply"].lower()


def test_admin_advisor_page_uses_simple_labels(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "advisor-admin-ui.db")})
    client = app.test_client()
    client.post("/admin/login", data={"password": "heliantha2026"})

    with app.app_context():
        from app.db import add_advisor_unknown

        add_advisor_unknown(
            "session-ui",
            "je veux qu'un technicien passe chez moi",
            "je veux qu un technicien passe chez moi",
            {"project_type": "offgrid", "current_intent": "request_visit"},
            "Projet non reconnu",
        )

    response = client.get("/admin/conseiller")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Conseiller HeliAntha" in html
    assert "À vérifier" in html
    assert "Le Conseiller propose" in html
    assert "Corriger" in html
    assert "Ignorer" in html
    assert "Associer à une intention" not in html
    assert "Créer un synonyme" not in html
    assert "Créer une réponse" not in html


def test_admin_advisor_page_shows_human_suggestion(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "advisor-admin-suggestion.db")})
    client = app.test_client()
    client.post("/admin/login", data={"password": "heliantha2026"})

    with app.app_context():
        from app.db import add_advisor_unknown, get_db

        add_advisor_unknown(
            "session-admin",
            "je veux qu'un technicien passe chez moi",
            "je veux qu un technicien passe chez moi",
            {"project_type": "offgrid", "current_intent": "request_visit"},
            "Projet non reconnu",
        )
        item_id = get_db().execute("SELECT id FROM advisor_unknown_messages ORDER BY id DESC LIMIT 1").fetchone()["id"]

    response = client.get("/admin/conseiller")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Demande de visite" in html
    assert str(item_id) in html
    assert "LE CONSEILLER PROPOSE" in html


def test_advisor_uses_dynamic_synonym_saved_in_database(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "advisor-synonym.db")})
    client = app.test_client()

    with app.app_context():
        from app.db import save_advisor_synonym

        save_advisor_synonym("plaque_signaletique", "etiquette pompe", category="pumping", project_type="pumping", validated_by="Admin")

    payload = post_message(client, "j'ai perdu l'etiquette pompe").get_json()

    assert payload["state"]["current_topic"] == "plaque_signaletique"
    assert "photo de la pompe" in payload["reply"].lower() or "pas bloquant" in payload["reply"].lower()


def test_advisor_uses_learned_faq_saved_in_database(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "advisor-faq-learned.db")})
    client = app.test_client()

    with app.app_context():
        from app.db import save_advisor_knowledge_item

        save_advisor_knowledge_item(
            "ongrid",
            "Pluie",
            "Les panneaux fonctionnent-ils sous la pluie ?",
            "Oui. Ils produisent encore, mais moins qu'en plein soleil.",
            keywords="pluie nuage mauvais temps panneaux",
            validated_by="Admin",
        )

    payload = post_message(client, "les panneaux marchent quand il pleut ?").get_json()

    assert "produisent encore" in payload["reply"].lower()


def test_advisor_does_not_repeat_same_question_when_user_does_not_know(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "advisor-unknown-answer.db")})
    client = app.test_client()
    state = {
        "project_type": "ongrid",
        "last_question_id": "monthly_kwh",
        "pending_question_id": "monthly_kwh",
        "collected_data": {},
    }

    payload = post_message(client, "je sais pas", state=state).get_json()

    assert "facture" in payload["reply"].lower()
    assert "appareils" in payload["reply"].lower()
    assert "consommation mensuelle" not in payload["reply"].lower()


def test_advisor_keeps_coherent_state_in_chaotic_conversation(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "advisor-chaos.db")})
    client = app.test_client()

    payload = post_message(client, "salut").get_json()
    payload = post_message(client, "je veux solaire maison", state=payload["state"]).get_json()
    payload = post_message(client, "jsuis a casa", state=payload["state"]).get_json()
    payload = post_message(client, "mais ya bcp coupure", state=payload["state"]).get_json()
    payload = post_message(client, "batterie sa coute cher ?", state=payload["state"]).get_json()
    payload = post_message(client, "ma facture 1200", state=payload["state"]).get_json()
    payload = post_message(client, "finalement projet a rabat", state=payload["state"]).get_json()
    payload = post_message(client, "je veux garder juste frigo lumiere wifi", state=payload["state"]).get_json()

    data = payload["state"]["collected_data"]
    assert payload["state"]["project_type"] == "hybrid"
    assert data["city"] == "Rabat"
    assert data["bill"] == 1200
    assert data["outages"] is True
    assert "frigo" in data["priority_loads"]
    assert "eclairage" in data["priority_loads"]
    assert "wifi" in data["priority_loads"]
