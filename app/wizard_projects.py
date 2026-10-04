from __future__ import annotations


WIZARD_PROJECTS: dict[str, dict[str, object]] = {
    "photovoltaic": {
        "engine_project": "photovoltaic",
        "aliases": ("ongrid", "on_grid"),
    },
    "hybrid": {
        "engine_project": "hybrid",
        "aliases": ("hybride", "hybrid", "battery", "batterie", "stockage"),
    },
    "pumping": {
        "engine_project": "pumping",
        "aliases": (),
    },
}


def normalize_wizard_project(project: str | None) -> str:
    value = str(project or "").strip()
    if not value:
        return ""
    if value in WIZARD_PROJECTS:
        return value
    for canonical, meta in WIZARD_PROJECTS.items():
        if value in (meta.get("aliases") or ()):
            return canonical
    return ""


def engine_project_for(project: str | None) -> str:
    normalized = normalize_wizard_project(project)
    if not normalized:
        return ""
    return str(WIZARD_PROJECTS[normalized]["engine_project"])
