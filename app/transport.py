"""Validated transport tariffs shared by the admin and sizing engines."""

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from .tax import money


TRANSPORT_DESCRIPTION = "Transport, livraison et logistique sur site"
TRANSPORT_SETTINGS = (
    ("transport_ongrid_rate", "50.00", "transport", "Tarif transport On-Grid / Hybride (DH HT par panneau)"),
    ("transport_pumping_rate", "60.00", "transport", "Tarif transport Pompage Agricole (DH HT par panneau)"),
    ("transport_pumping_mode", "per_panel", "transport", "Mode de calcul du transport pompage"),
)
TRANSPORT_KEYS = {row[0] for row in TRANSPORT_SETTINGS}


class TransportValidationError(ValueError):
    pass


def validate_transport_setting(key, raw):
    if key == "transport_pumping_mode":
        if raw != "per_panel":
            raise TransportValidationError("Le transport pompage doit être calculé par panneau.")
        return "per_panel"
    try:
        value = Decimal(str(raw).strip().replace(",", "."))
    except (InvalidOperation, ValueError, TypeError):
        raise TransportValidationError("Veuillez saisir un tarif de transport numérique positif ou nul.") from None
    if not value.is_finite() or value < 0:
        raise TransportValidationError("Le tarif de transport doit être un montant fini supérieur ou égal à 0 DH.")
    try:
        return str(money(value))
    except ValueError:
        raise TransportValidationError("Le tarif de transport dépasse la précision monétaire autorisée.") from None


def transport_rate(context, project):
    """Prefer the saved tariff; retain old On-Grid tariffs for legacy contexts."""
    settings = (context.get("company_settings", {}) if isinstance(context, Mapping)
                else getattr(context, "company_settings", {})) or {}
    pumping = project == "pumping"
    key = "transport_pumping_rate" if pumping else "transport_ongrid_rate"
    default = Decimal("60.00" if pumping else "50.00")
    row = settings.get(key)
    raw = row.get("value") if isinstance(row, Mapping) else row
    if raw is None and not pumping:
        ongrid = (context.get("ongrid_parameters", {}) if isinstance(context, Mapping)
                  else getattr(context, "ongrid_parameters", {})) or {}
        row = ongrid.get("transport_per_pv")
        raw = row.get("value") if isinstance(row, Mapping) else row
    if raw is None:
        return default
    try:
        return Decimal(validate_transport_setting(key, raw))
    except TransportValidationError:
        return default
