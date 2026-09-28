from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0
LEFT = 48.0
RIGHT = 547.0

NAVY = (0.04, 0.16, 0.27)
INK = (0.04, 0.08, 0.12)
MUTED = (0.34, 0.43, 0.54)
LINE = (0.74, 0.80, 0.87)
SOFT = (0.96, 0.98, 1.00)
WHITE = (1.0, 1.0, 1.0)


def _clean(value: Any, fallback: str = "") -> str:
    text = str(value if value is not None else fallback).strip()
    return " ".join(text.split())


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _get(source: Any, *keys: str, default: Any = "") -> Any:
    for key in keys:
        if isinstance(source, dict) and key in source:
            return source.get(key)
        if not isinstance(source, dict) and hasattr(source, key):
            return getattr(source, key)
    return default


def _money(value: Any, suffix: str = "MAD") -> str:
    amount = _number(value)
    formatted = f"{amount:,.2f}".replace(",", " ")
    return f"{formatted} {suffix}" if suffix else formatted


def _pdf_text(value: Any) -> str:
    text = _clean(value)
    replacements = {
        "\\": "\\\\",
        "(": "\\(",
        ")": "\\)",
        "\r": " ",
        "\n": " ",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text.encode("cp1252", "replace").decode("cp1252")


def _rgb(color: tuple[float, float, float]) -> str:
    return " ".join(f"{channel:.3f}" for channel in color)


def _wrap(text: Any, limit: int) -> list[str]:
    words = _clean(text).split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if current and len(candidate) > limit:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines or [""]


@dataclass
class _ImageAsset:
    data: bytes
    width: int
    height: int


class _Canvas:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def text(
        self,
        x: float,
        y: float,
        value: Any,
        *,
        size: float = 9,
        bold: bool = False,
        color: tuple[float, float, float] = INK,
    ) -> None:
        font = "F2" if bold else "F1"
        self.commands.append(
            f"{_rgb(color)} rg BT /{font} {size:.2f} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm ({_pdf_text(value)}) Tj ET"
        )

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        stroke: tuple[float, float, float] | None = LINE,
        fill: tuple[float, float, float] | None = None,
        width: float = 0.6,
    ) -> None:
        if fill is not None:
            self.commands.append(f"{_rgb(fill)} rg {x:.2f} {y:.2f} {w:.2f} {h:.2f} re f")
        if stroke is not None:
            self.commands.append(
                f"{width:.2f} w {_rgb(stroke)} RG {x:.2f} {y:.2f} {w:.2f} {h:.2f} re S"
            )

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        color: tuple[float, float, float] = LINE,
        width: float = 0.6,
    ) -> None:
        self.commands.append(
            f"{width:.2f} w {_rgb(color)} RG {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S"
        )

    def image(self, name: str, x: float, y: float, w: float, h: float) -> None:
        self.commands.append(f"q {w:.2f} 0 0 {h:.2f} {x:.2f} {y:.2f} cm /{name} Do Q")

    def content(self) -> bytes:
        return ("\n".join(self.commands) + "\n").encode("cp1252", "replace")


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(b"\xff\xd8"):
        return None
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        while index < len(data) and data[index] == 0xFF:
            index += 1
        if index >= len(data):
            break
        marker = data[index]
        index += 1
        if marker in {0xD8, 0xD9, 0x01}:
            continue
        if index + 2 > len(data):
            break
        segment_length = int.from_bytes(data[index : index + 2], "big")
        if segment_length < 2 or index + segment_length > len(data):
            break
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }:
            height = int.from_bytes(data[index + 3 : index + 5], "big")
            width = int.from_bytes(data[index + 5 : index + 7], "big")
            return width, height
        index += segment_length
    return None


def _load_logo(logo_path: str | Path | None = None) -> _ImageAsset | None:
    candidates: list[Path] = []
    if logo_path:
        candidates.append(Path(logo_path))
    root = Path(__file__).resolve().parents[2]
    candidates.extend([root / "helin.jpeg", root / "static" / "logo.png"])

    for path in candidates:
        if not path.exists() or path.suffix.lower() not in {".jpg", ".jpeg"}:
            continue
        data = path.read_bytes()
        dimensions = _jpeg_dimensions(data)
        if dimensions:
            width, height = dimensions
            return _ImageAsset(data=data, width=width, height=height)
    return None


