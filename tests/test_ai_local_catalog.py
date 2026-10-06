"""Regression coverage for the assistant's read-only, local product context."""

import json
import re
from unittest.mock import MagicMock, Mock, patch

import pytest

from app import create_app
from app.db import get_db
from app.services.anti_abuse import AssistantQuota
from app.services.ai_service import (
    chat_with_ollama,
    find_catalog_products,
    is_catalog_query,
    messages_with_system_prompt,
    project_branch,
    stream_ollama_chat,
)


def user(text):
    return {"role": "user", "content": text}


def insert_product(db, product_id, reference, category, **overrides):
    values = {
        "id": product_id,
        "reference": reference,
        "category": category,
        "brand": "LONGI",
        "model": "Mono 550",
        "description": "Panneau solaire monocristallin",
        "power_w": 550,
        "power_kw": None,
        "capacity_kwh": None,
        "sale_price": 1250,
        "stock": 5,
        "active": 1,
        "demo": 0,
        "currency": "DH",
        "voltage": None,
        "vat_rate": 20,
        "technical_specs_json": "{}",
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    db.execute(
        f"INSERT INTO products ({columns}) VALUES ({placeholders})",
        tuple(values.values()),
    )


@pytest.fixture(scope="module")
def _catalog_app_base(tmp_path_factory):
    database = str(tmp_path_factory.mktemp("ai-local-catalog") / "catalog.db")
    return create_app({"TESTING": True, "DATABASE": database}), database


@pytest.fixture
def catalog_app(_catalog_app_base):
    app, database = _catalog_app_base
    app.config["DATABASE"] = database
    app.extensions["assistant_quota"] = AssistantQuota()
    with app.app_context():
        db = get_db()
        db.execute("DELETE FROM pump_curve_points")
        db.execute("DELETE FROM products")
        insert_product(db, 1001, "PANEL-LONGI-550", "panels")
        insert_product(
            db, 1002, "BAT-DEYE-512", "batteries", brand="DEYE",
            model="SE-G5.1", description="Batterie lithium pour stockage résidentiel",
            power_w=None, capacity_kwh=5.12, sale_price=8500,
        )
        insert_product(
            db, 1003, "INV-DEYE-6", "inverters", brand="DEYE",
            model="SUN-6K", description="Onduleur solaire hybride pour maison",
            power_w=None, power_kw=6, sale_price=9500,
        )
        insert_product(
            db, 1004, "BAT-OTHER-5", "batteries", brand="AUTRE",
            model="Lithium 5", description="Batterie solaire lithium",
            power_w=None, capacity_kwh=5, sale_price=7900,
        )
        insert_product(
            db, 2001, "DRIVE-INVT-220", "drives", brand="INVT",
            model="GD100 220V", description="Variateur solaire pour pompe 2 CV",
            power_w=None, power_kw=2.2, voltage=220, sale_price=1800,
        )
        insert_product(
            db, 2002, "PUMP-IRRIGATION", "pumps", brand="POMPE",
            model="Forage 3CV", description="Pompe de puits pour irrigation",
            power_w=None, power_kw=2.2, voltage=380, sale_price=2500,
        )
        db.commit()
    try:
        yield app
    finally:
        # The missing-file case changes this configuration deliberately. Restore it
        # even on failure so following cases retain a real, isolated test catalogue.
        app.config["DATABASE"] = database


def ollama_json_response(content="Voici les produits du catalogue local."):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"message": {"role": "assistant", "content": content}}
    return response


def ollama_stream_response(*chunks):
    response = MagicMock()
    response.__enter__.return_value = response
    response.raise_for_status.return_value = None
    response.iter_lines.return_value = [
        json.dumps({"message": {"content": text}}) for text in chunks
    ]
    return response


def test_domestic_search_ignores_pumping_claims_from_assistant(catalog_app):
    messages = [
        user("Je cherche des panneaux pour ma maison"),
        {"role": "assistant", "content": "Une pompe de puits et un variateur 2 CV sont nécessaires."},
        user("Quel matériel est disponible et à quel prix ?"),
    ]
    with catalog_app.app_context():
        assert project_branch(messages) == "domestic"
        products = find_catalog_products(messages)
    assert products
    assert not {2001, 2002} & {item["id"] for item in products}


def test_latest_user_domestic_intent_replaces_earlier_well_project(catalog_app):
    messages = [
        user("J'ai un puits pour irriguer et une pompe"),
        user("Maintenant je veux acheter des panneaux pour ma maison et sa toiture"),
    ]
    with catalog_app.app_context():
        assert project_branch(messages) == "domestic"
        products = find_catalog_products(messages)
    assert {item["id"] for item in products} == {1001}


