from __future__ import annotations

import pytest

from app import create_app
from app.wizard_projects import WIZARD_PROJECTS, engine_project_for, normalize_wizard_project


def test_wizard_project_registry_uses_canonical_ids():
    assert list(WIZARD_PROJECTS) == [
        "pumping",
        "off_grid",
        "photovoltaic",
        "hybrid",
        "thermal",
        "ev_charging",
    ]
    assert len({meta["engine_project"] for meta in WIZARD_PROJECTS.values()}) == len(WIZARD_PROJECTS)
    assert normalize_wizard_project("offgrid") == "off_grid"
    assert normalize_wizard_project("ongrid") == "photovoltaic"
    assert normalize_wizard_project("ev") == "ev_charging"
    assert engine_project_for("off_grid") == "offgrid"
    assert engine_project_for("photovoltaic") == "ongrid"
    assert engine_project_for("ev_charging") == "ev"
    assert WIZARD_PROJECTS["off_grid"]["supports_loads"] is True
    assert WIZARD_PROJECTS["hybrid"]["supports_loads"] is True
    assert WIZARD_PROJECTS["pumping"]["supports_loads"] is False


@pytest.mark.parametrize(
    ("project_type", "data", "expected_engine"),
    [
        ("pumping", {"pump_existing": True, "existing_pump_cv": 15}, "pumping"),
        ("off_grid", {"daily_kwh": 12, "peak_kw": 4, "city": "Marrakech"}, "offgrid"),
        ("photovoltaic", {"monthly_kwh": 900, "city": "Casablanca", "roof_area": 100}, "ongrid"),
        ("thermal", {"people": 4, "city": "Fès"}, "thermal"),
        ("ev_charging", {"available_power": 6, "charger_power": 22, "vehicle_battery": 60}, "ev"),
    ],
)
def test_public_calculate_accepts_canonical_project_type_ids(tmp_path, project_type, data, expected_engine):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / f"{project_type}.db")})
    client = app.test_client()

    response = client.post(
        "/api/calculate",
        json={"project_type": project_type, "data": data},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["project"] == expected_engine
    assert payload["project_type"] == project_type
