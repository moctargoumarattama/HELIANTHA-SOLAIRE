"""Unit and integration tests for RAG dynamic catalog, Darija tolerance, Devis CTA actions, and Agricultural Pumping Sizing & Context."""

import pytest
from app.services.ai_service import (
    get_dynamic_suggested_products,
    match_darija,
    _detect_bill_and_build_cta,
    _detect_pumping_power,
    _get_commercial_direct_answer,
    _guard_technical_content,
    _sanitize_ai_response,
    quick_assistant_response,
    quick_solar_power_response,
)


def user(text: str) -> dict[str, str]:
    return {"role": "user", "content": text}


def assistant(text: str) -> dict[str, str]:
    return {"role": "assistant", "content": text}


class TestDynamicProductsRAG:
    @pytest.mark.parametrize(("category", "expected"), [
        ("panels", [
            (202227, "HYB-PV-585", 480.0, 582),
            (202228, "HYB-PV-725", 600.0, 583),
            (2037, "ONGRID-PV-400", 480.0, 510),
        ]),
        ("inverters", [
            (202230, "DEYE-SUN-6K-SG04LP1", 14500.0, 552),
            (202231, "DEYE-SUN-10K-SG04LP3", 22000.0, 552),
        ]),
        ("batteries", [
            (202232, "DEYE-BOS-G-5.12", 16000.0, 545),
            (202233, "DEYE-RW-M6.1", 29000.0, 545),
        ]),
        ("drives", [
            (5, "SI23-D5-5R5", 2375.0, 576),
            (8, "SI23-T3-015", 4583.33, 576),
        ]),
    ])
    def test_missing_catalog_uses_official_reference_equipment(self, monkeypatch, category, expected):
        from app.services import catalog_service

        monkeypatch.setattr(catalog_service, "get_all_products", lambda **kwargs: [])
        products = get_dynamic_suggested_products(category, limit=3)
        assert [(item["id"], item["reference"], item["price"], item["image_id"])
                for item in products] == expected
        for item in products:
            assert item["category"] == category
            assert item["currency"] == "DH"
            assert item["price_tax"] == "HT"
            assert item["en_stock"] is True
            assert item["source"] == "reference_catalog"
            assert item["name"]
            assert item["image_url"].startswith("/v1/products/")
            assert f"image_id={item['image_id']}" in item["image_url"]

    def test_suggestions_use_only_verified_catalog_rows(self, monkeypatch):
        from app.services import catalog_service

        rows = [
            {"id": 12, "category": "panels", "reference": "REAL-590",
             "brand": "LONGI", "model": "590 Wc", "sale_price": 1250.75,
             "currency": "DH", "stock": 4, "active": 1, "demo": 0},
            {"id": 13, "category": "panels", "reference": "EMPTY",
             "sale_price": 999, "currency": "DH", "stock": 0, "active": 1},
            {"id": 14, "category": "panels", "reference": "OTHER-CURRENCY",
             "sale_price": 99, "currency": "EUR", "stock": 4, "active": 1},
        ]
        monkeypatch.setattr(catalog_service, "get_all_products", lambda **kwargs: rows)
        products = get_dynamic_suggested_products("panels")
        assert len(products) == 1
        assert products[0]["reference"] == "REAL-590"
        assert products[0]["price"] == 1250.75
        assert products[0]["currency"] == "DH"
        assert products[0]["source"] == "local_sqlite"

    def test_catalog_failure_uses_limited_reference_equipment(self, monkeypatch):
        from app.services import catalog_service

        def unavailable_catalog(**kwargs):
            raise RuntimeError("catalogue unavailable")

        monkeypatch.setattr(catalog_service, "get_all_products", unavailable_catalog)
        products = get_dynamic_suggested_products("drives", limit=1)
        assert len(products) == 1
        assert products[0]["reference"] == "SI23-D5-5R5"
        assert products[0]["source"] == "reference_catalog"

    def test_invalid_catalog_rows_use_reference_equipment(self, monkeypatch):
        from app.services import catalog_service

        valid_row = {"id": 12, "category": "panels", "reference": "REAL-590",
                     "sale_price": 1250.75, "currency": "DH", "stock": 4,
                     "active": 1, "demo": 0}
        invalid_fields = [
            {"category": "batteries"}, {"demo": 1}, {"demo": "1"},
            {"active": 0}, {"active": None}, {"stock": 0}, {"stock": -1},
            {"stock": float("nan")}, {"stock": float("inf")},
            {"sale_price": 0}, {"sale_price": -1}, {"sale_price": "invalid"},
            {"sale_price": float("nan")}, {"sale_price": float("inf")},
            {"currency": "EUR"}, {"currency": ""},
        ]
        rows = [dict(valid_row, **fields) for fields in invalid_fields]
        monkeypatch.setattr(catalog_service, "get_all_products", lambda **kwargs: rows)
        products = get_dynamic_suggested_products("panels", limit=2)
        assert [item["reference"] for item in products] == ["HYB-PV-585", "HYB-PV-725"]
        assert all(item["source"] == "reference_catalog" for item in products)

    @pytest.mark.parametrize("limit", [0, -1])
    def test_nonpositive_limit_skips_catalog_access(self, monkeypatch, limit):
        from app.services import catalog_service

        def unexpected_catalog_access(**kwargs):
            pytest.fail("a nonpositive limit must not load the catalogue")

        monkeypatch.setattr(catalog_service, "get_all_products", unexpected_catalog_access)
        assert get_dynamic_suggested_products("panels", limit=limit) == []

    def test_reference_equipment_returns_independent_items(self, monkeypatch):
        from app.services import catalog_service

        monkeypatch.setattr(catalog_service, "get_all_products", lambda **kwargs: [])
        first = get_dynamic_suggested_products("panels", limit=1)
        original_image_url = first[0]["image_url"]
        first[0]["price"] = 1.0
        first[0]["reference"] = "CHANGED"
        first[0]["image_url"] = "changed.png"
        second = get_dynamic_suggested_products("panels", limit=1)
        assert second[0]["price"] == 480.0
        assert second[0]["reference"] == "HYB-PV-585"
        assert second[0]["image_url"] == original_image_url

    def test_currency_sanitizer_keeps_the_original_amount(self):
        assert _sanitize_ai_response("Prix vérifié : 12,50 € HT.") == "Prix vérifié : 12,50 € HT."


