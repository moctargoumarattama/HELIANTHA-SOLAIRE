"""Verifications techniques explicables entre produits du catalogue.

La regle importante de ce module est prudente : lorsqu'une donnee necessaire
manque, le resultat demande une validation manuelle. Une compatibilite n'est
jamais affirmee sans les donnees qui permettent de la demontrer.
"""

from __future__ import annotations

import json
import math
import unicodedata
from copy import deepcopy
from typing import Any, Iterable


COMPATIBILITY_STATUSES = (
    "compatible",
    "compatible_with_warning",
    "manual_validation_required",
    "incompatible",
)

_STATUS_PRIORITY = {
    "compatible": 0,
    "compatible_with_warning": 1,
    "manual_validation_required": 2,
    "incompatible": 3,
}


def normalize_text(value: Any) -> str:
    """Return a comparison-friendly, accent-free token."""

    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return "_".join(ascii_text.lower().replace("-", " ").replace("/", " ").split())


def as_float(value: Any, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def as_ratio(value: Any, default: float | None = None) -> float | None:
    """Normalize either a 0..1 ratio or a 0..100 percentage to 0..1."""

    number = as_float(value)
    if number is None:
        return default
    if abs(number) > 1 and abs(number) <= 100:
        number /= 100
    return number


def technical_specs(product: dict[str, Any] | None) -> dict[str, Any]:
    if not product:
        return {}
    raw = product.get("technical_specs")
    if raw in (None, ""):
        raw = product.get("technical_specs_json")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return {}
    return dict(raw) if isinstance(raw, dict) else {}


def spec_value(product: dict[str, Any] | None, *keys: str, default: Any = None) -> Any:
    """Read a value from common columns first, then ``technical_specs``."""

    if not product:
        return default
    specs = technical_specs(product)
    for key in keys:
        value = product.get(key)
        if value not in (None, ""):
            return value
        value = specs.get(key)
        if value not in (None, ""):
            return value
    return default


def bool_value(value: Any, default: bool | None = None) -> bool | None:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    token = normalize_text(value)
    if token in {"1", "true", "yes", "oui", "active", "actif"}:
        return True
    if token in {"0", "false", "no", "non", "inactive", "inactif"}:
        return False
    return default


def warning(
    code: str,
    message: str,
    *,
    level: str = "warning",
    parameter: str = "",
    value: Any = "",
    recommendation: str = "Validation technique HeliAntha necessaire.",
) -> dict[str, Any]:
    return {
        "code": code,
        "level": level,
        "message": message,
        "parameter": parameter,
        "value": value,
        "recommendation": recommendation,
    }


def check(
    code: str,
    label: str,
    status: str,
    message: str,
    *,
    expected: Any = None,
    actual: Any = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "label": label,
        "status": status,
        "message": message,
        "expected": expected,
        "actual": actual,
    }


def combine_statuses(statuses: Iterable[str]) -> str:
    statuses = list(statuses)
    if not statuses:
        return "manual_validation_required"
    return max(statuses, key=lambda item: _STATUS_PRIORITY.get(item, 2))


def compatibility_result(
    checks: list[dict[str, Any]] | None = None,
    warnings: list[dict[str, Any]] | None = None,
    details: dict[str, Any] | None = None,
    *,
    forced_status: str | None = None,
) -> dict[str, Any]:
    checks = checks or []
    warnings = warnings or []
    if forced_status:
        status = forced_status
    elif any(item.get("status") == "failed" for item in checks):
        status = "incompatible"
    elif any(item.get("status") == "manual" for item in checks):
        status = "manual_validation_required"
    elif warnings or any(item.get("status") == "warning" for item in checks):
        status = "compatible_with_warning"
    elif checks and all(item.get("status") == "passed" for item in checks):
        status = "compatible"
    else:
        status = "manual_validation_required"
    return {
        "status": status,
        "compatible": status in {"compatible", "compatible_with_warning", "manual_validation_required"},
        "checks": checks,
        "warnings": warnings,
        "details": details or {},
    }


class CompatibilityChecker:
    """Perform nominal, deterministic compatibility checks.

    The checker intentionally does not contain HeliAntha business standards.
    Bounds such as the acceptable DC/AC ratio must be supplied by the caller.
    """

    version = "3.0"

    @staticmethod
    def combine(*results: dict[str, Any]) -> dict[str, Any]:
        present = [item for item in results if item]
        if not present:
            return compatibility_result(
                warnings=[warning("COMPATIBILITY_DATA_MISSING", "Aucune verification de compatibilite n'a pu etre executee.")],
                forced_status="manual_validation_required",
            )
        checks: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        details: dict[str, Any] = {}
        for item in present:
            checks.extend(deepcopy(item.get("checks") or []))
            warnings.extend(deepcopy(item.get("warnings") or []))
            details.update(deepcopy(item.get("details") or {}))
        return compatibility_result(
            checks,
            warnings,
            details,
            forced_status=combine_statuses(item.get("status", "manual_validation_required") for item in present),
        )

    def check_pv_string(
        self,
        panel: dict[str, Any] | None,
        inverter: dict[str, Any] | None,
        panel_count: int | None = None,
        *,
        panels_per_string: int | None = None,
        string_count: int | None = None,
        ambient_min_c: float | None = None,
    ) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        details: dict[str, Any] = {"validation_scope": "nominal_with_optional_cold_voc"}
        if not panel or not inverter:
            return compatibility_result(
                [check("PV_STRING_PRODUCTS_MISSING", "Produits PV", "manual", "Le panneau et l'onduleur doivent etre selectionnes.")],
                [warning("PV_STRING_VALIDATION_REQUIRED", "Validation string PV manuelle requise : produit manquant.")],
                details,
            )

        voc = as_float(spec_value(panel, "voc_v", "voc", "open_circuit_voltage_v"))
        vmp = as_float(spec_value(panel, "vmp_v", "vmp", "maximum_power_voltage_v"))
        isc = as_float(spec_value(panel, "isc_a", "isc", "short_circuit_current_a"))
        imp = as_float(spec_value(panel, "imp_a", "imp", "maximum_power_current_a"))
        max_dc = as_float(spec_value(inverter, "max_dc_voltage_v", "maximum_dc_voltage_v"))
        mppt_min = as_float(spec_value(inverter, "mppt_min_voltage_v", "mppt_voltage_min_v"))
        mppt_max = as_float(spec_value(inverter, "mppt_max_voltage_v", "mppt_voltage_max_v"))
        mppt_current = as_float(spec_value(inverter, "max_input_current_per_mppt_a", "max_mppt_current_a"))
        short_current = as_float(spec_value(inverter, "max_short_circuit_current_a", "max_pv_short_circuit_current_a"))
        mppt_count = as_float(spec_value(inverter, "number_of_mppt", "mppt_count"))

        required = {
            "panel.voc_v": voc,
            "panel.vmp_v": vmp,
            "panel.isc_a": isc,
            "panel.imp_a": imp,
            "inverter.max_dc_voltage_v": max_dc,
            "inverter.mppt_min_voltage_v": mppt_min,
            "inverter.mppt_max_voltage_v": mppt_max,
            "inverter.max_input_current_per_mppt_a": mppt_current,
        }
        missing = [name for name, value in required.items() if value is None or value <= 0]
        if missing:
            details["missing_fields"] = missing
            checks.append(check("PV_STRING_DATA_INCOMPLETE", "Donnees string PV", "manual", "Des caracteristiques electriques sont manquantes.", actual=missing))
            warnings.append(warning("PV_STRING_VALIDATION_REQUIRED", "Validation string PV manuelle requise : donnees constructeur incompletes.", value=missing))
            return compatibility_result(checks, warnings, details)

        total_panels = int(panel_count or 0)
        if panels_per_string is None:
            if total_panels <= 0:
                checks.append(check("PV_STRING_PANEL_COUNT_MISSING", "Nombre de panneaux", "manual", "Le nombre de panneaux n'est pas renseigne."))
                warnings.append(warning("PV_STRING_VALIDATION_REQUIRED", "Le nombre de panneaux est necessaire pour configurer les strings."))
                return compatibility_result(checks, warnings, details)
            min_series = max(1, math.ceil(mppt_min / vmp))
            max_series = min(math.floor(mppt_max / vmp), math.floor(max_dc / voc))
            if max_series < min_series or max_series <= 0:
                checks.append(check("PV_STRING_NO_NOMINAL_WINDOW", "Plage de tension nominale", "failed", "Aucun nombre de panneaux en serie ne respecte simultanement les limites MPPT et DC.", expected=f">= {min_series}", actual=max_series))
                return compatibility_result(checks, warnings, details)
            panels_per_string = min(total_panels, max_series)
            if panels_per_string < min_series:
                checks.append(check("PV_STRING_MPPT_VOLTAGE_LOW", "Tension MPPT", "failed", "Le champ ne contient pas assez de panneaux pour atteindre la tension MPPT minimale.", expected=min_series, actual=panels_per_string))
                return compatibility_result(checks, warnings, details)

        panels_per_string = max(1, int(panels_per_string))
        if string_count is None:
            string_count = math.ceil(total_panels / panels_per_string) if total_panels > 0 else 1
        string_count = max(1, int(string_count))
        nominal_voc = voc * panels_per_string
        nominal_vmp = vmp * panels_per_string
        mppt_slots = max(1, int(mppt_count or 1))
        parallel_per_mppt = max(1, math.ceil(string_count / mppt_slots))
        input_imp = imp * parallel_per_mppt
        input_isc = isc * parallel_per_mppt
        details.update({
            "panel_count": total_panels or panels_per_string * string_count,
            "panels_per_string": panels_per_string,
            "string_count": string_count,
            "parallel_strings_per_mppt": parallel_per_mppt,
            "voc_string_v": nominal_voc,
            "vmp_string_v": nominal_vmp,
            "imp_per_mppt_a": input_imp,
            "isc_per_mppt_a": input_isc,
        })

        checks.append(check(
            "PV_STRING_MAX_DC_VOLTAGE",
            "Tension DC maximale",
            "passed" if nominal_voc < max_dc else "failed",
            "La tension Voc nominale du string reste sous la tension DC maximale." if nominal_voc < max_dc else "La tension Voc nominale du string atteint ou depasse la tension DC maximale.",
            expected=f"< {max_dc}",
            actual=nominal_voc,
        ))
        vmp_ok = mppt_min <= nominal_vmp <= mppt_max
        checks.append(check(
            "PV_STRING_MPPT_WINDOW",
            "Plage MPPT",
            "passed" if vmp_ok else "failed",
            "La tension Vmp nominale est dans la plage MPPT." if vmp_ok else "La tension Vmp nominale est hors de la plage MPPT.",
            expected=f"{mppt_min}..{mppt_max}",
            actual=nominal_vmp,
        ))
        checks.append(check(
            "PV_STRING_MPPT_CURRENT",
            "Courant MPPT",
            "passed" if input_imp <= mppt_current else "failed",
            "Le courant nominal reste sous la limite MPPT." if input_imp <= mppt_current else "Le courant nominal depasse la limite MPPT.",
            expected=f"<= {mppt_current}",
            actual=input_imp,
        ))
        if short_current is not None and short_current > 0:
            checks.append(check(
                "PV_STRING_SHORT_CIRCUIT_CURRENT",
                "Courant de court-circuit",
                "passed" if input_isc <= short_current else "failed",
                "Le courant Isc reste sous la limite constructeur." if input_isc <= short_current else "Le courant Isc depasse la limite constructeur.",
                expected=f"<= {short_current}",
                actual=input_isc,
            ))
        else:
            checks.append(check("PV_STRING_SHORT_CIRCUIT_DATA_MISSING", "Courant de court-circuit", "manual", "La limite de court-circuit de l'onduleur n'est pas renseignee."))

        temp_coeff = as_ratio(spec_value(panel, "temperature_coefficient_voc", "temperature_coefficient_voc_percent"))
        if ambient_min_c is None or temp_coeff is None:
            missing_temp = []
            if ambient_min_c is None:
                missing_temp.append("temperature minimale du site")
            if temp_coeff is None:
                missing_temp.append("coefficient de temperature Voc")
            details["temperature_validation_missing"] = missing_temp
            checks.append(check("PV_TEMPERATURE_DATA_MISSING", "Voc a temperature extreme", "manual", "La validation a froid reste a confirmer.", actual=missing_temp))
            warnings.append(warning("PV_TEMPERATURE_VALIDATION_REQUIRED", "Validation de la tension a temperature extreme a confirmer avec les donnees site et constructeur.", value=missing_temp))
        else:
            cold_voc = nominal_voc * (1 + temp_coeff * (float(ambient_min_c) - 25.0))
            details["cold_voc_string_v"] = cold_voc
            details["ambient_min_c"] = float(ambient_min_c)
            checks.append(check(
                "PV_STRING_COLD_VOC",
                "Voc corrigee a froid",
                "passed" if cold_voc < max_dc else "failed",
                "La tension Voc corrigee reste sous la limite DC." if cold_voc < max_dc else "La tension Voc corrigee depasse la limite DC.",
                expected=f"< {max_dc}",
                actual=cold_voc,
            ))
        return compatibility_result(checks, warnings, details)

    # Alias kept for a natural service API.
    check_panel_inverter = check_pv_string

    def check_dc_ac_ratio(
        self,
        pv_power_kwp: float,
        inverter: dict[str, Any] | None,
        *,
        min_ratio: float | None = None,
        max_ratio: float | None = None,
    ) -> dict[str, Any]:
        inverter_kw = as_float(spec_value(inverter, "rated_power_kw", "power_kw", "nominal_power_kw"))
        if not inverter or not inverter_kw or inverter_kw <= 0:
            return compatibility_result(
                [check("DC_AC_INVERTER_POWER_MISSING", "Ratio DC/AC", "manual", "La puissance nominale AC de l'onduleur est manquante.")],
                [warning("DC_AC_RATIO_VALIDATION_REQUIRED", "Le ratio DC/AC ne peut pas etre valide sans puissance onduleur.")],
            )
        ratio = float(pv_power_kwp) / inverter_kw
        details = {"pv_dc_kwp": float(pv_power_kwp), "inverter_ac_kw": inverter_kw, "dc_ac_ratio": ratio, "min_ratio": min_ratio, "max_ratio": max_ratio}
        if min_ratio is None or max_ratio is None:
            return compatibility_result(
                [check("DC_AC_RULE_NOT_CONFIGURED", "Ratio DC/AC", "manual", "Les limites HeliAntha du ratio DC/AC ne sont pas configurees.", actual=ratio)],
                [warning("DC_AC_RATIO_VALIDATION_REQUIRED", "Ratio DC/AC calcule mais limites HeliAntha a confirmer.", value=ratio)],
                details,
            )
        within = float(min_ratio) <= ratio <= float(max_ratio)
        return compatibility_result([
            check(
                "DC_AC_RATIO",
                "Ratio DC/AC",
                "passed" if within else "failed",
                "Le ratio DC/AC respecte la plage configuree." if within else "Le ratio DC/AC est hors de la plage configuree.",
                expected=f"{min_ratio}..{max_ratio}",
                actual=ratio,
            )
        ], details=details)

    check_dc_ac = check_dc_ac_ratio

    def check_battery_inverter(
        self,
        battery: dict[str, Any] | None,
        inverter: dict[str, Any] | None,
        *,
        battery_quantity: int = 1,
        required_power_kw: float | None = None,
    ) -> dict[str, Any]:
        if not battery or not inverter:
            return compatibility_result(
                [check("BATTERY_INVERTER_PRODUCTS_MISSING", "Batterie / onduleur", "manual", "La batterie et l'onduleur doivent etre selectionnes.")],
                [warning("BATTERY_INVERTER_VALIDATION_REQUIRED", "Compatibilite batterie/onduleur a confirmer : produit manquant.")],
            )
        checks: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        details: dict[str, Any] = {"battery_quantity": max(1, int(battery_quantity))}
        declared = bool_value(spec_value(inverter, "battery_compatible"))
        if declared is False:
            checks.append(check("INVERTER_NOT_BATTERY_COMPATIBLE", "Compatibilite batterie declaree", "failed", "L'onduleur est declare non compatible avec une batterie."))
        elif declared is True:
            checks.append(check("INVERTER_BATTERY_COMPATIBLE", "Compatibilite batterie declaree", "passed", "L'onduleur accepte une batterie."))
        else:
            checks.append(check("BATTERY_COMPATIBILITY_FLAG_MISSING", "Compatibilite batterie declaree", "manual", "La compatibilite batterie de l'onduleur n'est pas renseignee."))

        battery_v = as_float(spec_value(battery, "nominal_voltage_v", "voltage", "battery_voltage_v"))
        inverter_v = as_float(spec_value(inverter, "nominal_battery_voltage_v", "nominal_battery_voltage", "battery_voltage_v"))
        inverter_v_min = as_float(spec_value(inverter, "battery_voltage_min_v"))
        inverter_v_max = as_float(spec_value(inverter, "battery_voltage_max_v"))
        details.update({"battery_voltage_v": battery_v, "inverter_battery_voltage_v": inverter_v, "inverter_battery_voltage_min_v": inverter_v_min, "inverter_battery_voltage_max_v": inverter_v_max})
        if battery_v is None or (inverter_v is None and (inverter_v_min is None or inverter_v_max is None)):
            checks.append(check("BATTERY_VOLTAGE_DATA_MISSING", "Tension batterie", "manual", "Les tensions batterie/onduleur ne permettent pas une verification complete."))
        else:
            voltage_ok = (abs(battery_v - inverter_v) <= max(1.0, battery_v * 0.03)) if inverter_v is not None else inverter_v_min <= battery_v <= inverter_v_max
            checks.append(check("BATTERY_VOLTAGE_COMPATIBILITY", "Tension batterie", "passed" if voltage_ok else "failed", "Les tensions nominales sont compatibles." if voltage_ok else "Les tensions batterie et onduleur sont incompatibles.", expected=inverter_v or f"{inverter_v_min}..{inverter_v_max}", actual=battery_v))

        battery_power = as_float(spec_value(battery, "continuous_power_kw", "max_continuous_power_kw"))
        inverter_power = as_float(spec_value(inverter, "rated_power_kw", "power_kw"))
        power_needed = as_float(required_power_kw, inverter_power)
        if battery_power is None or power_needed is None:
            checks.append(check("BATTERY_POWER_DATA_MISSING", "Puissance de decharge batterie", "manual", "La puissance continue batterie ou le besoin onduleur manque."))
        else:
            available_power = battery_power * max(1, int(battery_quantity))
            details["battery_continuous_power_installed_kw"] = available_power
            checks.append(check("BATTERY_DISCHARGE_POWER", "Puissance de decharge batterie", "passed" if available_power >= power_needed else "failed", "La batterie peut fournir la puissance demandee." if available_power >= power_needed else "La puissance continue batterie est insuffisante.", expected=f">= {power_needed}", actual=available_power))

        max_parallel = as_float(spec_value(battery, "parallel_max", "max_parallel_units"))
        if max_parallel is not None:
            checks.append(check("BATTERY_PARALLEL_LIMIT", "Nombre maximal en parallele", "passed" if battery_quantity <= max_parallel else "failed", "La quantite respecte la limite constructeur." if battery_quantity <= max_parallel else "La quantite depasse la limite constructeur en parallele.", expected=f"<= {max_parallel}", actual=battery_quantity))
        else:
            checks.append(check("BATTERY_PARALLEL_DATA_MISSING", "Nombre maximal en parallele", "manual", "La limite de batteries en parallele n'est pas renseignee."))

        battery_comm = normalize_text(spec_value(battery, "communication", "communications"))
        inverter_comm = normalize_text(spec_value(inverter, "communication", "communications"))
        if not battery_comm or not inverter_comm:
            checks.append(check("BATTERY_COMMUNICATION_DATA_MISSING", "Communication batterie/onduleur", "manual", "Le protocole de communication reste a confirmer."))
        elif battery_comm == inverter_comm or battery_comm in inverter_comm or inverter_comm in battery_comm:
            checks.append(check("BATTERY_COMMUNICATION", "Communication batterie/onduleur", "passed", "Un protocole de communication commun est renseigne.", actual=battery_comm))
        else:
            checks.append(check("BATTERY_COMMUNICATION", "Communication batterie/onduleur", "manual", "Aucun protocole commun n'est evident ; validation fabricant necessaire.", expected=inverter_comm, actual=battery_comm))
            warnings.append(warning("BATTERY_INVERTER_VALIDATION_REQUIRED", "Compatibilite de communication batterie/onduleur a confirmer."))
        result = compatibility_result(checks, warnings, details)
        if result["status"] == "manual_validation_required" and not any(item["code"] == "BATTERY_INVERTER_VALIDATION_REQUIRED" for item in warnings):
            result["warnings"].append(warning("BATTERY_INVERTER_VALIDATION_REQUIRED", "Compatibilite batterie/onduleur a confirmer avec les fiches constructeur."))
        return result

    def check_pump_drive(
        self,
        pump: dict[str, Any] | None,
        drive: dict[str, Any] | None,
        *,
        pv_voltage_v: float | None = None,
    ) -> dict[str, Any]:
        if not pump or not drive:
            return compatibility_result(
                [check("PUMP_DRIVE_PRODUCTS_MISSING", "Pompe / variateur", "manual", "La pompe et le variateur doivent etre selectionnes.")],
                [warning("PUMP_DRIVE_VALIDATION_REQUIRED", "Compatibilite pompe/variateur a confirmer : produit manquant.")],
            )
        checks: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        pump_kw = as_float(spec_value(pump, "power_kw", "motor_power_kw", "rated_power_kw"))
        drive_kw = as_float(spec_value(drive, "motor_power_kw", "rated_power_kw", "power_kw"))
        if pump_kw is None or drive_kw is None:
            checks.append(check("PUMP_DRIVE_POWER_MISSING", "Puissance pompe/variateur", "manual", "Une puissance nominale est manquante."))
        else:
            checks.append(check("PUMP_DRIVE_POWER", "Puissance pompe/variateur", "passed" if drive_kw >= pump_kw else "failed", "Le variateur couvre la puissance moteur." if drive_kw >= pump_kw else "Le variateur est sous-dimensionne.", expected=f">= {pump_kw}", actual=drive_kw))

        pump_voltage = as_float(spec_value(pump, "voltage_v", "voltage"))
        output_voltage = as_float(spec_value(drive, "output_voltage_v", "voltage"))
        if pump_voltage is None or output_voltage is None:
            checks.append(check("PUMP_DRIVE_VOLTAGE_MISSING", "Tension pompe/variateur", "manual", "Les tensions moteur et sortie variateur sont incompletes."))
        else:
            voltage_ok = abs(pump_voltage - output_voltage) <= max(5.0, pump_voltage * 0.05)
            checks.append(check("PUMP_DRIVE_VOLTAGE", "Tension pompe/variateur", "passed" if voltage_ok else "failed", "Les tensions sont compatibles." if voltage_ok else "Les tensions sont incompatibles.", expected=pump_voltage, actual=output_voltage))

        pump_phases = normalize_text(spec_value(pump, "phases"))
        drive_phases = normalize_text(spec_value(drive, "phases", "output_phases"))
        if not pump_phases or not drive_phases:
            checks.append(check("PUMP_DRIVE_PHASES_MISSING", "Phases pompe/variateur", "manual", "Le nombre de phases manque sur un produit."))
        else:
            phase_ok = pump_phases == drive_phases
            checks.append(check("PUMP_DRIVE_PHASES", "Phases pompe/variateur", "passed" if phase_ok else "failed", "Les phases sont compatibles." if phase_ok else "Les phases sont incompatibles.", expected=pump_phases, actual=drive_phases))

        pump_current = as_float(spec_value(pump, "rated_current_a", "current_amp"))
        drive_current = as_float(spec_value(drive, "max_output_current_a", "current_amp"))
        if pump_current is None or drive_current is None:
            checks.append(check("PUMP_DRIVE_CURRENT_MISSING", "Courant pompe/variateur", "manual", "Les courants nominaux sont incomplets."))
        else:
            checks.append(check("PUMP_DRIVE_CURRENT", "Courant pompe/variateur", "passed" if drive_current >= pump_current else "failed", "Le courant variateur est suffisant." if drive_current >= pump_current else "Le courant variateur est insuffisant.", expected=f">= {pump_current}", actual=drive_current))

        if pv_voltage_v is not None:
            mppt_min = as_float(spec_value(drive, "mppt_voltage_min_v", "input_voltage_min_v"))
            mppt_max = as_float(spec_value(drive, "mppt_voltage_max_v", "input_voltage_max_v"))
            if mppt_min is None or mppt_max is None:
                checks.append(check("DRIVE_PV_VOLTAGE_RANGE_MISSING", "Tension PV / variateur", "manual", "La plage de tension PV du variateur est incomplete."))
            else:
                voltage_ok = mppt_min <= pv_voltage_v <= mppt_max
                checks.append(check("DRIVE_PV_VOLTAGE", "Tension PV / variateur", "passed" if voltage_ok else "failed", "La tension PV est dans la plage du variateur." if voltage_ok else "La tension PV est hors plage variateur.", expected=f"{mppt_min}..{mppt_max}", actual=pv_voltage_v))
        result = compatibility_result(checks, warnings, {"pump_power_kw": pump_kw, "drive_power_kw": drive_kw, "pv_voltage_v": pv_voltage_v})
        if result["status"] == "manual_validation_required":
            result["warnings"].append(warning("PUMP_DRIVE_VALIDATION_REQUIRED", "Compatibilite pompe/variateur a confirmer avec les fiches constructeur."))
        return result

    def check_ev_network(
        self,
        charger: dict[str, Any] | None,
        *,
        available_power_kw: float | None,
        phases: str,
        nominal_voltage_v: float | None = None,
        available_current_a: float | None = None,
    ) -> dict[str, Any]:
        if not charger:
            return compatibility_result(
                [check("EV_CHARGER_MISSING", "Borne EV", "manual", "Aucune borne n'est selectionnee.")],
                [warning("EV_NETWORK_VALIDATION_REQUIRED", "Compatibilite borne/reseau a confirmer : borne manquante.")],
            )
        checks: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        charger_kw = as_float(spec_value(charger, "rated_power_kw", "power_kw"))
        available_kw = as_float(available_power_kw)
        if charger_kw is None or available_kw is None:
            checks.append(check("EV_POWER_DATA_MISSING", "Puissance borne/reseau", "manual", "La puissance borne ou disponible est manquante."))
        else:
            checks.append(check("EV_NETWORK_POWER", "Puissance borne/reseau", "passed" if charger_kw <= available_kw else "failed", "La puissance disponible couvre la borne." if charger_kw <= available_kw else "La puissance disponible est insuffisante.", expected=f"<= {available_kw}", actual=charger_kw))

        expected_phases = normalize_text(phases)
        charger_phases = normalize_text(spec_value(charger, "phases", "phase", default=charger.get("subcategory")))
        phase_alias = {"monophasee": "monophase", "single_phase": "monophase", "triphasee": "triphase", "three_phase": "triphase"}
        expected_phases = phase_alias.get(expected_phases, expected_phases)
        charger_phases = phase_alias.get(charger_phases, charger_phases)
        if not expected_phases or not charger_phases:
            checks.append(check("EV_PHASE_DATA_MISSING", "Phases borne/reseau", "manual", "Le type de reseau ou de borne est incomplet."))
        else:
            phase_ok = expected_phases == charger_phases
            checks.append(check("EV_NETWORK_PHASES", "Phases borne/reseau", "passed" if phase_ok else "failed", "La borne correspond au type de reseau." if phase_ok else "La borne ne correspond pas au type de reseau.", expected=expected_phases, actual=charger_phases))

        charger_voltage = as_float(spec_value(charger, "nominal_voltage_v", "voltage_v", "voltage"))
        if nominal_voltage_v is None or charger_voltage is None:
            checks.append(check("EV_VOLTAGE_DATA_MISSING", "Tension borne/reseau", "manual", "La tension nominale reste a confirmer."))
        else:
            voltage_ok = abs(float(nominal_voltage_v) - charger_voltage) <= max(5.0, charger_voltage * 0.05)
            checks.append(check("EV_NETWORK_VOLTAGE", "Tension borne/reseau", "passed" if voltage_ok else "failed", "Les tensions sont compatibles." if voltage_ok else "Les tensions sont incompatibles.", expected=nominal_voltage_v, actual=charger_voltage))

        charger_current = as_float(spec_value(charger, "max_current_a", "current_amp"))
        if available_current_a is None or charger_current is None:
            checks.append(check("EV_CURRENT_DATA_MISSING", "Courant borne/reseau", "manual", "Le courant disponible ou requis reste a confirmer."))
        else:
            checks.append(check("EV_NETWORK_CURRENT", "Courant borne/reseau", "passed" if charger_current <= available_current_a else "failed", "Le courant disponible couvre la borne." if charger_current <= available_current_a else "Le courant disponible est insuffisant.", expected=f"<= {available_current_a}", actual=charger_current))
        result = compatibility_result(checks, warnings, {"charger_power_kw": charger_kw, "available_power_kw": available_kw, "charger_phases": charger_phases, "network_phases": expected_phases})
        if result["status"] == "manual_validation_required":
            result["warnings"].append(warning("EV_NETWORK_VALIDATION_REQUIRED", "Compatibilite borne/reseau a confirmer lors de la validation electrique."))
        return result

