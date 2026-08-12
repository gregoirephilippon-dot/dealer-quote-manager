import sys
from pathlib import Path

from database import get_connection, init_db


try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
        PageBreak,
        Image,
    )
except ImportError:
    print("Module manquant : reportlab")
    print("Installe-le avec : pip install reportlab")
    raise SystemExit(1)


BASE_DIR = Path(__file__).resolve().parents[2]
EXPORT_DIR = BASE_DIR / "data" / "exports"
LOGO_DIR = BASE_DIR / "storage" / "logos"


def get_company_branding(quote):
    company_id = quote["company_id"] if "company_id" in quote.keys() else None

    empty = {
        "company_name": "Société",
        "display_name": None,
        "legal_name": None,
        "address_line1": None,
        "address_line2": None,
        "postal_code": None,
        "city": None,
        "country": None,
        "phone": None,
        "email": None,
        "website": None,
        "siret": None,
        "vat_number": None,
        "logo_path": None,
    }

    if not company_id:
        return empty

    with get_connection() as conn:
        company = conn.execute(
            """
            SELECT name, display_name, legal_name, address_line1, address_line2,
                   postal_code, city, country, phone, email, website,
                   siret, vat_number, logo_filename
            FROM companies
            WHERE id = ?
            """,
            (company_id,),
        ).fetchone()

    if company is None:
        empty["company_name"] = f"Société ID {company_id}"
        return empty

    display_name = company["display_name"] or company["name"] or f"Société ID {company_id}"

    logo_path = None
    logo_filename = company["logo_filename"]
    if logo_filename:
        candidate = LOGO_DIR / logo_filename
        if candidate.exists():
            logo_path = candidate

    return {
        "company_name": company["name"] or display_name,
        "display_name": display_name,
        "legal_name": company["legal_name"],
        "address_line1": company["address_line1"],
        "address_line2": company["address_line2"],
        "postal_code": company["postal_code"],
        "city": company["city"],
        "country": company["country"],
        "phone": company["phone"],
        "email": company["email"],
        "website": company["website"],
        "siret": company["siret"],
        "vat_number": company["vat_number"],
        "logo_path": logo_path,
    }


def company_identity_html(branding):
    lines = []

    legal_name = branding.get("legal_name")
    display_name = branding.get("display_name") or branding.get("company_name") or "Société"

    if legal_name and legal_name != display_name:
        lines.append(f"<b>{legal_name}</b>")
    else:
        lines.append(f"<b>{display_name}</b>")

    for key in ["address_line1", "address_line2"]:
        value = branding.get(key)
        if value:
            lines.append(str(value))

    postal_city = " ".join(
        str(v) for v in [branding.get("postal_code"), branding.get("city")]
        if v
    ).strip()
    if postal_city:
        lines.append(postal_city)

    if branding.get("country"):
        lines.append(str(branding["country"]))

    contacts = []
    if branding.get("phone"):
        contacts.append(f"Tél. {branding['phone']}")
    if branding.get("email"):
        contacts.append(str(branding["email"]))
    if contacts:
        lines.append(" - ".join(contacts))

    if branding.get("website"):
        lines.append(str(branding["website"]))

    legal = []
    if branding.get("siret"):
        legal.append(f"SIRET : {branding['siret']}")
    if branding.get("vat_number"):
        legal.append(f"TVA : {branding['vat_number']}")
    if legal:
        lines.append(" - ".join(legal))

    return "<br/>".join(lines)

def money(value, currency="EUR"):
    if value is None:
        return "-"
    return f"{value:,.2f} {currency}".replace(",", " ").replace(".", ",")


def number(value, suffix=""):
    if value is None:
        return "-"
    if isinstance(value, float):
        text = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    else:
        text = str(value)
    return f"{text}{suffix}"


def get_quote_data(quote_id: int):
    init_db()

    with get_connection() as conn:
        quote = conn.execute(
            """
            SELECT *
            FROM quotes
            WHERE id = ?
            """,
            (quote_id,),
        ).fetchone()

        if quote is None:
            return None, [], [], {}, []

        lines = conn.execute(
            """
            SELECT *
            FROM quote_lines
            WHERE quote_id = ?
            ORDER BY id
            """,
            (quote_id,),
        ).fetchall()

        interventions = conn.execute(
            """
            SELECT *
            FROM interventions
            WHERE quote_id = ?
            ORDER BY intervention_date, id
            """,
            (quote_id,),
        ).fetchall()

        settings = conn.execute(
            """
            SELECT key, value
            FROM dealer_settings
            ORDER BY key
            """
        ).fetchall()

        services = []
        try:
            services = conn.execute(
                """
                SELECT *
                FROM quote_services
                WHERE quote_id = ? AND included = 1
                ORDER BY service_id
                """,
                (quote_id,),
            ).fetchall()
        except Exception:
            services = []

    settings_dict = {row["key"]: row["value"] for row in settings}
    return quote, lines, interventions, settings_dict, services


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#667085"))
    canvas.drawString(18 * mm, 12 * mm, "Dealer Quote Manager - offre client")
    canvas.drawRightString(192 * mm, 12 * mm, f"Page {doc.page}")
    canvas.restoreState()


def add_kv_table(story, rows, col_widths=None):
    if col_widths is None:
        col_widths = [42 * mm, 58 * mm, 42 * mm, 58 * mm]

    table = Table(rows, colWidths=col_widths)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FCFCFB")),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#1F2933")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 8))