def test_explicit_well_request_allows_solar_drive(catalog_app):
    messages = [user("Quel prix pour un variateur solaire 220V pour la pompe de mon puits ?")]
    with catalog_app.app_context():
        assert project_branch(messages) == "pumping"
        products = find_catalog_products(messages)
    assert 2001 in {item["id"] for item in products}


def test_catalog_excludes_unsellable_or_foreign_currency_products(catalog_app):
    with catalog_app.app_context():
        db = get_db()
        exclusions = [
            {"stock": 0}, {"stock": -1}, {"demo": 1}, {"active": 0},
            {"sale_price": 0}, {"sale_price": -10}, {"currency": "EUR"},
        ]
        for index, override in enumerate(exclusions, start=1010):
            insert_product(db, index, f"INVALID-{index}", "panels", **override)
        db.commit()
        products = find_catalog_products([user("Prix de panneaux LONGI pour une maison")])
    assert {item["id"] for item in products} == {1001}


def test_accented_brand_query_ranks_relevant_deye_battery_first(catalog_app):
    with catalog_app.app_context():
        accented = find_catalog_products([user("Quel prix pour une batterie Déye ?")])
        plain = find_catalog_products([user("Quel prix pour une batterie Deye ?")])
    assert accented and plain
    assert accented[0]["id"] == plain[0]["id"] == 1002
    assert 1003 not in {item["id"] for item in accented}


def test_catalog_payload_is_bounded_and_keeps_product_units_and_ht_price(catalog_app):
    with catalog_app.app_context():
        for query, product_id, expected_unit in [
            ("Prix panneau LONGI", 1001, "Wc"),
            ("Prix batterie DEYE", 1002, "kWh"),
            ("Prix onduleur DEYE", 1003, "kW"),
        ]:
            products = find_catalog_products([user(query)])
            assert 1 <= len(products) <= 3
            product = next(item for item in products if item["id"] == product_id)
            assert product["source"] == "local_sqlite"
            assert product["reference"]
            assert product["en_stock"] is True
            assert product["currency"] == "DH"
            assert expected_unit in product["description"]
        panel = find_catalog_products([user("Prix panneau LONGI")])[0]
    assert panel["price"] == 1250  # sale_price is HT; do not silently add VAT.


def test_product_price_is_catalog_intent_but_explicit_quote_is_not():
    assert is_catalog_query([user("Quel est le prix d'une batterie DEYE ?")])
    assert is_catalog_query([user("Bonjour, je veux acheter des panneaux")])
    assert not is_catalog_query([user("Je veux un devis solaire hybride avec batteries pour ma maison")])
    assert not is_catalog_query([user("Bonjour")])


def test_missing_database_is_not_created_by_catalog_lookup(catalog_app, tmp_path):
    missing_database = tmp_path / "does-not-exist.db"
    catalog_app.config["DATABASE"] = str(missing_database)
    with catalog_app.app_context():
        assert find_catalog_products([user("Prix panneau LONGI")]) == []
    assert not missing_database.exists()


def test_json_ollama_injects_local_products_and_keeps_quote_marker(catalog_app):
    messages = [user("Prix d'un panneau LONGI pour la toiture de ma maison")]
    with catalog_app.app_context():
        products = find_catalog_products(messages)
        injected = messages_with_system_prompt(messages, products=products)
        with patch("app.services.ai_service.requests.post", return_value=ollama_json_response()) as post:
            result = chat_with_ollama(messages, products=products)
    system_text = injected[0]["content"]
    assert injected[0]["role"] == "system"
    assert "PANEL-LONGI-550" in system_text
    assert "1250" in system_text.replace(" ", "")
    assert "Wc" in system_text
    assert "<<<DEVIS_DATA:{...}>>>" in system_text
    assert injected[1:] == messages
    assert result["role"] == "assistant"
    payload = post.call_args.kwargs["json"]
    assert payload["keep_alive"] == -1
    assert payload["stream"] is False
    assert payload["messages"] == injected


def test_streaming_ollama_preserves_chunks_and_injects_same_catalog(catalog_app):
    messages = [user("Comment fonctionne une batterie DEYE ?")]
    response = ollama_stream_response("Batterie ", "DEYE disponible.")
    with catalog_app.app_context():
        products = find_catalog_products(messages)
        with patch("app.services.ai_service.requests.post", return_value=response) as post:
            chunks = list(stream_ollama_chat(messages, products=products))
    assert "".join(chunks) == "Batterie DEYE disponible."
    payload = post.call_args.kwargs["json"]
    assert payload["keep_alive"] == -1
    assert payload["stream"] is True
    assert "BAT-DEYE-512" in payload["messages"][0]["content"]


