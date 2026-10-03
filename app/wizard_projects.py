from __future__ import annotations

from copy import deepcopy


WIZARD_PROJECTS: dict[str, dict[str, object]] = {
    "photovoltaic": {
        "label": "Réduire ma consommation",
        "icon": "PV",
        "description": "Dimensionnez une solution On-Grid pour réduire votre facture.",
        "engine_project": "photovoltaic",
        "aliases": ["ongrid", "on_grid"],
        "payload_fields": [
            "meter_type",
            "phase",
            "monthly_consumption_kwh",
        ],
        "summary_fields": [
            "meter_type",
            "phase",
            "monthly_consumption_kwh",
        ],
        "supports_loads": False,
    },
    "hybrid": {
        "label": "Solaire avec batteries",
        "icon": "BAT",
        "description": "Dimensionnez une solution hybride 220 V monophasée avec stockage lithium.",
        "engine_project": "hybrid",
        "aliases": ["hybride", "hybrid", "battery", "batterie", "stockage"],
        "payload_fields": [
            "monthly_consumption_kwh",
        ],
        "summary_fields": [
            "monthly_consumption_kwh",
        ],
        "supports_loads": False,
    },
    "pumping": {
        "label": "Pompage solaire",
        "icon": "P",
        "description": "Dimensionnez une solution pour forage, irrigation ou alimentation en eau.",
        "engine_project": "pumping",
        "aliases": [],
        "payload_fields": [
            "pump_existing",
            "existing_pump_cv",
            "flow_m3_h",
            "hmt_m",
        ],
        "summary_fields": [
            "pump_existing",
            "existing_pump_cv",
            "flow_m3_h",
            "hmt_m",
        ],
        "supports_loads": False,
    },
}


def normalize_wizard_project(project: str | None) -> str:
    value = str(project or "").strip()
    if not value:
        return ""
    if value in WIZARD_PROJECTS:
        return value
    for canonical, meta in WIZARD_PROJECTS.items():
        if value in (meta.get("aliases") or []):
            return canonical
    return ""


def engine_project_for(project: str | None) -> str:
    normalized = normalize_wizard_project(project)
    if not normalized:
        return ""
    return str(WIZARD_PROJECTS[normalized]["engine_project"])


def wizard_projects_payload() -> dict[str, dict[str, object]]:
    payload: dict[str, dict[str, object]] = {}
    for key, meta in WIZARD_PROJECTS.items():
        payload[key] = deepcopy(meta)
        payload[key]["aliases"] = list(meta.get("aliases") or [])
        payload[key]["payload_fields"] = list(meta.get("payload_fields") or [])
        payload[key]["summary_fields"] = list(meta.get("summary_fields") or [])
    return payload
