"""Read-only AI stream diagnostics with every external dependency mocked.

Run from the repository root: python scratch/audit_2026_10_12/diagnose_ai.py
No application creation, database connection, network request or business edit.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services import ai_service
from app.services import catalog_service
from app.services import assistant_devis


FALLBACK = "[REPLI DE DIAGNOSTIC]"
MESSAGES = [{"role": "user", "content": "Comment dimensionner une protection DC ?"}]


def diagnose(label: str, response_chunks: list[str]) -> dict:
    response = MagicMock()
    response.__enter__.return_value = response
    response.raise_for_status.return_value = None
    response.iter_lines.return_value = [
        json.dumps({"message": {"content": chunk}}) for chunk in response_chunks
    ]
    with (
        patch.object(ai_service.requests, "post", return_value=response),
        patch.object(ai_service.requests, "get", side_effect=AssertionError("Network forbidden")),
        patch.object(ai_service.sqlite3, "connect", side_effect=AssertionError("Database forbidden")),
        patch.object(ai_service, "messages_with_system_prompt", return_value=MESSAGES),
        patch.object(ai_service, "record_ai_observation") as telemetry,
        patch.object(ai_service, "offline_fallback_response", return_value={"content": FALLBACK}) as fallback,
    ):
        emitted = list(ai_service.stream_ollama_chat(MESSAGES, products=[]))
    return {
        "case": label,
        "input_chunks": response_chunks,
        "output_chunks": emitted,
        "fallback_calls": fallback.call_count,
        "recorded_success": telemetry.call_args.args[0] if telemetry.called else None,
        "unexpected_fallback": FALLBACK in emitted and bool(response_chunks),
    }


def diagnose_local_paths() -> list[dict]:
    """Compare local quote guidance without creating an app or opening SQLite."""
    pumping_history = [
        {"role": "user", "content": "Pompage solaire pour puits agricole"},
        {"role": "assistant", "content": "Quelle est la puissance de votre pompe en CV ou kW ?"},
        {"role": "user", "content": "2cv 220v monophase"},
    ]
    with (
        patch.object(ai_service.sqlite3, "connect", side_effect=AssertionError("Database forbidden")),
        patch.object(ai_service.requests, "post", side_effect=AssertionError("Network forbidden")),
        patch.object(ai_service.requests, "get", side_effect=AssertionError("Network forbidden")),
        patch.object(ai_service, "company_profile_from_settings", return_value=ai_service.DEFAULT_COMPANY_PROFILE),
        patch.object(catalog_service, "get_all_products", return_value=[]),
    ):
        french = ai_service.quick_solar_power_response(
            [{"role": "user", "content": "Ma facture est de 1800 DH par mois"}], products=[]
        )
        darija = ai_service.quick_assistant_response(
            [{"role": "user", "content": "fakhtora diali 1800 dh"}]
        )
        pumping = ai_service.quick_assistant_response(pumping_history)
    return [
        {
            "case": "same_bill_different_language",
            "french_kwc": french.get("action", {}).get("estimated_kwc"),
            "darija_kwc": darija.get("action", {}).get("estimated_kwc"),
            "french_product_count": len(french.get("suggested_products", [])),
            "darija_product_count": len(darija.get("suggested_products", [])),
        },
        {
            "case": "explicit_220v_single_phase_pump",
            "input": pumping_history[-1]["content"],
            "response_mentions_380v": "380V" in pumping["content"],
            "response": pumping["content"],
            "suggested_drives": [
                {key: product.get(key) for key in ("reference", "power_kw", "source", "en_stock")}
                for product in pumping.get("suggested_products", [])
            ],
        },
    ]


def diagnose_quote_replay() -> dict:
    history = [{
        "role": "user",
        "content": (
            "Je veux un devis autoconsommation. Nom: Client Direct. "
            "Telephone: 0600000000. Ville: Rabat. Conso 1000 kWh par mois. Monophase."
        ),
    }]
    factory = MagicMock(return_value={
        "id": 123, "ref": "AUDIT-FAKE-123", "total_ttc": "10000 DH",
        "system_summary": "Systeme solaire autoconsommation",
        "download_url": "/api/quotes/123/document.pdf",
    })
    with (
        patch.object(ai_service.sqlite3, "connect", side_effect=AssertionError("Database forbidden")),
        patch.object(assistant_devis, "load_company_name", return_value="HELIANTHA"),
    ):
        manager = assistant_devis.AssistantDevisManager()
        first = manager.handle(history, quote_factory=factory)
        history.extend([{"role": "assistant", "content": first.content}, {"role": "user", "content": "Merci"}])
        followup = manager.handle(history, quote_factory=factory)
    return {
        "case": "thank_you_after_completed_quote",
        "first_quote_created": first.quote is not None,
        "followup_handled": followup.handled,
        "followup_quote_created": followup.quote is not None,
        "quote_factory_calls": factory.call_count,
    }


if __name__ == "__main__":
    cases = [
        ("control_final_period", ["Une protection DC doit etre adaptee au courant."]),
        ("successful_final_space", ["Une protection DC doit etre adaptee au courant. "]),
        ("successful_final_newline", ["Une protection DC doit etre adaptee au courant.\n"]),
        ("success_two_sentence_boundaries", ["Premiere phrase. ", "Deuxieme phrase."]),
    ]
    for label, chunks in cases:
        print(json.dumps(diagnose(label, chunks), ensure_ascii=True))
    for result in diagnose_local_paths():
        print(json.dumps(result, ensure_ascii=True))
    print(json.dumps(diagnose_quote_replay(), ensure_ascii=True))
