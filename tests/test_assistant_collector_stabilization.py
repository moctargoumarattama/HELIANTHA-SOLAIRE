"""Customer-only quote facts: units, corrections and calculator constraints."""

from unittest.mock import Mock

import pytest

from app.services.assistant_devis import AssistantDevisManager, build_data, extract_slots, parse_float


def user(content):
    return {"role": "user", "content": content}


def assistant(content):
    return {"role": "assistant", "content": content}


@pytest.mark.parametrize("bill", ["1000 DH", "1 000 DH", "1\u202f000 MAD", "1000 dirhams"])
def test_monetary_consumption_never_supplies_official_energy(bill):
    messages = [user(
        "Je veux un devis autoconsommation. Nom: Ali. Ville: Casablanca. "
        f"Telephone: 0600000000. Monophase. Consommation de {bill}."
    )]
    slots = extract_slots(messages)
    assert slots.monthly_consumption_kwh is None
    assert slots.monthly_bill_dh == 1000
    factory = Mock()
    result = AssistantDevisManager().handle(messages, quote_factory=factory)
    assert result.handled
    assert "monthly_consumption_kwh" in result.missing
    assert "kWh" in result.content and "facture" in result.content
    factory.assert_not_called()


def test_bill_correction_clears_an_earlier_wrong_energy_value():
    slots = extract_slots([
        user("Devis autoconsommation : consommation 1000 kWh par mois"),
        user("Correction : ma consommation est en fait de 1000 DH"),
    ])
    assert slots.monthly_consumption_kwh is None
    assert slots.monthly_bill_dh == 1000


@pytest.mark.parametrize("separator", [" ", "\u00a0", "\u202f"])
def test_french_grouped_customer_energy_is_parsed_in_full(separator):
    slots = extract_slots([user(f"Devis autoconsommation : consommation 1{separator}000,5 kWh/mois")])
    assert slots.monthly_consumption_kwh == 1000.5
    assert parse_float(f"1{separator}000,5") == 1000.5


@pytest.mark.parametrize("negative", ["-30", "- 30", "\u221230", "-1 100"])
def test_negative_energy_and_motor_values_never_become_positive(negative):
    assert extract_slots([user(f"Devis autoconsommation : {negative} kWh/mois")]).monthly_consumption_kwh is None
    assert extract_slots([user(f"Devis pompage : pompe {negative} CV")]).existing_pump_cv is None


def test_nonfinite_and_extreme_numbers_are_not_calculator_inputs():
    for value in ("9" * 400, "inf", "nan", "1000000001", "0"):
        assert parse_float(value) is None
    assert extract_slots([user("Devis autoconsommation : " + "9" * 400 + " kWh/mois")]).monthly_consumption_kwh is None
    assert extract_slots([user("Devis autoconsommation : consommation 100000000 kWh/j")]).monthly_consumption_kwh is None


@pytest.mark.parametrize("energy", [
    "30 kWh par jour", "30 kWh/j", "30 kWh / jour",
    "Consommation journaliere de 30 kWh", "30,5 kWh par jour",
])
def test_daily_energy_is_normalized_using_thirty_days(energy):
    expected = 915 if "30,5" in energy else 900
    slots = extract_slots([user(f"Devis autoconsommation : {energy}")])
    assert slots.monthly_consumption_kwh == expected
    assert slots.monthly_consumption_basis == "daily_30_days"


def test_official_quote_receives_daily_energy_as_monthly_and_discloses_basis():
    factory = Mock(return_value={"id": 1, "ref": "UNIT-QUOTE", "total_ttc": "12 000 DH"})
    result = AssistantDevisManager().handle([user(
        "Je veux un devis autoconsommation. Nom: Ali. Ville: Casablanca. "
        "Telephone: 0600000000. Monophase. Consommation 30 kWh/j."
    )], quote_factory=factory)
    assert result.quote["id"] == 1
    assert factory.call_args.args[1]["monthly_consumption_kwh"] == 900
    assert "30 jours" in result.content


@pytest.mark.parametrize("energy", ["30 kWh/an", "30 kWh par semaine", "30 kWh par heure"])
def test_other_energy_periods_are_not_silently_treated_as_monthly(energy):
    assert extract_slots([user(f"Devis autoconsommation : {energy}")]).monthly_consumption_kwh is None


def test_battery_capacity_is_not_consumption():
    assert extract_slots([user("Je veux un devis hybride avec une batterie de 5 kWh")]).monthly_consumption_kwh is None


def test_battery_capacity_does_not_replace_consumption_in_the_same_message():
    slots = extract_slots([user("Devis hybride : ma consommation est 1000 kWh par mois, avec une batterie de 5 kWh")])
    assert slots.monthly_consumption_kwh == 1000


def test_monetary_answer_to_consumption_question_requires_actual_energy():
    messages = [
        user("Devis autoconsommation. Nom: Ali. Ville: Casablanca. Telephone: 0600000000. Monophase."),
        assistant("Quelle est votre consommation mensuelle en kWh ?"),
        user("1000 DH"),
    ]
    assert extract_slots(messages).monthly_bill_dh == 1000
    factory = Mock()
    result = AssistantDevisManager().handle(messages, quote_factory=factory)
    assert "monthly_consumption_kwh" in result.missing
    assert "kWh" in result.content
    factory.assert_not_called()


def test_contextual_city_and_energy_come_from_customer_answers():
    slots = extract_slots([
        user("Je veux un devis autoconsommation"),
        assistant("Quelle est votre ville ?"), user("Casablanca"),
        assistant("Quelle est votre consommation mensuelle en kWh ?"), user("1 000"),
    ])
    assert slots.city == "Casablanca"
    assert slots.monthly_consumption_kwh == 1000


