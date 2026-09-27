"""Pump sale pricing from the internal PT catalogue amount."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any


DEFAULT_PUMP_COEFFICIENT_1 = Decimal("0.5")
DEFAULT_PUMP_COEFFICIENT_2 = Decimal("1.3")
DEFAULT_PUMP_VAT_RATE = Decimal("0.20")


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except Exception:
        return default


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _float(value: Decimal) -> float:
    return float(_money(value))


def calculate_pump_sale_price(
    internal_pt: Any,
    coefficient_1: Any = DEFAULT_PUMP_COEFFICIENT_1,
    coefficient_2: Any = DEFAULT_PUMP_COEFFICIENT_2,
    vat_rate: Any = DEFAULT_PUMP_VAT_RATE,
) -> dict[str, float]:
    """Return the client sale amounts for one pump.

    The business rule is fixed: sale TTC = PT * coefficient_1 * coefficient_2.
    The HT amount is then derived from the configured pump VAT rate.
    """

    pt = _decimal(internal_pt)
    coeff_1 = _decimal(coefficient_1, DEFAULT_PUMP_COEFFICIENT_1)
    coeff_2 = _decimal(coefficient_2, DEFAULT_PUMP_COEFFICIENT_2)
    vat = _decimal(vat_rate, DEFAULT_PUMP_VAT_RATE)
    if vat > 1:
        vat = vat / Decimal("100")
    if vat < 0:
        vat = DEFAULT_PUMP_VAT_RATE

    price_ttc = _money(pt * coeff_1 * coeff_2)
    divisor = Decimal("1") + vat
    price_ht = _money(price_ttc / divisor) if divisor > 0 else price_ttc
    vat_amount = _money(price_ttc - price_ht)
    return {
        "internal_pt": _float(pt),
        "coefficient_1": float(coeff_1),
        "coefficient_2": float(coeff_2),
        "vat_rate": float(vat),
        "price_ttc": _float(price_ttc),
        "price_ht": _float(price_ht),
        "vat_amount": _float(vat_amount),
    }


__all__ = [
    "DEFAULT_PUMP_COEFFICIENT_1",
    "DEFAULT_PUMP_COEFFICIENT_2",
    "DEFAULT_PUMP_VAT_RATE",
    "calculate_pump_sale_price",
]