def _write_pdf(content: bytes, logo: _ImageAsset | None = None) -> bytes:
    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")

    xobject = ""
    if logo:
        xobject = " /XObject << /Logo 7 0 R >>"
    page = (
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH:.0f} {PAGE_HEIGHT:.0f}] "
        f"/Resources << /Font << /F1 4 0 R /F2 5 0 R >>{xobject} >> /Contents 6 0 R >>"
    ).encode("ascii")
    objects.append(page)
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    objects.append(b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"endstream")

    if logo:
        image_obj = (
            f"<< /Type /XObject /Subtype /Image /Width {logo.width} /Height {logo.height} "
            f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length {len(logo.data)} >>"
        ).encode("ascii")
        objects.append(image_obj + b"\nstream\n" + logo.data + b"\nendstream")

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(pdf)


def _setting(company: dict[str, Any], key: str, default: str = "") -> str:
    return _clean(company.get(key), default)


def _draw_party_card(
    canvas: _Canvas,
    *,
    x: float,
    y: float,
    w: float,
    title: str,
    lines: list[tuple[str, bool]],
) -> None:
    canvas.rect(x, y, w, 72, stroke=LINE, fill=SOFT, width=0.7)
    canvas.text(x + 10, y + 54, title, size=8.2, bold=True, color=NAVY)
    canvas.line(x + 10, y + 47, x + w - 10, y + 47)
    current_y = y + 32
    for line, bold in lines[:4]:
        if line:
            canvas.text(x + 10, current_y, line, size=7.8, bold=bold, color=INK)
            current_y -= 11


def _line_total(line: dict[str, Any], *keys: str) -> float:
    for key in keys:
        if key in line:
            return _number(line.get(key))
    return 0.0


