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
ASSETS_DIR = BASE_DIR / "data" / "assets"

LOGO_CANDIDATES = [
    ASSETS_DIR / "gwen_service_logo.png",
    ASSETS_DIR / "gwen_service_logo.jpg",
    ASSETS_DIR / "gwen_service_logo.jpeg",
    ASSETS_DIR / "logo_gwen_service.png",
    ASSETS_DIR / "logo_gwen_service.jpg",
    ASSETS_DIR / "logo.png",
]


def find_logo_path():
    for path in LOGO_CANDIDATES:
        if path.exists():
            return path
    return None


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
    canvas.drawString(18 * mm, 12 * mm, "Dealer Quote Manager - document de travail")
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


def build_logo_block():
    logo_path = find_logo_path()
    if not logo_path:
        return Paragraph("<b>GWEN SERVICE</b>", ParagraphStyle(
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
        return Paragraph("<b>GWEN SERVICE</b>", ParagraphStyle(
            name="LogoFallbackError",
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=18,
            textColor=colors.HexColor("#102033"),
        ))


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
                build_logo_block(),
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

    story.append(Paragraph("Synthese financiere", styles["Section"]))
    add_kv_table(
        story,
        [
            ["Cout brut importe", money(quote["total_cost"], currency), "Prix client", money(quote["selling_total"], currency)],
            ["Prix mensuel", money(quote["selling_monthly"], currency), "Prix par heure", money(quote["selling_per_hour"], currency) + "/h"],
            ["Pieces", money(quote["total_parts"], currency), "Main d'oeuvre", money(quote["total_labour"], currency)],
            ["Misc", money(quote["total_misc"], currency), "Services inclus", str(len(services))],
        ],
    )

    if services:
        story.append(Paragraph("Services additionnels inclus", styles["Section"]))
        service_data = [["ID", "Service", "Temps", "Qte", "Prix fixe", "Total"]]
        for service in services:
            service_data.append(
                [
                    service["service_id"] or "",
                    service["service_name"] or "",
                    number(service["work_time_hours"], " h"),
                    number(service["quantity"]),
                    money(service["fixed_price"], currency),
                    money(service["calculated_price"], currency),
                ]
            )

        service_table = Table(service_data, colWidths=[18 * mm, 74 * mm, 22 * mm, 18 * mm, 28 * mm, 28 * mm], repeatRows=1)
        service_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#102033")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(service_table)

    story.append(Paragraph("Parametres dealer appliques", styles["Section"]))
    settings_rows = [
        ["Marge pieces", f"{settings.get('parts_margin_percent', 0)} %", "Marge main d'oeuvre", f"{settings.get('labour_margin_percent', 0)} %"],
        ["Frais admin", f"{settings.get('admin_fee_percent', 0)} %", "Frais logistique", f"{settings.get('logistics_fee_percent', 0)} %"],
        ["Frais deplacement fixes", money(settings.get("travel_fee_fixed", 0), currency), "Indexation", f"{settings.get('indexation_percent', 0)} %"],
    ]
    add_kv_table(story, settings_rows)

    story.append(Paragraph("Planning des interventions", styles["Section"]))

    intervention_data = [["Date", "Heures", "Pieces", "M.O.", "Misc", "Total"]]
    for intervention in interventions:
        intervention_data.append(
            [
                intervention["intervention_date"] or "",
                number(intervention["engine_hours"], " h"),
                money(intervention["parts_cost"], currency),
                money(intervention["labour_cost"], currency),
                money(intervention["misc_cost"], currency),
                money(intervention["total_cost"], currency),
            ]
        )

    if len(intervention_data) == 1:
        intervention_data.append(["-", "-", "-", "-", "-", "-"])

    table = Table(intervention_data, colWidths=[28 * mm, 26 * mm, 32 * mm, 28 * mm, 24 * mm, 34 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#102033")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)

    story.append(PageBreak())
    story.append(Paragraph("Lignes detaillees importees", styles["Section"]))
    story.append(Spacer(1, 6))

    line_data = [["Groupe", "Description", "Reference", "Qte", "PU", "Total"]]
    max_lines = 120
    for line in lines[:max_lines]:
        line_data.append(
            [
                str(line["component"] or ""),
                str(line["description"] or ""),
                str(line["part_number"] or ""),
                number(line["quantity"]),
                money(line["unit_price"], currency),
                money(line["total_price"], currency),
            ]
        )

    if len(lines) > max_lines:
        line_data.append(["...", f"Affichage limite aux {max_lines} premieres lignes sur {len(lines)}", "", "", "", ""])

    if len(line_data) == 1:
        line_data.append(["-", "-", "-", "-", "-", "-"])

    line_table = Table(line_data, colWidths=[24 * mm, 54 * mm, 28 * mm, 16 * mm, 28 * mm, 28 * mm], repeatRows=1)
    line_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#102033")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(line_table)

    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def export_quote_pdf(quote_id: int):
    quote, lines, interventions, settings, services = get_quote_data(quote_id)

    if quote is None:
        print(f"Devis introuvable : ID {quote_id}")
        return None

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = EXPORT_DIR / f"quote_{quote_id}.pdf"

    build_pdf(quote, lines, interventions, settings, services, output_path)

    print(f"Export PDF cree : {output_path}")
    print(f"Devis ID {quote_id}")
    print(f"Moteur : {quote['product_designation']} / SN {quote['engine_serial_number']}")
    print(f"Prix client : {money(quote['selling_total'], quote['currency'] or 'EUR')}")

    logo_path = find_logo_path()
    if logo_path:
        print(f"Logo utilise : {logo_path}")
    else:
        print(f"Logo non trouve. Ajoute-le dans : {ASSETS_DIR}\\gwen_service_logo.png")

    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage : python backend/app/export_quote_pdf.py 1")
        raise SystemExit(1)

    export_quote_pdf(int(sys.argv[1]))
