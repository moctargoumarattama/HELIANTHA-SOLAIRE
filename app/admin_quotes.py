"""Client grouping for the single administrative quote workspace."""
import json
from unicodedata import combining, normalize

from .defaults import QUOTE_STATUSES
from .services.anti_abuse import whatsapp_phone_key
from .tax import money

ADMIN_QUOTE_STATUSES = tuple(status for status in QUOTE_STATUSES if status != "Visite programmee")


def display_quote_status(status):
    return "Étude" if status == "Visite programmee" else status


def _identity_text(value):
    text = normalize("NFKD", str(value or "").casefold())
    return " ".join("".join(char for char in text if not combining(char)).split())


def _quote_display_amounts(quote):
    """Read the saved snapshot, without consulting today's prices or tax rates."""
    financial = quote.get("financial_breakdown")
    if not isinstance(financial, dict):
        try:
            financial = json.loads(quote.get("financial_breakdown_json") or "{}")
        except (TypeError, ValueError):
            financial = {}
    if not isinstance(financial, dict):
        financial = {}
    ht = financial.get("total_ht", quote.get("amount_ht") or 0)
    ttc = financial.get("total_ttc", quote.get("amount_ttc") or 0)
    vat = financial.get("vat")
    if vat is None:
        vat = money(ttc) - money(ht)  # Legacy snapshots with no VAT field.
    return {"amount_ht": ht, "amount_vat": vat, "amount_ttc": ttc}


def group_quotes_by_client(quotes):
    """Keep every quote, with one contact header per identifiable client.

    Phone identity takes priority. An email-only quote joins a phone group only
    when that email identifies a single phone, keeping shared family emails safe.
    Input rows are newest first, as returned by list_quotes().
    """
    emails = {}
    for quote in quotes:
        phone = whatsapp_phone_key(quote.get("phone"))
        email = str(quote.get("email") or "").strip().casefold()
        if phone and email:
            emails.setdefault(email, set()).add(phone)
    groups = {}
    seen = set()
    fields = ("customer_name", "phone", "email", "company", "city")
    for quote in quotes:
        if quote["id"] in seen:
            continue
        seen.add(quote["id"])
        phone = whatsapp_phone_key(quote.get("phone"))
        email = str(quote.get("email") or "").strip().casefold()
        if not phone and email and len(emails.get(email, ())) == 1:
            phone = next(iter(emails[email]))
        if phone:
            key = ("phone", phone)
        elif email:
            key = ("email", email)
        else:
            name = _identity_text(quote.get("customer_name"))
            city = _identity_text(quote.get("location") or quote.get("city"))
            key = ("name", name, city, _identity_text(quote.get("company"))) if name and city else ("quote", quote["id"])
        group = groups.setdefault(key, {**dict.fromkeys(fields, ""), "quotes": []})
        contact = {**quote, "city": quote.get("location") or quote.get("city")}
        for field in fields:
            if not group[field] and contact.get(field):
                group[field] = contact[field]
        group["quotes"].append({**quote, **_quote_display_amounts(quote), "display_status": display_quote_status(quote.get("status"))})
    return list(groups.values())