class TestDarijaPhoneticMatching:
    @pytest.mark.parametrize("word", [
        "fakhtora diali 1500 dh",
        "kandfe3 bzzaf f do",
        "bghit n9es l'faktora",
        "khlass dial do",
    ])
    def test_darija_facture_intent(self, word):
        assert match_darija(word, "facture") is True

    @pytest.mark.parametrize("word", [
        "bghit taqa chmsiya",
        "chhal taman lwah",
        "plakat dial 585w",
        "chamsiya",
    ])
    def test_darija_panneaux_intent(self, word):
        assert match_darija(word, "panneaux") is True

    @pytest.mark.parametrize("word", [
        "pompa dial bir",
        "pompage solaire lbiir",
        "3ndi bir f fellaha",
    ])
    def test_darija_pompage_intent(self, word):
        assert match_darija(word, "pompage") is True

    @pytest.mark.parametrize("word", [
        "bghit batri li lil",
        "batriyat lithium",
        "kayt9te3 do f lil",
    ])
    def test_darija_batteries_intent(self, word):
        assert match_darija(word, "batteries") is True

    @pytest.mark.parametrize("word", [
        "chhal taman dial hadchi",
        "bchhal l'kit",
        "bghit devis 3afak",
        "3tini taman",
    ])
    def test_darija_prix_devis_intent(self, word):
        assert match_darija(word, "prix_devis") is True


class TestCommercialDirectAnswerAndCTA:
    def test_detect_bill_cta_returns_open_quote_wizard(self):
        cta = _detect_bill_and_build_cta("ma facture est de 1500 DH par mois")
        assert cta is not None
        assert cta["type"] == "open_quote_wizard"
        assert cta["bill_dh"] == 1500.0
        assert cta["estimated_kwc"] == 4.7
        assert "4.7 kWc" in cta["label"]

    def test_detect_kw_cta_returns_open_quote_wizard(self):
        cta = _detect_bill_and_build_cta("je veux installer 6 kwc")
        assert cta is not None
        assert cta["type"] == "open_quote_wizard"
        assert cta["estimated_kwc"] == 6.0
        assert "6 kWc" in cta["label"]

    def test_commercial_direct_answer_bill_in_dh(self):
        res = _get_commercial_direct_answer("ma facture est de 1800 dh")
        assert res is not None
        assert "1800 DH/mois" in res["content"]
        assert "5.6 kWc" in res["content"]
        assert res["action"]["type"] == "open_quote_wizard"
        assert res["products"]
        assert all(item["category"] == "panels" for item in res["products"])

    def test_commercial_direct_answer_darija_pompage(self):
        res = _get_commercial_direct_answer("bghit pompa dial lbir")
        assert res is not None
        assert "pompage solaire" in res["content"].lower()
        assert res["action"]["type"] == "open_pumping_calculator"
        assert res["products"]
        assert all(item["category"] == "drives" for item in res["products"])

    def test_commercial_direct_answer_darija_batteries(self):
        res = _get_commercial_direct_answer("bghit batriyat bach ila t9te3 do")
        assert res is not None
        assert "lithium lifepo4" in res["content"].lower()
        assert res["products"]
        assert all(item["category"] == "batteries" for item in res["products"])

    def test_quick_assistant_response_handles_darija_and_attaches_action(self):
        reply = quick_assistant_response([user("fakhtora diali 2000 dh")])
        assert reply is not None
        assert reply["role"] == "assistant"
        assert "2000 DH/mois" in reply["content"]
        assert reply["action"]["type"] == "open_quote_wizard"
        assert reply["action"]["bill_dh"] == 2000.0

    def test_quick_solar_power_response_attaches_action(self):
        reply = quick_solar_power_response([user("Combien de panneaux pour 10 kWc ?")])
        assert reply is not None
        assert "action" in reply
        assert reply["action"]["type"] == "open_quote_wizard"
        assert reply["action"]["estimated_kwc"] == 10.0

    def test_grid_neutrality_is_enforced(self):
        sanitized = _sanitize_ai_response("Votre facture ONEE sera réduite de 70% avec Lydec et Amendis.")
        assert "ONEE" not in sanitized
        assert "Lydec" not in sanitized
        assert "Amendis" not in sanitized
        assert "facture d'électricité" in sanitized