def test_catalog_chat_returns_suggestions_without_starting_contact_collection(catalog_app):
    with patch(
        "app.services.ai_service.requests.post",
        return_value=ollama_json_response("La batterie DEYE est disponible au catalogue."),
    ) as post:
        response = catalog_app.test_client().post(
            "/api/assistant/chat",
            json={"messages": [user("Bonjour, quel prix pour une batterie DEYE ?")]},
        )
    assert response.status_code == 200
    payload = response.get_json()
    assert "BAT-DEYE-512" in payload["content"]
    assert "8500" in payload["content"].replace(" ", "")
    assert payload["suggested_products"][0]["id"] == 1002
    assert payload["suggested_products"][0]["price"] == 8500
    assert "quote_ready" not in payload
    post.assert_called_once()
    assert post.call_args.args[0].endswith("/api/chat")


def test_catalog_stream_final_event_contains_suggestions_and_intact_tokens(catalog_app):
    with patch(
        "app.services.ai_service.requests.post",
        return_value=ollama_stream_response("Batterie DEYE ", "en stock."),
    ) as post:
        response = catalog_app.test_client().post(
            "/api/assistant/chat/stream",
            json={"messages": [user("Quel prix pour une batterie DEYE ?")]},
        )
        events = [json.loads(line) for line in response.data.decode().splitlines()]
    assert response.status_code == 200
    assert events[-1]["type"] == "final"
    assert "BAT-DEYE-512" in events[-1]["content"]
    assert "8500" in events[-1]["content"].replace(" ", "")
    assert events[-1]["suggested_products"][0]["id"] == 1002
    assert "".join(event.get("content", "") for event in events if event["type"] == "token") == events[-1]["content"]
    post.assert_called_once()


def assert_no_domestic_pumping_leak(content):
    assert not re.search(r"\b(?:pompes?|pompage|variateurs?|cv)\b", content.casefold())


def test_domestic_json_response_blocks_ollama_pump_hallucination(catalog_app):
    hallucinated = (
        "Pour votre maison, installez un variateur pour pompe 2 CV. "
        "Consultez le Catalogue pour les panneaux solaires."
    )
    with patch(
        "app.services.ai_service.requests.post",
        return_value=ollama_json_response(hallucinated),
    ) as post:
        response = catalog_app.test_client().post(
            "/api/assistant/chat",
            json={"messages": [user("Quels panneaux pour ma maison ?")]},
        )
    assert response.status_code == 200
    content = response.get_json()["content"]
    assert content.strip()
    assert_no_domestic_pumping_leak(content)
    post.assert_called_once()


def test_domestic_stream_blocks_forbidden_words_split_across_chunks(catalog_app):
    chunks = (
        "Pour votre maison, un vari",
        "ateur pour pom",
        "pe 2 CV est adapté. ",
        "Choisissez des panneaux 550 Wc dans Catalogue.",
    )
    with patch(
        "app.services.ai_service.requests.post",
        return_value=ollama_stream_response(*chunks),
    ) as post:
        response = catalog_app.test_client().post(
            "/api/assistant/chat/stream",
            json={"messages": [user("Quels panneaux pour ma maison ?")]},
        )
        events = [json.loads(line) for line in response.data.decode().splitlines()]
    assert response.status_code == 200
    assert events[-1]["type"] == "final"
    tokens = "".join(event.get("content", "") for event in events if event["type"] == "token")
    assert tokens.strip()
    assert_no_domestic_pumping_leak(tokens)
    assert_no_domestic_pumping_leak(events[-1]["content"])
    post.assert_called_once()


def test_ollama_stream_keeps_fragmented_quote_marker_for_existing_parser(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "stream-quote-marker.db")})
    chunks = (
        "Voici votre estimation solaire. ",
        "<<<DE",
        'VIS_DATA:{"mode":"ongrid","nom":"Client IA",',
        '"telephone":"0600000000","ville":"Rabat",',
        '"consommation":1000,"phase":"monophase"}',
        ">>>",
    )
    with patch(
        "app.services.ai_service.requests.post",
        return_value=ollama_stream_response(*chunks),
    ):
        response = app.test_client().post(
            "/api/assistant/chat/stream",
            json={"messages": [user("Preparation finale client")]},
        )
        events = [json.loads(line) for line in response.data.decode().splitlines()]
    assert response.status_code == 200
    final = events[-1]
    assert final["type"] == "final"
    assert final["quote_ready"] is True
    assert final["quote"]["total_ttc"].endswith("DH")
    assert final["quote"]["system_summary"].startswith("Systeme solaire")
    assert final["quote"]["download_url"] == f"/api/quotes/{final['quote']['id']}/document.pdf"
    assert "<<<DEVIS_DATA" not in final["content"]
    token_text = "".join(event.get("content", "") for event in events if event["type"] == "token")
    assert "Voici votre estimation solaire." in token_text
    assert "<<<DEVIS_DATA" not in token_text


