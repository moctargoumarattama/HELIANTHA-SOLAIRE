"""Small dependency-free PDF generation for quote documents."""

from __future__ import annotations

from io import BytesIO
from textwrap import wrap
from typing import Any


PAGE_WIDTH = 595
PAGE_HEIGHT = 842
LEFT = 42
RIGHT = 553


def _money(value: Any) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0
    return f"{number:,.2f}".replace(",", " ") + " MAD"


def _text(value: Any) -> str:
    text = str(value or "")
    return text.replace("\r", " ").replace("\n", " ").strip()


def _pdf_escape(value: Any) -> str:
    text = _text(value)
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class _PdfBuilder:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def text(self, x: int, y: int, value: Any, size: int = 9, bold: bool = False) -> None:
        font = "F2" if bold else "F1"
        self.commands.append(f"BT /{font} {size} Tf {x} {y} Td ({_pdf_escape(value)}) Tj ET")

    def line(self, x1: int, y1: int, x2: int, y2: int) -> None:
        self.commands.append(f"{x1} {y1} m {x2} {y2} l S")

    def rect(self, x: int, y: int, w: int, h: int) -> None:
        self.commands.append(f"{x} {y} {w} {h} re S")

    def fill_rect(self, x: int, y: int, w: int, h: int, rgb: tuple[float, float, float]) -> None:
        r, g, b = rgb
        self.commands.append(f"{r} {g} {b} rg {x} {y} {w} {h} re f 0 0 0 rg")

    def content(self) -> bytes:
        return "\n".join(self.commands).encode("cp1252", errors="replace")


def _write_pdf(content: bytes) -> bytes:
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream",
    ]

    out = BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{index} 0 obj\n".encode("ascii"))
        out.write(obj)
        out.write(b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    out.write(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("ascii")
    )
    return out.getvalue()


def build_quote_pdf(
    *,
    quote: dict[str, Any],
    company: dict[str, Any],
    display_equipment_lines: list[dict[str, Any]],
    financial_summary_rows: list[dict[str, Any]] | None = None,
) -> bytes:
    """Build a real PDF document for a quote."""

    pdf = _PdfBuilder()
    financial = quote.get("financial_breakdown") or {}
    total_ht = financial.get("total_ht") or 0
    vat = financial.get("vat") or 0
    total_ttc = financial.get("total_ttc") or 0

    pdf.fill_rect(LEFT, 774, RIGHT - LEFT, 28, (0.06, 0.15, 0.22))
    pdf.text(LEFT + 12, 784, company.get("company_name") or "HELIANTHA", 16, True)
    pdf.text(360, 785, f"PROPOSITION {quote.get('quote_number') or ''}", 11, True)
    pdf.text(360, 770, f"Date : {quote.get('created_at') or ''}", 8)
    pdf.text(360, 758, "Validite : 15 jours", 8)
    pdf.text(360, 746, f"Code client : CL{int(quote.get('id') or 0):05d}", 8)

    y = 710
    pdf.rect(LEFT, y - 70, 242, 70)
    pdf.rect(311, y - 70, 242, 70)
    pdf.text(LEFT + 10, y - 16, "EMETTEUR", 9, True)
    pdf.text(LEFT + 10, y - 34, company.get("company_name") or "HELIANTHA", 9, True)
    pdf.text(LEFT + 10, y - 48, company.get("address") or "Maroc", 8)
    pdf.text(LEFT + 10, y - 61, f"Tel. : {company.get('phone') or '-'}", 8)
    pdf.text(311 + 10, y - 16, "ADRESSE A", 9, True)
    pdf.text(311 + 10, y - 34, quote.get("customer_name") or "Client", 9, True)
    pdf.text(311 + 10, y - 48, f"Tel. : {quote.get('phone') or '-'}", 8)
    pdf.text(311 + 10, y - 61, quote.get("location") or quote.get("city") or "Maroc", 8)

    y = 610
    pdf.fill_rect(LEFT, y, RIGHT - LEFT, 20, (0.06, 0.15, 0.22))
    headers = [("Designation", LEFT + 6), ("TVA", 286), ("P.U. HT", 331), ("Qte", 389), ("Total HT", 427), ("Total TTC", 492)]
    for label, x in headers:
        pdf.text(x, y + 7, label, 7, True)

    y -= 18
    for item in display_equipment_lines[:9]:
        row_h = 42
        pdf.rect(LEFT, y - row_h + 5, RIGHT - LEFT, row_h)
        designation = item.get("display_designation") or item.get("description") or "-"
        lines = wrap(_text(designation), width=42)[:2]
        pdf.text(LEFT + 6, y - 8, lines[0] if lines else "-", 8, True)
        if len(lines) > 1:
            pdf.text(LEFT + 6, y - 20, lines[1], 7)
        role = item.get("role") or item.get("category")
        if role:
            pdf.text(LEFT + 6, y - 32, role, 7)
        pdf.text(286, y - 13, item.get("display_vat_rate") or "-", 8)
        pdf.text(331, y - 13, f"{float(item.get('display_unit_price_ht') or item.get('unit_price') or 0):,.2f}".replace(",", " "), 8)
        pdf.text(392, y - 13, item.get("quantity") or "-", 8)
        pdf.text(427, y - 13, f"{float(item.get('display_total_price_ht') or item.get('total_price') or 0):,.2f}".replace(",", " "), 8)
        pdf.text(492, y - 13, f"{float(item.get('display_total_ttc') or 0):,.2f}".replace(",", " "), 8, True)
        y -= row_h

    y = max(y - 15, 170)
    pdf.text(LEFT, y + 55, "Montants exprimes en Dirham Marocain (MAD)", 8, True)
    pdf.text(LEFT, y + 40, "Modalite de paiement : 100% a la commande.", 8)
    pdf.text(LEFT, y + 25, f"Banque : {company.get('pdf_bank_name') or '-'}", 8)
    pdf.text(LEFT, y + 10, f"RIB : {company.get('pdf_rib') or '-'}", 8)
    pdf.text(LEFT, y - 5, f"IBAN : {company.get('pdf_iban') or '-'}", 8)

    totals_x = 355
    pdf.rect(totals_x, y + 5, 198, 66)
    pdf.text(totals_x + 10, y + 52, "Total HT", 8)
    pdf.text(460, y + 52, _money(total_ht), 8)
    pdf.text(totals_x + 10, y + 32, "Total TVA", 8)
    pdf.text(460, y + 32, _money(vat), 8)
    pdf.fill_rect(totals_x, y + 5, 198, 22, (0.06, 0.15, 0.22))
    pdf.text(totals_x + 10, y + 13, "TOTAL TTC", 9, True)
    pdf.text(455, y + 13, _money(total_ttc), 9, True)

    pdf.rect(LEFT, 78, RIGHT - LEFT, 36)
    pdf.text(LEFT + 8, 99, f"VOTRE INTERLOCUTEUR CHEZ {company.get('company_name') or 'HELIANTHA'} :", 7, True)
    pdf.text(LEFT + 8, 86, f"{company.get('pdf_contact_name') or '-'} | Tel : {company.get('phone') or '-'}", 7)
    pdf.text(LEFT, 50, company.get("pdf_legal_footer") or f"{company.get('company_name') or 'HELIANTHA'} - Maroc", 7)

    return _write_pdf(pdf.content())