class TestAgriculturalPumpingSizingAndContext:
    """Rigorous tests ensuring zero hallucination for agricultural solar pumping."""

    def test_detect_pumping_power_50cv(self):
        pump = _detect_pumping_power("50cv")
        assert pump is not None
        assert pump["cv"] == 50
        assert pump["kw"] == 37.3
        assert pump["solar_kwc"] == 50.4
        assert pump["panels_725"] == 70
        assert pump["variateur_kw"] == 45.0

    def test_detect_pumping_power_various_formats(self):
        # 10 CV
        p10 = _detect_pumping_power("pompe de 10 cv")
        assert p10 is not None
        assert p10["cv"] == 10
        assert p10["kw"] == 7.5
        assert p10["solar_kwc"] == 10.1
        assert p10["variateur_kw"] == 7.5

        # 7.5 ch
        p75 = _detect_pumping_power("7.5 ch")
        assert p75 is not None
        assert p75["cv"] == 7.5
        assert p75["kw"] == 5.6
        assert p75["solar_kwc"] in (7.5, 7.6)
        assert p75["variateur_kw"] == 7.5

    def test_quick_assistant_response_handles_50cv_directly(self):
        reply = quick_assistant_response([user("50cv")])
        assert reply is not None
        assert reply["role"] == "assistant"
        content = reply["content"]
        assert "50 CV" in content
        assert "50.4 kWc" in content
        assert "70 panneaux" in content
        assert "45 kW" in content
        assert "fil du soleil" in content.lower()
        # Strictly zero battery / zero hybrid inverter confirmation
        assert "sans aucune batterie ni onduleur hybride" in content.lower()
        assert "10w/c" not in content.lower()

        # Action is pumping calculator
        assert reply["action"] is not None
        assert reply["action"]["type"] == "open_pumping_calculator"
        assert reply["action"]["pump_power_cv"] == 50
        assert reply["action"]["estimated_kwc"] == 50.4

    def test_contextual_retention_when_user_answers_raw_number(self):
        # User first asked about pumping, assistant asked for pump power
        messages = [
            user("Pompage solaire pour puits agricole"),
            assistant("Notre solution de pompage solaire au fil du soleil alimente directement votre pompe. Quelle est la puissance de votre pompe actuelle (en CV ou en kW) ?"),
            user("50"),
        ]
        reply = quick_assistant_response(messages)
        assert reply is not None
        assert "50 CV" in reply["content"]
        assert "50.4 kWc" in reply["content"]
        assert "45 kW" in reply["content"]
        assert reply["action"]["type"] == "open_pumping_calculator"
        assert reply["action"]["pump_power_cv"] == 50

    def test_guard_rejects_hallucinated_batteries_in_pumping(self):
        messages = [
            user("pompage agricole"),
            user("50cv"),
        ]
        hallucinated_content = "Pour votre pompe de 50 CV, nous vous conseillons un onduleur hybride avec batterie de 10 kWh."
        guarded = _guard_technical_content(messages, hallucinated_content)
        assert "batterie de 10 kWh" not in guarded
        assert "sans batterie ni onduleur hybride" in guarded.lower()
        assert "fil du soleil" in guarded.lower()


class TestRoleInversionAndUnitTypoSanitization:
    def test_role_inversion_eradication(self):
        reversed_msg = "Je suis à la recherche d'un système de pompage pour mon puits de 50m. Quelle est la puissance de votre pompe ?"
        cleaned = _sanitize_ai_response(reversed_msg, user_count=2)
        assert not cleaned.lower().startswith("je suis à la recherche")

    def test_unit_typo_correction(self):
        typo_msg = "Chaque panneau fournit 10W/c de puissance crête."
        cleaned = _sanitize_ai_response(typo_msg)
        assert "10W/c" not in cleaned
        assert "10 Wc" in cleaned or "10Wc" in cleaned

