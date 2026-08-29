from __future__ import annotations


PROJECT_FLOWS = {
    "pumping": {
        "required": [],
        "questions": [
            {"id": "pump_existing", "text": "Avez-vous deja une pompe ?", "step": "pump", "actions": ["Oui", "Non"]},
            {"id": "existing_pump_cv", "text": "Quelle est la puissance de votre pompe en CV ?", "step": "pump", "show_if": {"pump_existing": True}},
            {"id": "water_need", "text": "Quel volume d'eau souhaitez-vous par jour ?", "step": "water", "show_if": {"pump_existing": False}},
            {"id": "depth", "text": "Quelle est la profondeur du forage ?", "step": "site", "show_if": {"pump_existing": False}},
            {"id": "city", "text": "Dans quelle ville se trouve le projet ?", "step": "site", "show_if": {"pump_existing": False}},
        ],
        "fields": {"water_need", "pump_existing", "existing_pump_cv", "depth", "city", "distance", "elevation"},
    },
    "offgrid": {
        "required": ["daily_kwh"],
        "questions": [
            {"id": "daily_kwh", "text": "Quelle consommation souhaitez-vous alimenter par jour ?", "step": "energy"},
            {"id": "peak_kw", "text": "Quelle puissance peut fonctionner en meme temps ?", "step": "energy"},
            {"id": "autonomy", "text": "Quelle autonomie souhaitez-vous ?", "step": "storage"},
            {"id": "city", "text": "Dans quelle ville est le site ?", "step": "site"},
        ],
        "fields": {"daily_kwh", "peak_kw", "autonomy", "city", "objective", "priority_loads"},
    },
    "ongrid": {
        "required_any": [["monthly_kwh", "bill"]],
        "questions": [
            {"id": "monthly_kwh", "text": "Connaissez-vous votre consommation mensuelle ou votre facture moyenne ?", "step": "bill"},
            {"id": "roof_area", "text": "Quelle surface est disponible pour les panneaux ?", "step": "site"},
            {"id": "city", "text": "Dans quelle ville se trouve le batiment ?", "step": "site"},
        ],
        "fields": {"monthly_kwh", "bill", "roof_area", "city", "network_existing"},
    },
    "hybrid": {
        "required_any": [["daily_kwh", "monthly_kwh", "bill"]],
        "questions": [
            {"id": "monthly_kwh", "text": "Connaissez-vous votre consommation mensuelle ou votre facture moyenne ?", "step": "energy"},
            {"id": "priority_loads", "text": "Quels appareils voulez-vous garder pendant les coupures ?", "step": "storage"},
            {"id": "autonomy", "text": "Quelle autonomie souhaitez-vous sur batterie ?", "step": "storage"},
            {"id": "city", "text": "Dans quelle ville est le projet ?", "step": "site"},
        ],
        "fields": {"daily_kwh", "monthly_kwh", "bill", "priority_loads", "autonomy", "city", "outages", "network_existing", "objective"},
    },
    "thermal": {
        "required": ["people"],
        "questions": [
            {"id": "people", "text": "Pour combien de personnes ?", "step": "usage"},
            {"id": "city", "text": "Dans quelle ville se trouve le projet ?", "step": "site"},
        ],
        "fields": {"people", "city"},
    },
    "ev": {
        "required": ["charger_power"],
        "questions": [
            {"id": "charger_power", "text": "Quelle puissance de borne souhaitez-vous ?", "step": "vehicle"},
            {"id": "available_power", "text": "Quelle puissance est disponible sur place ?", "step": "installation"},
            {"id": "phases", "text": "Votre installation est-elle en monophase ou triphase ?", "step": "installation"},
            {"id": "city", "text": "Dans quelle ville se fera l'installation ?", "step": "installation"},
        ],
        "fields": {"charger_power", "available_power", "phases", "city", "daily_km"},
    },
}

SHARED_FIELDS = {"city"}


def question_by_id(project: str | None, question_id: str | None) -> dict | None:
    if not project or project not in PROJECT_FLOWS or not question_id:
        return None
    for question in PROJECT_FLOWS[project]["questions"]:
        if question["id"] == question_id:
            return question
    return None


def next_question(project: str | None, data: dict, answered_fields: list[str] | None = None) -> dict | None:
    if not project or project not in PROJECT_FLOWS:
        return None
    answered = set(answered_fields or [])
    for question in PROJECT_FLOWS[project]["questions"]:
        key = question["id"]
        show_if = question.get("show_if") or {}
        if any(bool(data.get(cond_key)) is not bool(expected) and data.get(cond_key) != expected for cond_key, expected in show_if.items()):
            continue
        if key == "monthly_kwh" and (data.get("monthly_kwh") or data.get("bill") or data.get("daily_kwh")):
            continue
        if key == "daily_kwh" and (data.get("daily_kwh") or data.get("monthly_kwh") or data.get("bill")):
            continue
        if data.get(key) not in (None, "", []):
            continue
        if key in answered and key in {"city", "roof_area", "autonomy", "peak_kw"}:
            continue
        return question
    return None


def has_minimum(project: str | None, data: dict) -> bool:
    if not project or project not in PROJECT_FLOWS:
        return False
    if project == "pumping":
        if data.get("pump_existing") is True:
            return data.get("existing_pump_cv") not in (None, "", [])
        return all(data.get(key) not in (None, "", []) for key in ("water_need", "depth", "city"))
    flow = PROJECT_FLOWS[project]
    for key in flow.get("required", []):
        if data.get(key) in (None, "", []):
            return False
    for group in flow.get("required_any", []):
        if not any(data.get(key) not in (None, "", []) for key in group):
            return False
    return True


def missing_fields(project: str | None, data: dict, answered_fields: list[str] | None = None) -> list[str]:
    question = next_question(project, data, answered_fields=answered_fields)
    return [question["id"]] if question else []


def prune_data_for_project(project: str | None, data: dict) -> dict:
    if not project or project not in PROJECT_FLOWS:
        return dict(data or {})
    allowed = set(PROJECT_FLOWS[project].get("fields") or set()) | SHARED_FIELDS
    return {
        key: value
        for key, value in (data or {}).items()
        if key in allowed
    }