def _line_value(line: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in line and line.get(key) not in {"", None}:
            return line.get(key)
    return default


def _draw_table(canvas: _Canvas, quote: Any, rows: list[dict[str, Any]]) -> float:
    top = 575.0
    header_h = 24.0
    columns = [LEFT, 278.0, 318.0, 382.0, 416.0, 476.0, RIGHT]
    labels = ["Designation", "TVA", "P.U. HT", "Qte", "Total HT", "Total TTC"]

    canvas.rect(LEFT, top, RIGHT - LEFT, header_h, stroke=NAVY, fill=NAVY, width=0.4)
    label_x = [LEFT + 8, 284, 326, 389, 424, 485]
    for idx, label in enumerate(labels):
        canvas.text(label_x[idx], top + 8, label, size=7.6, bold=True, color=WHITE)

    row_h = 37.0
    y = top - row_h
    max_rows = 8
    display_rows = rows[:max_rows]
    if len(rows) > max_rows:
        display_rows[-1] = {
            "name": "Autres prestations incluses",
            "description": f"{len(rows) - max_rows + 1} lignes detaillees dans le recapitulatif.",
            "vat_rate": "",
            "unit_price": 0,
            "quantity": "",
            "total_ht": 0,
            "total_ttc": 0,
        }

    for row in display_rows:
        canvas.rect(LEFT, y, RIGHT - LEFT, row_h, stroke=LINE, fill=WHITE, width=0.55)
        for x in columns[1:-1]:
            canvas.line(x, y, x, y + row_h, color=LINE, width=0.45)

        name = _clean(
            _line_value(row, "display_designation", "name", "designation", "title", "description")
        )
        description = _clean(
            _line_value(row, "role", "category", "details", "description", default=name)
        )
        canvas.text(LEFT + 8, y + 24, _wrap(name, 38)[0], size=7.8, bold=True, color=INK)
        canvas.text(LEFT + 8, y + 9, _wrap(description, 50)[0], size=6.5, color=MUTED)

        vat = _line_value(row, "display_vat_rate", "vat_rate", "tva")
        vat_text = str(vat) if isinstance(vat, str) and "%" in vat else f"{_number(vat):.0f} %" if vat not in {"", None} else ""
        quantity = row.get("quantity", row.get("qty", ""))
        unit = _line_total(row, "display_unit_price_ht", "unit_price", "price_ht", "pu_ht")
        total_ht = _line_total(row, "display_total_price_ht", "total_ht", "line_total_ht", "total_price")
        total_ttc = _line_total(row, "display_total_ttc", "total_ttc", "line_total_ttc")

        canvas.text(292, y + 21, vat_text, size=7.5, color=INK)
        canvas.text(332, y + 21, _money(unit, ""), size=7.4, color=INK)
        canvas.text(392, y + 21, _clean(quantity), size=7.4, color=INK)
        canvas.text(425, y + 21, _money(total_ht, ""), size=7.4, color=INK)
        canvas.text(485, y + 21, _money(total_ttc, ""), size=7.5, bold=True, color=INK)
        y -= row_h

    return y


def _draw_totals(canvas: _Canvas, quote: Any) -> None:
    x = 346.0
    y = 245.0
    w = 201.0
    row_h = 22.0
    financial = _get(quote, "financial_breakdown", default={}) or {}
    total_ht = _get(quote, "total_ht", default=financial.get("total_ht", 0))
    total_tax = _get(quote, "total_tax", default=financial.get("vat", financial.get("total_tax", 0)))
    total_ttc = _get(quote, "total_ttc", default=financial.get("total_ttc", 0))

    canvas.rect(x, y + row_h * 2, w, row_h, stroke=LINE, fill=SOFT)
    canvas.text(x + 8, y + row_h * 2 + 7, "Total HT", size=7.6, bold=True, color=INK)
    canvas.text(x + 114, y + row_h * 2 + 7, _money(total_ht), size=7.4, color=INK)

    canvas.rect(x, y + row_h, w, row_h, stroke=LINE, fill=WHITE)
    canvas.text(x + 8, y + row_h + 7, "Total TVA", size=7.6, color=INK)
    canvas.text(x + 114, y + row_h + 7, _money(total_tax), size=7.4, color=INK)

    canvas.rect(x, y, w, row_h, stroke=NAVY, fill=NAVY)
    canvas.text(x + 8, y + 7, "TOTAL TTC", size=8.5, bold=True, color=WHITE)
    canvas.text(x + 104, y + 7, _money(total_ttc), size=8.4, bold=True, color=WHITE)


def build_quote_pdf(
    *,
    quote: Any,
    company: dict[str, Any],
    display_equipment_lines: list[dict[str, Any]],
    financial_summary_rows: list[dict[str, Any]] | None = None,
    logo_path: str | Path | None = None,
) -> bytes:
    del financial_summary_rows
    canvas = _Canvas()
    logo = _load_logo(logo_path)

    quote_number = _clean(_get(quote, "quote_number"), "DEVIS")
    created_at = _get(quote, "created_at")
    date_text = created_at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(created_at, "strftime") else _clean(created_at)
    validity = _clean(_get(quote, "validity_days"), _setting(company, "quote_validity_days", "15"))
    client_code = _clean(_get(quote, "client_code"), f"CL{int(_number(_get(quote, 'id'))):05d}" if _get(quote, "id") else "CL00001")

    if logo:
        logo_h = 45.0
        logo_w = min(105.0, logo_h * logo.width / max(1, logo.height))
        canvas.image("Logo", LEFT, 737, logo_w, logo_h)
    else:
        canvas.text(LEFT, 762, "HELIANTHA", size=19, bold=True, color=NAVY)
        canvas.text(LEFT, 750, "Leader de l'energie solaire au Maroc", size=6.5, color=MUTED)

    canvas.text(340, 765, f"PROPOSITION {quote_number}", size=11, bold=True, color=NAVY)
    canvas.text(395, 749, f"Date : {date_text}", size=6.7, bold=True, color=INK)
    canvas.text(395, 737, f"Validite : {validity} jours", size=6.7, bold=True, color=INK)
    canvas.text(395, 725, f"Code client : {client_code}", size=6.7, bold=True, color=INK)

    company_name = _setting(company, "company_name", "HELIANTHA")
    phone = _setting(company, "phone", _setting(company, "whatsapp", "05 30 13 35 83"))
    email = _setting(company, "email", "contact@heliantha.ma")
    website = _setting(company, "website", "www.heliantha.ma")
    address = _setting(company, "address", "Maroc")
    _draw_party_card(
        canvas,
        x=LEFT,
        y=630,
        w=230,
        title="EMETTEUR",
        lines=[
            (company_name, True),
            (address, False),
            (f"Tel. : {phone}", False),
            (f"Email : {email}   Web : {website}", False),
        ],
    )

    client_name = _clean(_get(quote, "client_name", "customer_name", "name"), "Client")
    client_phone = _clean(_get(quote, "client_phone", "phone"))
    city = _clean(_get(quote, "city", "location"))
    _draw_party_card(
        canvas,
        x=315,
        y=630,
        w=232,
        title="ADRESSE A",
        lines=[
            (client_name, True),
            (f"Tel. : {client_phone}" if client_phone else "", False),
            (city, False),
        ],
    )

    _draw_table(canvas, quote, display_equipment_lines)

    canvas.text(LEFT, 300, "Montants exprimes en Dirham Marocain (MAD)", size=7.3, bold=True, color=INK)
    canvas.text(LEFT, 286, "Modalite de paiement : 100% a la commande.", size=7.0, color=INK)
    canvas.text(LEFT, 269, "Reglement par virement bancaire :", size=7.0, bold=True, color=INK)
    canvas.text(LEFT, 256, f"Banque : {_setting(company, 'pdf_bank_name', 'CIH Bank')}", size=6.8, color=INK)
    canvas.text(LEFT, 244, f"RIB : {_setting(company, 'pdf_rib', 'A renseigner')}", size=6.8, color=INK)
    canvas.text(LEFT, 232, f"IBAN : {_setting(company, 'pdf_iban', 'A renseigner')}", size=6.8, color=INK)
    canvas.text(LEFT, 216, "Reglement par cheque :", size=7.0, bold=True, color=INK)
    canvas.text(
        LEFT,
        204,
        f"A l'ordre de {_setting(company, 'pdf_check_payee', company_name)}, adresse au : {_setting(company, 'pdf_check_address', address)}",
        size=6.8,
        color=INK,
    )

    _draw_totals(canvas, quote)

    contact_name = _setting(company, "pdf_contact_name", "Dr. Omar EL KADMIRI")
    contact_phone = _setting(company, "pdf_contact_phone", phone)
    social_links = _setting(company, "pdf_social_links", "")
    canvas.rect(LEFT, 138, RIGHT - LEFT, 34, stroke=LINE, fill=SOFT, width=0.65)
    canvas.text(LEFT + 8, 159, f"VOTRE INTERLOCUTEUR CHEZ {company_name} :", size=6.9, bold=True, color=NAVY)
    canvas.text(LEFT + 8, 148, f"{contact_name} | Tel : {contact_phone} | Email : {email}", size=6.4, color=INK)
    if social_links:
        canvas.text(LEFT + 8, 140, f"Suivez-nous : {social_links}", size=5.7, color=MUTED)

    canvas.rect(LEFT, 92, RIGHT - LEFT, 34, stroke=LINE, fill=None, width=0.5)
    canvas.commands.append("0.50 w 0.450 0.560 0.690 RG [3 3] 0 d")
    canvas.commands.append(f"{LEFT:.2f} 92.00 {RIGHT - LEFT:.2f} 34.00 re S")
    canvas.commands.append("[] 0 d")
    canvas.text(LEFT + 8, 112, 'Cachet, Date, Signature et mention "Bon pour Accord" :', size=6.2, color=MUTED)

    legal = _setting(
        company,
        "pdf_legal_footer",
        "Siege social : Heliantha - Maroc | Tel. : 05 30 13 35 83 | www.heliantha.ma | contact@heliantha.ma",
    )
    for idx, line in enumerate(_wrap(legal, 118)[:2]):
        canvas.text(145, 66 - idx * 9, line, size=5.5, color=MUTED)

    return _write_pdf(canvas.content(), logo)
