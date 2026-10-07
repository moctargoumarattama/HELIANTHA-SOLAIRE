"""Authoritative catalogue service providing access to live SQLite products."""

from __future__ import annotations

from typing import Any, List
from flask import has_app_context

from ..db import list_products


def get_all_products(category: str = "", active: str = "1", stock: str = "available") -> List[dict[str, Any]]:
    """Retrieve verified catalogue products from the SQLite database."""
    if not has_app_context():
        return []
    try:
        products = list_products(category=category, active=active, stock=stock)
        if not products and stock:
            products = list_products(category=category, active=active)
        return products or []
    except Exception:
        return []
