from app.services.pdf_service import build_quote_pdf
from app import create_app
from app.db import get_quote_by_number


def test_build_quote_pdf_returns_real_pdf_bytes():
    quote = {
        "id": 12,
        "quote_number": "HSQ-TEST",
        "created_at": "27/09/2026 a 23:10",
        "customer_name": "Client Test",
        "phone": "0611111111",
        "city": "Rabat",
        "financial_breakdown": {"total_ht": 1000, "vat": 200, "total_ttc": 1200},
    }
    company = {
        "company_name": "HELIANTHA",
        "phone": "05 30 13 35 83",
        "address": "Maroc",
    }
    lines = [
        {
            "display_designation": "Panneaux photovoltaïques",
            "display_vat_rate": "20 %",
            "display_unit_price_ht": 100,
            "quantity": 2,
            "display_total_price_ht": 200,
            "display_total_ttc": 240,
        }
    ]

    payload = build_quote_pdf(
        quote=quote,
        company=company,
        display_equipment_lines=lines,
        financial_summary_rows=[],
    )

    assert payload.startswith(b"%PDF-1.4")
    assert b"%%EOF" in payload
    assert b"<html" not in payload.lower()


def test_public_pdf_routes_return_pdf_without_public_html(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "pdf-routes.db")})
    client = app.test_client()

    response = client.post(
        "/api/calculate",
        json={
            "project": "photovoltaic",
            "project_type": "photovoltaic",
            "data": {"meter_type": "numerique", "phase": "monophase", "monthly_consumption_kwh": 1000},
            "contact": {"name": "Client PDF", "phone": "0600000000"},
        },
    )
    assert response.status_code == 200
    quote_number = response.get_json()["quote_number"]
    with app.app_context():
        quote_id = get_quote_by_number(quote_number)["id"]

    legacy_pdf_response = client.get(f"/devis/{quote_id}/pdf", follow_redirects=True)
    assert legacy_pdf_response.status_code == 200
    assert legacy_pdf_response.mimetype == "application/pdf"
    assert legacy_pdf_response.data.startswith(b"%PDF-1.4")

    document_response = client.get(f"/devis/{quote_id}/document.pdf")
    assert document_response.status_code == 200
    assert document_response.mimetype == "application/pdf"
    assert document_response.data.startswith(b"%PDF-1.4")