def test_no_available_product_adds_no_suggestions_and_forbids_invented_prices(catalog_app):
    with catalog_app.app_context():
        db = get_db()
        db.execute("UPDATE products SET stock = 0 WHERE category = 'panels'")
        db.commit()
        assert find_catalog_products([user("Prix panneau LONGI pour ma maison")]) == []
    with patch(
        "app.services.ai_service.requests.post",
        return_value=ollama_json_response("La référence disponible doit être vérifiée dans Catalogue."),
    ) as post:
        response = catalog_app.test_client().post(
            "/api/assistant/chat",
            json={"messages": [user("Prix panneau LONGI pour ma maison")]},
        )
    assert response.status_code == 200
    assert "suggested_products" not in response.get_json()
    prompt = post.call_args.kwargs["json"]["messages"][0]["content"].casefold()
    assert "prix" in prompt
    assert "invent" in prompt
    assert "aucun" in prompt or "absence" in prompt or "indisponible" in prompt
    assert "PANEL-LONGI-550" not in prompt
    post.assert_called_once()


def test_catalog_answer_replaces_unsupported_price_with_real_sqlite_price(catalog_app):
    with patch(
        "app.services.ai_service.requests.post",
        return_value=ollama_json_response("La batterie DEYE SE-G5.1 est disponible à 999 DH HT."),
    ):
        response = catalog_app.test_client().post(
            "/api/assistant/chat",
            json={"messages": [user("Quel prix pour une batterie DEYE ?")]},
        )
    assert response.status_code == 200
    payload = response.get_json()
    content = payload["content"].replace("\u00a0", " ")
    assert not re.search(r"\b999\s*DH\b", content, re.IGNORECASE)
    assert "8500" in content.replace(" ", "")
    assert payload["suggested_products"][0]["price"] == 8500


def test_pumping_stream_rejects_panel_cv_split_at_decimal_without_domestic_advice(catalog_app):
    with patch(
        "app.services.ai_service.requests.post",
        return_value=ollama_stream_response(
            "Panneau 1.", "5 CV pour votre pompe. ", "Vérifiez la plaque moteur."
        ),
    ):
        response = catalog_app.test_client().post(
            "/api/assistant/chat/stream",
            json={"messages": [user("Quel panneau pour la pompe de mon puits ?")]},
        )
        events = [json.loads(line) for line in response.data.decode().splitlines()]
    assert response.status_code == 200
    tokens = "".join(event.get("content", "") for event in events if event["type"] == "token")
    for content in (tokens, events[-1]["content"]):
        normalized = content.casefold()
        assert not re.search(r"\bpanneau\s+1\.5\s*cv\b", normalized)
        assert "wc" in normalized
        assert "maison" not in normalized
        assert "batterie" not in normalized


def test_unavailable_catalog_does_not_expose_model_invented_reference_or_price(catalog_app):
    with catalog_app.app_context():
        db = get_db()
        db.execute("UPDATE products SET stock = 0")
        db.commit()
    with patch(
        "app.services.ai_service.requests.post",
        return_value=ollama_json_response(
            "Le panneau SuperSolaire-X999 de LONGI est disponible pour 999 DH HT."
        ),
    ):
        response = catalog_app.test_client().post(
            "/api/assistant/chat",
            json={"messages": [user("Quel prix pour acheter un panneau LONGI ?")]},
        )
    assert response.status_code == 200
    payload = response.get_json()
    assert "suggested_products" not in payload
    assert "SuperSolaire-X999" not in payload["content"]
    assert not re.search(r"\b999\s*DH\b", payload["content"], re.IGNORECASE)
    assert "catalogue" in payload["content"].casefold() or "conseiller" in payload["content"].casefold()


