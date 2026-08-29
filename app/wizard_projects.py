from __future__ import annotations

from copy import deepcopy


WIZARD_PROJECTS: dict[str, dict[str, object]] = {
    "pumping": {
        "label": "Pompage solaire",
        "icon": "💧",
        "description": "Dimensionnez une solution pour forage, irrigation ou alimentation en eau.",
        "engine_project": "pumping",
        "aliases": [],
        "payload_fields": [
            "pump_existing",
            "existing_pump_cv",
            "water_need",
            "hours",
            "depth",
            "elevation",
            "distance",
            "city",
        ],
        "summary_fields": [
            "pump_existing",
            "existing_pump_cv",
            "water_need",
            "hours",
            "depth",
            "elevation",
            "distance",
            "city",
        ],
        "supports_loads": False,
    },
    "off_grid": {
        "label": "Site sans réseau",
        "icon": "🏠",
        "description": "Produisez et stockez votre énergie sans réseau.",
        "engine_project": "offgrid",
        "aliases": ["offgrid"],
        "payload_fields": [
            "energy_mode",
            "daily_kwh",
            "peak_kw",
            "autonomy",
            "city",
            "notes",
            "loads",
        ],
        "summary_fields": [
            "energy_mode",
            "daily_kwh",
            "peak_kw",
            "autonomy",
            "city",
            "loads",
        ],
        "supports_loads": True,
    },
    "photovoltaic": {
        "label": "Réduire ma consommation",
        "icon": "☀️",
        "description": "Réduisez votre facture avec le solaire.",
        "engine_project": "ongrid",
        "aliases": ["ongrid"],
        "payload_fields": [
            "building",
            "monthly_kwh",
            "bill",
            "day_profile",
            "network",
            "roof_area",
            "city",
        ],
        "summary_fields": [
            "building",
            "monthly_kwh",
            "bill",
            "day_profile",
            "network",
            "roof_area",
            "city",
        ],
        "supports_loads": False,
    },
    "hybrid": {
        "label": "Solaire avec batteries",
        "icon": "🔋",
        "description": "Solaire et stockage, en continuité.",
        "engine_project": "hybrid",
        "aliases": [],
        "payload_fields": [
            "energy_mode",
            "daily_kwh",
            "monthly_kwh",
            "bill",
            "peak_kw",
            "priority_kwh",
            "autonomy",
            "objective",
            "city",
            "loads",
        ],
        "summary_fields": [
            "energy_mode",
            "daily_kwh",
            "monthly_kwh",
            "bill",
            "peak_kw",
            "priority_kwh",
            "autonomy",
            "objective",
            "city",
            "loads",
        ],
        "supports_loads": True,
    },
    "thermal": {
        "label": "Chauffage solaire",
        "icon": "♨️",
        "description": "Eau chaude solaire pour maison, hôtel ou activité.",
        "engine_project": "thermal",
        "aliases": [],
        "payload_fields": [
            "people",
            "building",
            "daily_hot_water_l",
            "thermal_target_temp",
            "thermal_inlet_temp",
            "city",
        ],
        "summary_fields": [
            "people",
            "building",
            "daily_hot_water_l",
            "thermal_target_temp",
            "thermal_inlet_temp",
            "city",
        ],
        "supports_loads": False,
    },
    "ev_charging": {
        "label": "Recharge électrique",
        "icon": "🚗",
        "description": "Une borne adaptée au véhicule, au réseau et à l’usage réel.",
        "engine_project": "ev",
        "aliases": ["ev"],
        "payload_fields": [
            "vehicle",
            "vehicle_battery",
            "daily_km",
            "consumption_kwh_100km",
            "phases",
            "available_power",
            "charger_power",
            "vehicle_ac_max",
            "distance",
            "city",
        ],
        "summary_fields": [
            "vehicle",
            "vehicle_battery",
            "daily_km",
            "consumption_kwh_100km",
            "phases",
            "available_power",
            "charger_power",
            "vehicle_ac_max",
            "distance",
            "city",
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
