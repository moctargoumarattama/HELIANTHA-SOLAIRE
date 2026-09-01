from __future__ import annotations

from datetime import datetime
from random import randint

from flask import url_for

from ...calculators import CalculationEngine, ValidationError
from ...db import (
    add_advisor_message,
    add_advisor_unknown,
    get_advisor_runtime_assets,
    get_advisor_state,
    get_quote_by_number,
    load_calculation_context,
    save_advisor_state,
    save_quote,
)
from .entities import extract_entities
from .intents import detect_intents
from .knowledge import search_knowledge
from .learning import should_queue_unknown
from .project_flows import has_minimum, missing_fields, next_question, prune_data_for_project, question_by_id
from .rules import PROJECT_LABELS_PUBLIC, contains_any, detect_project, is_unknown_answer, normalize
from .state import merge_state, public_state


class AdvisorService:
    def __init__(self, engine: CalculationEngine | None = None):
        self.engine = engine or CalculationEngine()

    def handle_message(self, session_key: str, message: str, incoming_state: dict | None = None) -> dict:
        saved = get_advisor_state(session_key)
        state = merge_state(saved, incoming_state)
        original = str(message or "").strip()
        normalized = normalize(original)
        assets = get_advisor_runtime_assets()
        add_advisor_message(session_key, "user", original, normalized)

        if not original:
            return self._reply(session_key, state, "Ecrivez votre besoin en quelques mots.", self._home_actions())

        intents = detect_intents(original, examples=assets["intent_examples"])
        top_intent = intents[0]["intent"]
        top_confidence = int(intents[0].get("confidence") or 0)
        state["current_intent"] = top_intent

        if top_intent == "restart":
            state = merge_state(None, {"session_id": state.get("session_id")})
            return self._reply(session_key, state, "D'accord. On repart sur un nouveau projet.", self._home_actions())

        extraction = extract_entities(original, state, synonyms=assets["synonyms"])
        data_updates = dict(extraction.get("data") or {})
        if extraction.get("current_topic"):
            state["previous_topic"] = state.get("current_topic", "")
            state["current_topic"] = extraction["current_topic"]
        self._merge_data(state, data_updates, extraction.get("answered_fields") or [])

        project_hit = detect_project(
            original,
            synonyms=assets["synonyms"],
            learned_examples=assets["intent_examples"],
        )

        if state.get("current_topic") == "plaque_signaletique":
            return self._continue_after_side_answer(
                session_key,
                state,
                "Ce n'est pas bloquant. Si vous avez une photo de la pompe, sa puissance ou sa tension, HeliAntha peut deja vous orienter.",
            )

        if (
            not state.get("quote_reference")
            and top_intent in {"ask_explanation", "ask_equipment", "ask_price"}
            and self._looks_like_question(original, top_intent)
        ):
            faq = search_knowledge(original, state.get("project_type") or project_hit.get("project"), assets["knowledge"])
            if faq:
                return self._continue_after_side_answer(session_key, state, faq["answer"])
            if top_intent == "ask_price":
                return self._continue_after_side_answer(
                    session_key,
                    state,
                    "Le prix arrive apres l'etude avec les vraies donnees HeliAntha.",
                )

        resolved_from_context = self._resolve_project_from_context(state, original, project_hit)
        if resolved_from_context:
            self._assign_project(state, resolved_from_context)

        if state.get("quote_reference"):
            variant_reply = self._start_variant_if_needed(state, original, project_hit)
            if variant_reply:
                return self._reply(session_key, state, variant_reply["text"], variant_reply["actions"])

        explicit_project = project_hit.get("project")
        if explicit_project:
            if project_hit.get("ambiguous") and (
                not state.get("project_type") or state.get("project_type") not in {"ongrid", "offgrid", "hybrid"}
            ):
                state["project_confidence"] = project_hit["confidence"]
                state["project_candidates"] = project_hit.get("scores", {})
                return self._ask_network_question(session_key, state)
            if explicit_project != state.get("project_type") and self._should_switch_project(state, explicit_project, project_hit, top_intent):
                self._assign_project(state, explicit_project)
            elif not state.get("project_type"):
                self._assign_project(state, explicit_project)

        if top_intent in {"greeting", "thanks"} and not state.get("project_type") and not data_updates and not explicit_project:
            return self._reply(session_key, state, "Bonjour. Dites-moi simplement votre projet.", self._home_actions())

        if top_intent in {"request_human", "request_visit"}:
            text = "Bien sur. HeliAntha peut vous rappeler ou organiser une visite."
            return self._reply(session_key, state, text, self._human_actions())

        if top_intent == "request_pdf" and state.get("quote_reference"):
            return self._reply(session_key, state, "Votre pre-devis est disponible.", self._quote_actions(state["quote_reference"]))

        if state.get("quote_reference") and top_intent in {"ask_explanation", "ask_equipment", "ask_price"}:
            quote_answer = self._quote_followup_answer(state, original)
            if quote_answer:
                return self._continue_after_side_answer(session_key, state, quote_answer)

        if is_unknown_answer(normalized) and state.get("last_question_id"):
            return self._reply_unknown_answer(session_key, state)

        if not state.get("project_type"):
            reason = should_queue_unknown(
                original,
                state,
                intents,
                ambiguous_project=bool(project_hit.get("ambiguous")),
                low_confidence=top_confidence < 60,
            )
            if reason:
                add_advisor_unknown(session_key, original, normalized, state, reason)
            return self._reply(
                session_key,
                state,
                "Je peux vous orienter. Choisissez le besoin le plus proche.",
                self._project_choice_actions(),
            )

        if has_minimum(state["project_type"], state["collected_data"]):
            state["missing_data"] = []
            state["pending_question_id"] = None
            state["last_question_id"] = "ready"
            label = PROJECT_LABELS_PUBLIC.get(state["project_type"], "votre projet")
            text = f"J'ai assez d'informations pour preparer {label}."
            return self._reply(session_key, state, text, [
                {"label": "Calculer mon projet", "action": "calculate"},
                {"label": "Ouvrir le questionnaire", "action": "start_estimate"},
                {"label": "Parler a HeliAntha", "action": "call"},
            ])

        question = next_question(
            state.get("project_type"),
            state.get("collected_data") or {},
            answered_fields=state.get("answered_fields") or [],
        )
        if question:
            return self._ask_question(session_key, state, question, prefix=self._acknowledgement(state, data_updates))

        reason = should_queue_unknown(original, state, intents, low_confidence=top_confidence < 60, fallback=True)
        if reason:
            add_advisor_unknown(session_key, original, normalized, state, reason)
        return self._reply(session_key, state, self._fallback_text(state), self._context_actions(state))

    def calculate(self, session_key: str, incoming_state: dict | None = None, contact: dict | None = None) -> dict:
        state = merge_state(get_advisor_state(session_key), incoming_state)
        project = state.get("project_type")
        data = dict(state.get("collected_data") or {})
        if not has_minimum(project, data):
            question = next_question(project, data, answered_fields=state.get("answered_fields") or [])
            if question:
                return self._ask_question(session_key, state, question)
            return self._reply(session_key, state, "Il me manque encore quelques informations.", self._context_actions(state))

        try:
            result = self.engine.calculate(project, data, context=load_calculation_context())
        except ValidationError as exc:
            return self._reply(session_key, state, str(exc), self._context_actions(state), ok=False)

        result["quote_number"] = f"HSQ-{datetime.now():%Y%m%d}-{randint(1000, 9999)}"
        result["created_at"] = datetime.now().strftime("%d/%m/%Y a %H:%M")
        quote_id = save_quote(result["quote_number"], project, data, contact or {}, result)
        state["quote_reference"] = result["quote_number"]
        state["quote_id"] = quote_id
        offers = result.get("offers") or []
        state["active_offer"] = next((offer.get("level") for offer in offers if offer.get("recommended")), "") or ""
        final = result.get("final_results") or {}
        price = result.get("financial_breakdown", {}).get("total_ttc")
        price_label = f"{price:,.0f} DH".replace(",", " ") if price is not None else "Prix prepare"
        summary = self._result_summary(project, final, price_label)
        return self._reply(
            session_key,
            state,
            summary,
            [
                {"label": "Voir mon devis", "href": url_for("main.public_quote", quote_number=result["quote_number"])},
                {"label": "Telecharger le PDF", "href": url_for("main.public_quote_print", quote_number=result["quote_number"])},
                {"label": "Demander une visite", "href": url_for("main.public_quote", quote_number=result["quote_number"]) + "#visit"},
            ],
            quote={"quote_reference": result["quote_number"], "quote_id": quote_id},
        )

    def _merge_data(self, state: dict, updates: dict, answered_fields: list[str]) -> None:
        if not updates:
            return
        state["collected_data"].update(updates)
        state["answered_fields"] = list(dict.fromkeys([
            *(state.get("answered_fields") or []),
            *answered_fields,
            *(updates.keys()),
        ]))
        state["clarification_count"] = 0

    def _assign_project(self, state: dict, project: str) -> None:
        current = state.get("project_type")
        if current == project:
            return
        state["project_type"] = project
        state["project_confidence"] = max(int(state.get("project_confidence") or 0), 70)
        state["collected_data"] = prune_data_for_project(project, state.get("collected_data") or {})
        state["answered_fields"] = [field for field in state.get("answered_fields") or [] if field in state["collected_data"] or field == "city"]
        state["pending_question_id"] = None
        state["suspended_question_id"] = None
        state.pop("project_candidates", None)

    def _resolve_project_from_context(self, state: dict, message: str, project_hit: dict) -> str | None:
        text = normalize(message)
        project = state.get("project_type")
        data = state.get("collected_data") or {}

        if state.get("project_candidates") and data.get("network_existing") is not None:
            if data.get("network_existing") is False:
                return "offgrid"
            if data.get("outages") or contains_any(text, ["batterie", "batteries", "coupure", "coupures", "secours"]):
                return "hybrid"
            return "ongrid"

        if project in {"ongrid", "offgrid"} and contains_any(text, ["batterie", "batteries", "coupure", "coupures", "secours"]):
            if not contains_any(text, ["pas de batterie", "je veux pas de batterie"]):
                return "hybrid"

        if not project and project_hit.get("project") and not project_hit.get("ambiguous"):
            return project_hit["project"]
        return None

    def _should_switch_project(self, state: dict, project: str, project_hit: dict, top_intent: str) -> bool:
        current = state.get("project_type")
        if not current or current == project:
            return False
        return top_intent in {"change_project", "start_project"} or int(project_hit.get("confidence") or 0) >= 24

    def _ask_network_question(self, session_key: str, state: dict) -> dict:
        question = {
            "id": "network_existing",
            "text": "Votre maison est-elle deja raccordee au reseau electrique ?",
        }
        return self._ask_question(session_key, state, question, actions=[
            {"label": "Oui", "action": "say:oui"},
            {"label": "Non", "action": "say:non"},
            {"label": "Il y a beaucoup de coupures", "action": "say:oui mais bcp de coupure"},
        ])

    def _ask_question(self, session_key: str, state: dict, question: dict, prefix: str = "", actions: list[dict] | None = None) -> dict:
        question_id = question["id"]
        counts = dict(state.get("question_counts") or {})
        counts[question_id] = counts.get(question_id, 0) + 1
        state["question_counts"] = counts
        state["last_question_id"] = question_id
        state["pending_question_id"] = question_id
        state["wizard_step"] = question.get("step")
        state["missing_data"] = [question_id]
        text = self._rephrase_question(question) if counts[question_id] >= 2 else question["text"]
        if prefix:
            text = f"{prefix}\n\n{text}"
        return self._reply(session_key, state, text, actions or self._question_actions(question_id, state))

    def _continue_after_side_answer(self, session_key: str, state: dict, answer: str) -> dict:
        pending_question_id = state.get("pending_question_id") or state.get("last_question_id")
        question = question_by_id(state.get("project_type"), pending_question_id) if pending_question_id else None
        if question and not self._question_is_resolved(question["id"], state.get("collected_data") or {}):
            state["suspended_question_id"] = pending_question_id
            text = f"{answer}\n\nPour continuer : {question['text']}"
            return self._reply(session_key, state, text, self._question_actions(question["id"], state))
        next_item = next_question(
            state.get("project_type"),
            state.get("collected_data") or {},
            answered_fields=state.get("answered_fields") or [],
        )
        if next_item:
            state["suspended_question_id"] = None
            return self._ask_question(session_key, state, next_item, prefix=f"{answer}\n\nPour continuer :")
        return self._reply(session_key, state, answer, self._context_actions(state))

    def _question_is_resolved(self, question_id: str, data: dict) -> bool:
        if question_id == "monthly_kwh":
            return any(data.get(key) not in (None, "", []) for key in ("monthly_kwh", "bill", "daily_kwh"))
        if question_id == "daily_kwh":
            return any(data.get(key) not in (None, "", []) for key in ("daily_kwh", "monthly_kwh", "bill"))
        return data.get(question_id) not in (None, "", [])

    def _reply_unknown_answer(self, session_key: str, state: dict) -> dict:
        question_id = state.get("last_question_id")
        state["clarification_count"] = int(state.get("clarification_count") or 0) + 1
        if question_id == "monthly_kwh":
            return self._reply(
                session_key,
                state,
                "Pas de probleme. Nous pouvons partir de votre facture ou de vos appareils principaux.",
                [
                    {"label": "Utiliser ma facture", "action": "say:ma facture"},
                    {"label": "Estimer avec mes appareils", "action": "start_estimate"},
                    {"label": "Parler a HeliAntha", "action": "call"},
                ],
            )
        if question_id == "city":
            return self._reply(
                session_key,
                state,
                "Pas de probleme. Donnez-moi simplement la ville ou la region du projet.",
                self._question_actions("city", state),
            )
        if question_id == "pump_existing":
            next_item = question_by_id(state.get("project_type"), "existing_pump_cv") or {"id": "existing_pump_cv", "text": "Quelle est la puissance de votre pompe en CV ?"}
            return self._ask_question(
                session_key,
                state,
                next_item,
                prefix="Ce n'est pas bloquant.",
                actions=self._question_actions("existing_pump_cv", state),
            )
        if question_id == "existing_pump_cv":
            next_item = question_by_id(state.get("project_type"), "existing_pump_cv") or {"id": "existing_pump_cv", "text": "Quelle est la puissance de votre pompe en CV ?"}
            return self._ask_question(
                session_key,
                state,
                next_item,
                prefix="Merci. Choisissez simplement la puissance.",
                actions=self._question_actions("existing_pump_cv", state),
            )
        question = question_by_id(state.get("project_type"), question_id)
        text = "Pas de probleme. Donnez-moi une estimation simple."
        if question:
            text = f"{text}\n\n{self._rephrase_question(question)}"
        return self._reply(session_key, state, text, self._question_actions(question_id, state))

    def _rephrase_question(self, question: dict) -> str:
        mapping = {
            "monthly_kwh": "Vous pouvez me donner soit la consommation mensuelle, soit la facture moyenne.",
            "daily_kwh": "Donnez-moi simplement la consommation approximative par jour.",
            "city": "Indiquez-moi simplement la ville du projet.",
            "priority_loads": "Quels appareils doivent rester alimentes ?",
            "autonomy": "Souhaitez-vous une autonomie de quelques heures ou de plusieurs jours ?",
        }
        return mapping.get(question["id"], question["text"])

    def _fallback_text(self, state: dict) -> str:
        question_id = state.get("last_question_id")
        if question_id == "pump_existing":
            return "Je veux etre sur de bien comprendre. Avez-vous deja une pompe sur place ?"
        if question_id == "existing_pump_cv":
            return "Je veux juste la puissance de la pompe en CV."
        if question_id == "flow_m3_h":
            return "Je veux juste le debit souhaite en m3/h."
        if question_id == "hmt_m":
            return "Je veux juste la HMT de l'installation en metres."
        if question_id == "network_existing":
            return "Je veux etre sur de bien vous orienter. Le site a-t-il deja le reseau electrique ?"
        if state.get("project_type") == "pumping":
            return "Je veux etre sur de bien comprendre. Parlez-vous du debit, de la HMT ou de la pompe ?"
        if state.get("project_type") in {"ongrid", "hybrid", "offgrid"}:
            return "Je veux etre sur de bien comprendre. Parlez-vous de la consommation, des batteries ou du lieu du projet ?"
        return "Je veux etre sur de bien comprendre. Parlez-vous du projet, du prix ou du materiel ?"

    def _question_actions(self, question_id: str | None, state: dict) -> list[dict]:
        if question_id in {"pump_existing", "network_existing", "grid_connection"}:
            return [
                {"label": "Oui", "action": "say:oui"},
                {"label": "Non", "action": "say:non"},
                {"label": "Je ne sais pas", "action": "say:je ne sais pas"},
            ]
        if question_id == "existing_pump_cv":
            return [
                {"label": "2 CV", "action": "say:2 cv"},
                {"label": "3 CV", "action": "say:3 cv"},
                {"label": "5,5 CV", "action": "say:5,5 cv"},
                {"label": "7,5 CV", "action": "say:7,5 cv"},
                {"label": "10 CV", "action": "say:10 cv"},
                {"label": "15 CV", "action": "say:15 cv"},
                {"label": "20 CV", "action": "say:20 cv"},
                {"label": "30 CV", "action": "say:30 cv"},
                {"label": "40 CV", "action": "say:40 cv"},
                {"label": "50 CV", "action": "say:50 cv"},
            ]
        if question_id in {"monthly_kwh", "daily_kwh"}:
            return [
                {"label": "Donner ma facture", "action": "say:900 dh"},
                {"label": "Ouvrir le questionnaire", "action": "start_estimate"},
                {"label": "Parler a HeliAntha", "action": "call"},
            ]
        actions = [{"label": "Ouvrir le questionnaire", "action": "start_estimate"}]
        if state.get("project_type"):
            actions.insert(0, {"label": "Calculer mon projet", "action": "calculate"})
        actions.append({"label": "Parler a HeliAntha", "action": "call"})
        return actions[:3]

    def _looks_like_question(self, message: str, top_intent: str) -> bool:
        text = normalize(message)
        if "?" in message:
            return True
        if top_intent in {"ask_explanation", "ask_price"}:
            return True
        return contains_any(text, ["c est quoi", "pourquoi", "combien", "comment", "peut", "marche", "fonctionne"])

    def _home_actions(self) -> list[dict]:
        return [
            {"label": "Pompage solaire", "action": "project:pumping"},
            {"label": "Site sans reseau", "action": "project:offgrid"},
            {"label": "Reduire ma consommation", "action": "project:ongrid"},
            {"label": "Solaire avec batteries", "action": "project:hybrid"},
        ]

    def _project_choice_actions(self) -> list[dict]:
        return self._home_actions() + [
            {"label": "Chauffage solaire", "action": "project:thermal"},
            {"label": "Recharge electrique", "action": "project:ev"},
        ]

    def _human_actions(self) -> list[dict]:
        return [
            {"label": "Etre rappele", "action": "call"},
            {"label": "WhatsApp", "action": "whatsapp"},
            {"label": "Demander une visite", "action": "say:je veux une visite"},
        ]

    def _quote_actions(self, quote_reference: str) -> list[dict]:
        return [
            {"label": "Voir mon devis", "href": url_for("main.public_quote", quote_number=quote_reference)},
            {"label": "Telecharger le PDF", "href": url_for("main.public_quote_print", quote_number=quote_reference)},
            {"label": "Demander une visite", "href": url_for("main.public_quote", quote_number=quote_reference) + "#visit"},
        ]

    def _context_actions(self, state: dict) -> list[dict]:
        actions = [{"label": "Ouvrir le questionnaire", "action": "start_estimate"}]
        if state.get("project_type"):
            actions.insert(0, {"label": "Calculer mon projet", "action": "calculate"})
        actions.append({"label": "Parler a HeliAntha", "action": "call"})
        return actions[:3]

    def _acknowledgement(self, state: dict, updates: dict) -> str:
        if not updates:
            return ""
        if "city" in updates:
            return f"J'ai note {updates['city']}."
        if "existing_pump_cv" in updates:
            return f"J'ai note la pompe de {updates['existing_pump_cv']:.1f} CV."
        if "pump_power" in updates:
            return f"J'ai note la pompe de {updates['pump_power']:.0f} kW."
        if "bill" in updates:
            return f"J'ai note environ {updates['bill']:.0f} DH."
        if "monthly_kwh" in updates:
            return f"J'ai note {updates['monthly_kwh']:.0f} kWh par mois."
        if "flow_m3_h" in updates:
            return f"J'ai note {updates['flow_m3_h']:.2f} m3/h."
        if "hmt_m" in updates:
            return f"J'ai note {updates['hmt_m']:.0f} m de HMT."
        if "priority_loads" in updates:
            return "J'ai note les appareils prioritaires."
        return ""

    def _start_variant_if_needed(self, state: dict, message: str, project_hit: dict) -> dict | None:
        current = state.get("project_type")
        text = normalize(message)
        if current == "ongrid" and contains_any(text, ["batterie", "batteries", "stockage", "coupure"]):
            self._assign_project(state, "hybrid")
            state["quote_id"] = None
            state["quote_reference"] = None
            question = next_question("hybrid", state.get("collected_data") or {}, answered_fields=state.get("answered_fields") or [])
            return {
                "text": "Tres bien. Je prepare une variante solaire avec batteries.",
                "actions": self._question_actions((question or {}).get("id"), state),
            } if question else None
        if project_hit.get("project") and project_hit["project"] != current and self._should_switch_project(state, project_hit["project"], project_hit, "change_project"):
            self._assign_project(state, project_hit["project"])
            state["quote_id"] = None
            state["quote_reference"] = None
            label = PROJECT_LABELS_PUBLIC.get(project_hit["project"], "votre projet")
            question = next_question(project_hit["project"], state.get("collected_data") or {}, answered_fields=state.get("answered_fields") or [])
            actions = self._question_actions((question or {}).get("id"), state) if question else self._context_actions(state)
            return {"text": f"D'accord. Je bascule sur {label}.", "actions": actions}
        return None

    def _quote_followup_answer(self, state: dict, message: str) -> str | None:
        quote_reference = state.get("quote_reference")
        if not quote_reference:
            return None
        quote = get_quote_by_number(quote_reference)
        if not quote:
            return None
        text = normalize(message)
        offer = self._selected_offer(quote)
        final = dict(quote.get("result", {}).get("final_results") or {})
        if offer.get("final_results"):
            final.update(offer["final_results"])
        components = {item.get("category"): item for item in (offer.get("selected_equipment") or [])}

        if contains_any(text, ["pourquoi", "panneau", "panneaux"]):
            panels = int(final.get("panels") or 0)
            pv_power = float(final.get("pv_power_kwp") or 0)
            if panels:
                return f"HeliAntha a retenu {panels} panneaux pour atteindre environ {pv_power:.2f} kWp."
        if contains_any(text, ["onduleur"]):
            inverter = components.get("inverters") or {}
            power = inverter.get("power_kw") or final.get("inverter_power_kw")
            title = " ".join(part for part in [inverter.get("brand"), inverter.get("model")] if part).strip()
            if power:
                return f"L'onduleur retenu est {title or 'le modele compatible'} en {float(power):.1f} kW."
        if contains_any(text, ["batterie", "batteries"]):
            battery = components.get("batteries") or {}
            capacity = battery.get("capacity_kwh") or final.get("battery_capacity_kwh")
            if capacity:
                return f"Le stockage retenu est d'environ {float(capacity):.2f} kWh."
        if contains_any(text, ["prix", "cout", "budget", "combien"]):
            price = offer.get("ttc") or quote.get("financial_breakdown", {}).get("total_ttc")
            if price is not None:
                return f"L'estimation actuelle est de {float(price):,.0f} DH TTC.".replace(",", " ")
        if contains_any(text, ["materiel", "equipement"]):
            labels = []
            for item in (offer.get("selected_equipment") or [])[:3]:
                title = " ".join(part for part in [item.get("brand"), item.get("model")] if part).strip() or item.get("description") or item.get("reference") or "Materiel"
                labels.append(title)
            if labels:
                return "Le materiel principal retenu est : " + ", ".join(labels) + "."
        return None

    def _selected_offer(self, quote: dict) -> dict:
        offers = quote.get("result", {}).get("offers") or []
        selected_level = (quote.get("selected_offer_level") or state_value(quote, "selected_offer_level") or "").strip().lower()
        for offer in offers:
            if str(offer.get("level") or "").strip().lower() == selected_level and selected_level:
                return offer
        for offer in offers:
            if offer.get("recommended"):
                return offer
        return offers[0] if offers else {}

    def _reply(self, session_key: str, state: dict, text: str, actions: list[dict] | None = None, ok: bool = True, quote: dict | None = None) -> dict:
        state["missing_data"] = missing_fields(
            state.get("project_type"),
            state.get("collected_data") or {},
            answered_fields=state.get("answered_fields") or [],
        )
        save_advisor_state(session_key, state)
        add_advisor_message(session_key, "assistant", text, normalize(text))
        return {
            "ok": ok,
            "reply": text,
            "actions": actions or [],
            "state": public_state(state),
            "prefill": {
                "project": state.get("project_type") or "",
                "answers": state.get("collected_data") or {},
            },
            "quote": quote or {},
        }

    def _result_summary(self, project: str, final: dict, price_label: str) -> str:
        label = PROJECT_LABELS_PUBLIC.get(project, "Votre etude")
        parts = [f"Votre etude est prete.\n\nSolution : {label}"]
        if final.get("pv_power_kwp"):
            parts.append(f"Puissance : {float(final['pv_power_kwp']):.2f} kWp")
        if final.get("panels"):
            parts.append(f"Panneaux : {int(final['panels'])}")
        if final.get("pump_power_cv"):
            parts.append(f"Pompe : {float(final['pump_power_cv']):.1f} CV")
        elif final.get("pump_power_kw"):
            parts.append(f"Pompe : {float(final['pump_power_kw']):.1f} kW")
        if final.get("charger_power_kw"):
            parts.append(f"Borne : {float(final['charger_power_kw']):.1f} kW")
        if final.get("battery_capacity_kwh"):
            parts.append(f"Stockage : {float(final['battery_capacity_kwh']):.2f} kWh")
        parts.append(f"Estimation : {price_label} TTC")
        return "\n".join(parts)


def state_value(row: dict, key: str):
    return row.get(key)