def test_domestic_intent_does_not_reuse_old_pumping_quote_slots(catalog_app):
    with catalog_app.app_context():
        before = get_db().execute("SELECT COUNT(*) FROM quote_requests").fetchone()[0]
    messages = [
        user(
            "Je veux un devis pompage solaire pour mon puits. Nom: Client Test. "
            "Telephone: 0600000000. Ville: Fes. Debit 12 m3/h et HMT 80 m."
        ),
        user("Finalement je veux un devis pour ma maison."),
    ]
    with patch(
        "app.services.ai_service.requests.post",
        return_value=ollama_json_response(
            "Pour votre maison, indiquez votre consommation mensuelle en kWh. "
            "Nous dimensionnerons les panneaux en Wc et l'onduleur adapté."
        ),
    ) as post:
        response = catalog_app.test_client().post("/api/assistant/chat", json={"messages": messages})
    assert response.status_code == 200
    payload = response.get_json()
    assert "maison" in payload["content"].casefold()
    assert_no_domestic_pumping_leak(payload["content"])
    assert "hmt" not in payload["content"].casefold()
    assert not payload.get("quote_ready", False)
    post.assert_called_once()
    with catalog_app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM quote_requests").fetchone()[0] == before


def test_domestic_answer_cannot_create_pumping_quote_via_type_alias(catalog_app):
    marker = (
        'Voici votre estimation. <<<DEVIS_DATA:{"type":"pumping","name":"Agriculteur",'
        '"phone":"0611111111","city":"Fes","debit":12,"hmt":80}>>>'
    )
    with catalog_app.app_context():
        before = get_db().execute("SELECT COUNT(*) FROM quote_requests").fetchone()[0]
    with patch(
        "app.services.ai_service.requests.post",
        return_value=ollama_json_response(marker),
    ) as post:
        response = catalog_app.test_client().post(
            "/api/assistant/chat",
            json={"messages": [user("Preparation finale client pour ma maison")]},
        )
    assert response.status_code == 200
    payload = response.get_json()
    assert not payload.get("quote_ready", False)
    assert "<<<DEVIS_DATA" not in payload["content"]
    assert_no_domestic_pumping_leak(payload["content"])
    post.assert_called_once()
    with catalog_app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM quote_requests").fetchone()[0] == before


def test_commercial_answer_cannot_invent_model_or_power_with_matching_real_price(catalog_app):
    with patch(
        "app.services.ai_service.requests.post",
        return_value=ollama_json_response("Panneau FICTIF900 - 900 Wc - 1250 DH HT disponible."),
    ):
        response = catalog_app.test_client().post(
            "/api/assistant/chat",
            json={"messages": [user("Quel prix pour un panneau LONGI pour ma maison ?")]},
        )
    assert response.status_code == 200
    payload = response.get_json()
    assert "FICTIF900" not in payload["content"]
    assert "900 Wc" not in payload["content"]
    assert "PANEL-LONGI-550" in payload["content"]
    assert "550 Wc" in payload["content"]
    assert payload["suggested_products"][0]["id"] == 1001


def test_commercial_stream_lists_each_reference_once_for_multiple_model_sentences(catalog_app):
    with patch(
        "app.services.ai_service.requests.post",
        return_value=ollama_stream_response(
            "La batterie DEYE est adaptée. ",
            "Elle coûte 8500 DH HT. ",
            "Elle est en stock.",
        ),
    ):
        response = catalog_app.test_client().post(
            "/api/assistant/chat/stream",
            json={"messages": [user("Quel prix pour une batterie DEYE ?")]},
        )
        events = [json.loads(line) for line in response.data.decode().splitlines()]
    assert response.status_code == 200
    final = events[-1]
    assert final["type"] == "final"
    tokens = "".join(event.get("content", "") for event in events if event["type"] == "token")
    assert tokens == final["content"]
    assert final["suggested_products"]
    for product in final["suggested_products"]:
        assert tokens.count(product["reference"]) == 1


def test_commercial_chat_ignores_unsolicited_model_quote_marker(catalog_app):
    with catalog_app.app_context():
        before = get_db().execute("SELECT COUNT(*) FROM quote_requests").fetchone()[0]
    content = (
        "La batterie DEYE est en stock. "
        '<<<DEVIS_DATA:{"mode":"pumping","name":"Client inventé",'
        '"phone":"0611111111","city":"Fes","debit":12,"hmt":80}>>>'
    )
    with patch(
        "app.services.ai_service.requests.post",
        return_value=ollama_json_response(content),
    ):
        response = catalog_app.test_client().post(
            "/api/assistant/chat",
            json={"messages": [user("Quel prix pour une batterie DEYE ?")]},
        )
    assert response.status_code == 200
    payload = response.get_json()
    assert not payload.get("quote_ready", False)
    assert "quote" not in payload
    assert "<<<DEVIS_DATA" not in payload["content"]
    assert "BAT-DEYE-512" in payload["content"]
    assert "8500" in payload["content"].replace(" ", "")
    assert payload["suggested_products"][0]["id"] == 1002
    with catalog_app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM quote_requests").fetchone()[0] == before