def build_logo_block(quote):
    branding = get_company_branding(quote)
    company_name = branding.get("display_name") or branding.get("company_name") or "Société"
    logo_path = branding.get("logo_path")

    if not logo_path:
        return Paragraph(f"<b>{company_name}</b>", ParagraphStyle(
            name="LogoFallback",
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=18,
            textColor=colors.HexColor("#102033"),
        ))

    try:
        logo = Image(str(logo_path))
        max_width = 42 * mm
        max_height = 22 * mm

        width, height = logo.imageWidth, logo.imageHeight
        scale = min(max_width / width, max_height / height)
        logo.drawWidth = width * scale
        logo.drawHeight = height * scale
        return logo
    except Exception:
        return Paragraph(f"<b>{company_name}</b>", ParagraphStyle(
            name="LogoFallbackError",
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=18,
            textColor=colors.HexColor("#102033"),
        ))


def build_company_identity_block(quote):
    branding = get_company_branding(quote)
    return [
        build_logo_block(quote),
        Spacer(1, 4),
        Paragraph(company_identity_html(branding), ParagraphStyle(
            name="CompanyIdentity",
            fontName="Helvetica",
            fontSize=7.5,
            leading=9,
            textColor=colors.HexColor("#374151"),
        )),
    ]

def build_pdf(quote, lines, interventions, settings, services, output_path: Path):
    currency = quote["currency"] or "EUR"

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
    )

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="TitleBlue",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=21,
            leading=25,
            textColor=colors.HexColor("#102033"),
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Section",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=colors.HexColor("#102033"),
            spaceBefore=14,
            spaceAfter=7,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Small",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#667085"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="RightSmall",
            parent=styles["Small"],
            alignment=TA_RIGHT,
        )
    )

    story = []

    title_table = Table(
        [
            [
                build_company_identity_block(quote),
                Paragraph("Devis contrat service", styles["TitleBlue"]),
                Paragraph(f"Devis ID {quote['id']}<br/>Statut : {quote['status']}<br/>{quote['created_at']}", styles["RightSmall"]),
            ]
        ],
        colWidths=[45 * mm, 75 * mm, 58 * mm],
    )
    title_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#D8C38A")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 8),
            ]
        )
    )
    story.append(title_table)
    story.append(Spacer(1, 8))

    story.append(Paragraph("Informations moteur", styles["Section"]))
    add_kv_table(
        story,
        [
            ["Client", quote["customer_name"] or "-", "Designation", quote["product_designation"] or "-"],
            ["Numero de serie", quote["engine_serial_number"] or "-", "Produit", quote["product_name"] or "-"],
            ["Pays", quote["country"] or "-", "Devise", currency],
            ["Heures contrat", number(quote["total_hours"], " h"), "Heures par an", number(quote["hours_per_year"], " h")],
            ["Taux horaire input", money(quote["labour_rate"], currency) + "/h" if quote["labour_rate"] is not None else "-", "", ""],
        ],
    )

    selling_total = quote["selling_total"] or 0
    total_hours = quote["total_hours"] or 0
    selling_per_hour = quote["selling_per_hour"]
    if selling_per_hour is None and total_hours:
        selling_per_hour = selling_total / total_hours

    story.append(Paragraph("Synthese de l offre client", styles["Section"]))
    add_kv_table(
        story,
        [
            ["Prix total contrat", money(selling_total, currency), "Prix mensuel", money(quote["selling_monthly"], currency)],
            ["Prix horaire", money(selling_per_hour, currency) + "/h" if selling_per_hour is not None else "-", "Services inclus", str(len(services))],
            ["Heures contrat", number(total_hours, " h"), "Devise", currency],
        ],
    )

    if services:
        story.append(Paragraph("Services inclus", styles["Section"]))
        service_data = [["ID", "Service", "Temps", "Qte"]]
        for service in services:
            service_data.append(
                [
                    service["service_id"] or "",
                    service["service_name"] or "",
                    number(service["work_time_hours"], " h"),
                    number(service["quantity"]),
                ]
            )

        service_table = Table(service_data, colWidths=[22 * mm, 105 * mm, 26 * mm, 22 * mm], repeatRows=1)
        service_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#102033")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(service_table)

    # Parametres dealer internes non affiches dans l offre client.

    story.append(Paragraph("Planning des interventions", styles["Section"]))
    intervention_data = [["Date", "Heures moteur"]]
    for intervention in interventions:
        intervention_data.append(
            [
                intervention["intervention_date"] or "",
                number(intervention["engine_hours"], " h"),
            ]
        )

    if len(intervention_data) == 1:
        intervention_data.append(["-", "-"])

    table = Table(intervention_data, colWidths=[55 * mm, 55 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#102033")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)

    story.append(Spacer(1, 10))
    story.append(Paragraph("Conditions et remarques", styles["Section"]))
    story.append(Paragraph("Offre etablie sous reserve de validation technique, disponibilite des pieces et conditions contractuelles applicables.", styles["Small"]))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def export_quote_pdf(quote_id: int):
    quote, lines, interventions, settings, services = get_quote_data(quote_id)

    if quote is None:
        print(f"Devis introuvable : ID {quote_id}")
        return None

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = EXPORT_DIR / f"quote_{quote_id}.pdf"

    build_pdf(quote, lines, interventions, settings, services, output_path)

    print(f"Export PDF cree : {output_path}")
    print(f"Devis ID {quote_id}")
    print(f"Moteur : {quote['product_designation']} / SN {quote['engine_serial_number']}")
    print(f"Prix client : {money(quote['selling_total'], quote['currency'] or 'EUR')}")

    branding = get_company_branding(quote)
    logo_path = branding.get("logo_path")
    company_name = branding.get("display_name") or branding.get("company_name")
    if logo_path:
        print(f"Logo société utilisé : {logo_path}")
    else:
        print(f"Aucun logo société trouvé. Fallback texte : {company_name}")

    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage : python backend/app/export_quote_pdf.py 1")
        raise SystemExit(1)

    export_quote_pdf(int(sys.argv[1]))
