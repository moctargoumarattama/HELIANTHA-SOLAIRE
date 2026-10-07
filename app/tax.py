"""Central, validated VAT profiles and decimal monetary arithmetic."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


VAT_PROFILES = (
    {"key": "residential", "title": "Taux communs & résidentiel (On-Grid et Hybride)"},
    {"key": "pumping", "title": "Pompage solaire agricole"},
)
_PROFILE_LABELS = {
    "residential": {"equipment": "Onduleurs et batteries lithium", "accessories": "Structures, coffrets et câblage"},
    "pumping": {"equipment": "Variateurs et pompes", "accessories": "Accessoires, tuyauterie et structure"},
}
VAT_FIELDS = tuple(
    {"key": f"{profile}_{component}", "profile": profile, "label": _PROFILE_LABELS[profile].get(component, label), "default": default}
    for profile in ("residential", "pumping")
    for component, label, default in (
        ("panels", "Panneaux photovoltaïques", "10"),
        ("equipment", "Équipements principaux", "20"),
        ("accessories", "Accessoires, structure, câblage et protections", "20"),
        ("transport", "Transport", "10"),
        ("installation", "Installation et mise en service", "20"),
    )
)
_VAT_KEYS = {field["key"] for field in VAT_FIELDS}
_VAT_RANGE_MESSAGE = "Le taux de TVA doit être compris entre 0 % et 30 %"


class TaxValidationError(ValueError):
    def __init__(self, message: str, errors: dict[str, str] | None = None):
        self.errors = errors or {}
        super().__init__(message)


def parse_vat_percentage(raw: Any) -> Decimal:
    """Parse a percentage, preserving zero and rejecting non-finite/out-of-range values."""
    try:
        value = Decimal(str(raw).strip().replace(",", "."))
    except (InvalidOperation, ValueError, TypeError):
        raise TaxValidationError("Veuillez saisir un taux de TVA numérique.") from None
    if not value.is_finite() or not Decimal("0") <= value <= Decimal("30"):
        raise TaxValidationError(_VAT_RANGE_MESSAGE)
    return value


def _context_value(context: Any, key: str, default: Any = None) -> Any:
    if isinstance(context, Mapping):
        return context.get(key, default)
    if key == "pumping_solar_rules":
        return getattr(context, key, getattr(context, "pumping_rules", default))
    return getattr(context, key, default)


def _row_value(row: Any) -> Any:
    return row.get("value") if isinstance(row, Mapping) else row


def _legacy_pumping_percentage(raw: Any) -> Decimal:
    try:
        value = Decimal(str(raw).strip().replace(",", "."))
    except (InvalidOperation, ValueError, TypeError):
        raise TaxValidationError("Veuillez saisir un taux de TVA numérique.") from None
    if not value.is_finite():
        raise TaxValidationError(_VAT_RANGE_MESSAGE)
    return parse_vat_percentage(value * 100 if value <= 1 else value)


def get_vat_rates(context: Any = None) -> dict[str, Decimal]:
    """Return ten percentages, preferring the central configuration over legacy profiles."""
    rates = {field["key"]: Decimal(field["default"]) for field in VAT_FIELDS}
    central = _context_value(context, "vat_rates", {}) or {}
    if not isinstance(central, Mapping):
        central = {row["key"]: row for row in central}
    for key, row in central.items():
        if key in _VAT_KEYS:
            rates[key] = parse_vat_percentage(_row_value(row))
    missing = _VAT_KEYS - central.keys()
    if not missing:
        return rates
    ongrid = _context_value(context, "ongrid_parameters", {}) or {}
    for old_key, components in (
        ("vat_pv_rate", ("panels",)),
        ("vat_transport_rate", ("transport",)),
        ("vat_standard_rate", ("equipment", "accessories", "installation")),
    ):
        value = _row_value(ongrid.get(old_key))
        targets = [f"residential_{component}" for component in components if f"residential_{component}" in missing]
        if targets and value not in (None, ""):
            percentage = parse_vat_percentage(value)
            for target in targets:
                rates[target] = percentage

    pumping = _context_value(context, "pumping_solar_rules", {}) or {}
    rows = list(pumping.values()) if isinstance(pumping, Mapping) else list(pumping)
    rows = sorted(rows, key=lambda row: (int(row.get("sort_order") or 0), str(row.get("rule_key") or "")))
    pump_sale = None
    seen = set()
    for row in rows:
        if int(row.get("active", 1) or 0) != 1 or row.get("vat_rate") in (None, ""):
            continue
        if row.get("rule_type") == "pump_sale_parameters" and pump_sale is None and "pumping_equipment" in missing:
            pump_sale = _legacy_pumping_percentage(row["vat_rate"])
        if row.get("rule_type") != "vat_pricing":
            continue
        applies_to = row.get("applies_to")
        if applies_to in seen:
            continue
        seen.add(applies_to)
        if applies_to in {"panels", "transport"}:
            if f"pumping_{applies_to}" in missing:
                rates[f"pumping_{applies_to}"] = _legacy_pumping_percentage(row["vat_rate"])
        elif applies_to == "others":
            targets = [f"pumping_{component}" for component in ("equipment", "accessories", "installation") if f"pumping_{component}" in missing]
            if targets:
                value = _legacy_pumping_percentage(row["vat_rate"])
                for target in targets:
                    rates[target] = value
    if pump_sale is not None:
        rates["pumping_equipment"] = pump_sale

    return rates


def vat_rate_for_component(context: Any, project: str, component: str) -> Decimal:
    """Resolve a percentage profile to the ratio consumed by the pricing engines."""
    profile = "pumping" if str(project).lower() in {"pumping", "pompage", "pump"} else "residential"
    normalized = str(component or "").strip().lower()
    if normalized in {"panel", "panels", "pv"}:
        family = "panels"
    elif normalized in {"equipment", "principal_equipment", "pump", "pumps", "pump_drive", "drive", "drives", "inverter", "inverters", "battery", "batteries"}:
        family = "equipment"
    elif normalized in {"installation", "install", "labor", "services"}:
        family = "installation"
    elif normalized == "transport":
        family = "transport"
    else:
        family = "accessories"
    return get_vat_rates(context)[f"{profile}_{family}"] / 100


def money(value: Any) -> Decimal:
    """Round monetary amounts to cents using one rule throughout the application."""
    try:
        amount = Decimal(str(0 if value in (None, "") else value).replace(",", "."))
        if not amount.is_finite():
            raise InvalidOperation
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Le montant doit être un nombre fini.") from None


def vat_amount(ht: Any, ratio: Any) -> Decimal:
    return money(Decimal(str(ht)) * Decimal(str(ratio)))


def line_vat_amount(item: Mapping[str, Any]) -> Decimal:
    """Preserve the contractual pump TTC when HT was derived from internal PT."""
    specs = item.get("technical_specs") or {}
    pump_ttc = specs.get("pump_sale_price_ttc", item.get("pump_sale_price_ttc"))
    is_pump = item.get("component") in {"pump", "pumps"} or item.get("category") == "pumps"
    if is_pump and specs.get("price_tax_basis") == "internal_pt" and pump_ttc not in (None, ""):
        try:
            ttc = Decimal(str(pump_ttc))
            if ttc.is_finite() and ttc >= 0:
                quantity = item.get("quantity")
                quantity = Decimal(str(1 if quantity is None else quantity))
                return money(ttc * quantity) - money(item.get("total_price"))
        except (InvalidOperation, ValueError, TypeError):
            pass
    ratio = item.get("vat_rate")
    return vat_amount(item.get("total_price") or 0, 0 if ratio in (None, "") else ratio)