def test_unknown_city_requires_a_specific_city_question():
    assert extract_slots([assistant("Quelle est votre ville ?"), user("Tata")]).city == "Tata"
    assert extract_slots([user("Tata")]).city == ""


def test_plain_number_requires_a_specific_consumption_question():
    assert extract_slots([user("1000")]).monthly_consumption_kwh is None
    slots = extract_slots([
        assistant("Il me manque votre nom, telephone et consommation mensuelle en kWh."),
        user("1000"),
    ])
    assert slots.monthly_consumption_kwh is None


def test_assistant_energy_city_and_phase_never_supply_customer_facts():
    slots = extract_slots([
        user("Je veux un devis hybride"),
        assistant("Vous etes a Casablanca, votre consommation est 1000 kWh/mois et votre branchement est triphase."),
        user("merci"),
    ])
    assert slots.city == ""
    assert slots.monthly_consumption_kwh is None
    assert slots.phase == ""


def test_new_no_pump_request_clears_the_previous_motor_power():
    messages = [
        user("Devis pompage : pompe existante 2 CV"),
        assistant("Donnez-moi votre ville."),
        user("Correction : sans pompe, debit 12 m3/h, HMT 80 m. Nom: Ali. Ville: Rabat. Telephone: 0600000000."),
    ]
    slots = extract_slots(messages)
    assert slots.existing_pump_cv is None
    assert slots.pump_existing is False
    assert build_data(slots) == {"pump_existing": False, "flow_m3_h": 12, "hmt_m": 80, "city": "Rabat"}
    factory = Mock(return_value={"id": 2, "ref": "PUMP-QUOTE"})
    result = AssistantDevisManager().handle(messages, quote_factory=factory)
    assert result.quote["id"] == 2
    assert "existing_pump_cv" not in factory.call_args.args[1]


def test_later_existing_pump_correction_can_restore_customer_motor_power():
    slots = extract_slots([
        user("Devis pompage : pompe 2 CV"),
        user("Sans pompe, debit 12 m3/h et HMT 80 m"),
        user("Finalement j'ai une pompe 3 CV"),
    ])
    assert slots.pump_existing is True
    assert slots.existing_pump_cv == 3


@pytest.mark.parametrize("phase", ["triphase", "380 V", "400 V"])
def test_unsupported_hybrid_three_phase_is_preserved_and_not_quoted(phase):
    messages = [user(
        "Je veux un devis hybride. Nom: Ali. Ville: Casablanca. Telephone: 0600000000. "
        f"Consommation 1000 kWh/mois. Branchement {phase}."
    )]
    slots = extract_slots(messages)
    assert slots.phase == "triphase"
    assert build_data(slots)["phase"] == "triphase"
    assert build_data(slots)["voltage_v"] == 380
    factory = Mock()
    result = AssistantDevisManager().handle(messages, quote_factory=factory)
    assert result.handled
    assert result.data["phase"] == "triphase"
    assert "uniquement" in result.content and "monophase" in result.content
    factory.assert_not_called()


def test_hybrid_quote_requires_customer_phase_confirmation():
    factory = Mock()
    result = AssistantDevisManager().handle([user(
        "Je veux un devis hybride. Nom: Ali. Ville: Casablanca. Telephone: 0600000000. Conso 1000 kWh/mois."
    )], quote_factory=factory)
    assert "phase" in result.missing
    factory.assert_not_called()


@pytest.mark.parametrize("amount", ["380 DH", "380 kWh/mois"])
def test_bill_or_energy_never_implies_a_mains_phase(amount):
    assert extract_slots([user(f"Devis autoconsommation : consommation {amount}")]).phase == ""


@pytest.mark.parametrize("amount", ["380 DH", "380 kWh/mois"])
def test_bill_or_energy_does_not_override_an_explicit_monophase_connection(amount):
    slots = extract_slots([
        user("Devis autoconsommation : mon branchement est monophase"),
        user(f"Ma consommation est {amount}"),
    ])
    assert slots.phase == "monophase"


@pytest.mark.parametrize("question", [
    "590 W * 5", "590,5 Wc x 5", "Combien de panneaux pour 50 Wc ?",
    "nombre de panneaux solaires pour 10 kWc", "facture de 1200 DH par mois",
    "1000 kWh par mois",
])
def test_informative_numeric_request_can_interrupt_a_quote(question):
    factory = Mock()
    result = AssistantDevisManager().handle([
        user("Je veux un devis autoconsommation"),
        assistant("Pour preparer votre devis, il me manque votre nom et votre telephone."),
        user(question),
    ], quote_factory=factory)
    assert result.handled is False
    factory.assert_not_called()


def test_specific_consumption_answer_can_complete_a_progressive_quote():
    factory = Mock(return_value={"id": 3, "ref": "PROGRESSIVE"})
    result = AssistantDevisManager().handle([
        user("Je veux un devis autoconsommation. Nom: Ali. Ville: Rabat. Telephone: 0600000000. Monophase."),
        assistant("Pour preparer votre devis, quelle est votre consommation mensuelle en kWh ?"),
        user("1000 kWh par mois"),
    ], quote_factory=factory)
    assert result.quote["id"] == 3
    assert factory.call_args.args[1]["monthly_consumption_kwh"] == 1000


def test_price_of_a_product_does_not_start_an_official_quote():
    factory = Mock()
    result = AssistantDevisManager().handle([user("Quel est le prix des panneaux solaires ?")], quote_factory=factory)
    assert result.handled is False
    factory.assert_not_called()
