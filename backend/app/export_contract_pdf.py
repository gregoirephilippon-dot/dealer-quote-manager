from datetime import datetime
from html import escape
from pathlib import Path

from database import get_connection, init_db
from export_quote_pdf import get_company_branding, company_identity_html

from reportlab.lib import colors
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


BASE_DIR = Path(__file__).resolve().parents[2]
EXPORT_DIR = BASE_DIR / "data" / "exports"


def money(value, currency="EUR"):
    if value is None:
        return "-"
    return f"{float(value):,.2f} {currency}".replace(",", " ").replace(".", ",")


def number(value, suffix=""):
    if value is None:
        return "-"

    value = float(value)

    if value.is_integer():
        text = str(int(value))
    else:
        text = f"{value:,.2f}".replace(",", " ").replace(".", ",")

    return f"{text}{suffix}"


def safe_text(value):
    if value is None:
        return "-"
    return escape(str(value))


def get_contract_pdf_data(contract_id):
    init_db()

    with get_connection() as conn:
        contract = conn.execute(
            """
            SELECT *
            FROM contracts
            WHERE id = ?
            """,
            (contract_id,),
        ).fetchone()

        if contract is None:
            raise ValueError("Contrat introuvable.")

        interventions = conn.execute(
            """
            SELECT *
            FROM contract_interventions
            WHERE contract_id = ?
            ORDER BY planned_engine_hours, planned_date, id
            """,
            (contract_id,),
        ).fetchall()

        services = conn.execute(
            """
            SELECT *
            FROM quote_services
            WHERE quote_id = ?
              AND included = 1
            ORDER BY service_id
            """,
            (contract["quote_id"],),
        ).fetchall()

        cgv = None
        cgdv = None

        if contract["cgv_version_id"]:
            cgv = conn.execute(
                """
                SELECT *
                FROM contract_terms_versions
                WHERE id = ?
                  AND company_id = ?
                """,
                (
                    contract["cgv_version_id"],
                    contract["company_id"],
                ),
            ).fetchone()

        if contract["cgdv_version_id"]:
            cgdv = conn.execute(
                """
                SELECT *
                FROM contract_terms_versions
                WHERE id = ?
                  AND company_id = ?
                """,
                (
                    contract["cgdv_version_id"],
                    contract["company_id"],
                ),
            ).fetchone()

    return contract, interventions, services, cgv, cgdv


def build_styles():
    styles = getSampleStyleSheet()

    styles.add(
        ParagraphStyle(
            name="ContractTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#102033"),
            spaceAfter=10,
        )
    )

    styles.add(
        ParagraphStyle(
            name="ContractSection",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#102033"),
            spaceBefore=10,
            spaceAfter=7,
        )
    )

    styles.add(
        ParagraphStyle(
            name="ContractSmall",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=11,
        )
    )

    styles.add(
        ParagraphStyle(
            name="ContractTerms",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=10,
            spaceAfter=5,
        )
    )

    return styles


def add_kv_table(story, rows):
    table = Table(
        rows,
        colWidths=[
            36 * mm,
            52 * mm,
            36 * mm,
            52 * mm,
        ],
    )

    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F3F4F6")),
                ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#F3F4F6")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                ("FONTNAME", (3, 0), (3, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D1D5DB")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )

    story.append(table)


def terms_story(story, title, term, styles):
    story.append(Paragraph(title, styles["ContractSection"]))

    if term is None:
        story.append(
            Paragraph(
                "Aucune version associee a ce contrat.",
                styles["ContractSmall"],
            )
        )
        return

    story.append(
        Paragraph(
            f"<b>Version :</b> {safe_text(term['version_code'])}"
            f" &nbsp;&nbsp; <b>Titre :</b> {safe_text(term['title'])}",
            styles["ContractSmall"],
        )
    )

    story.append(Spacer(1, 5))

    content = str(term["content_text"] or "").strip()

    if not content:
        story.append(
            Paragraph(
                "Aucun contenu.",
                styles["ContractSmall"],
            )
        )
        return

    paragraphs = [
        part.strip()
        for part in content.replace("\r\n", "\n").split("\n")
        if part.strip()
    ]

    for part in paragraphs:
        story.append(
            Paragraph(
                safe_text(part),
                styles["ContractTerms"],
            )
        )


def export_contract_pdf(contract_id):
    contract, interventions, services, cgv, cgdv = get_contract_pdf_data(
        contract_id
    )

    branding = get_company_branding(contract)

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"contract_{contract_id}_{timestamp}.pdf"
    output_path = EXPORT_DIR / filename

    styles = build_styles()

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    story = []

    logo_path = branding.get("logo_path")

    if logo_path and Path(logo_path).exists():
        try:
            logo = Image(str(logo_path))
            logo._restrictSize(45 * mm, 22 * mm)
        except Exception:
            logo = ""
    else:
        logo = ""

    identity = Paragraph(
        company_identity_html(branding),
        styles["ContractSmall"],
    )

    header = Table(
        [[logo, identity]],
        colWidths=[55 * mm, 120 * mm],
    )

    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    story.append(header)
    story.append(Spacer(1, 10))

    story.append(
        Paragraph(
            "CONTRAT DE MAINTENANCE PIECES ET SERVICE",
            styles["ContractTitle"],
        )
    )

    story.append(
        Paragraph(
            f"Contrat n° <b>{safe_text(contract['contract_number'])}</b>",
            styles["ContractSmall"],
        )
    )

    story.append(Paragraph("Informations contractuelles", styles["ContractSection"]))

    currency = contract["currency"] or "EUR"

    add_kv_table(
        story,
        [
            [
                "Client",
                safe_text(contract["customer_name"]),
                "Statut",
                safe_text(contract["status"]),
            ],
            [
                "Machine / moteur",
                safe_text(
                    contract["product_designation"]
                    or contract["product_name"]
                ),
                "Numero de serie",
                safe_text(contract["engine_serial_number"]),
            ],
            [
                "Date de debut",
                safe_text(contract["start_date"]),
                "Date de fin prevue",
                safe_text(contract["planned_end_date"]),
            ],
            [
                "Compteur debut",
                number(contract["start_engine_hours"], " h"),
                "Compteur fin",
                number(contract["planned_end_engine_hours"], " h"),
            ],
            [
                "Heures / an",
                number(contract["hours_per_year"], " h"),
                "Montant contrat",
                money(contract["contract_total"], currency),
            ],
            [
                "Facturation",
                (
                    "Mensuelle"
                    if contract["billing_mode"] == "monthly"
                    else "A l'intervention"
                ),
                "Devise",
                currency,
            ],
        ],
    )

    story.append(Paragraph("Cadre du contrat", styles["ContractSection"]))

    story.append(
        Paragraph(
            "Le present document formalise un contrat de maintenance pieces "
            "et service selon le perimetre defini dans l'offre commerciale "
            "et les prestations reprises ci-dessous.",
            styles["ContractSmall"],
        )
    )

    if services:
        story.append(Paragraph("Services inclus", styles["ContractSection"]))

        service_data = [["ID", "Service", "Temps", "Quantite"]]

        for service in services:
            service_data.append(
                [
                    safe_text(service["service_id"]),
                    Paragraph(
                        safe_text(service["service_name"]),
                        styles["ContractSmall"],
                    ),
                    number(service["work_time_hours"], " h"),
                    number(service["quantity"]),
                ]
            )

        service_table = Table(
            service_data,
            colWidths=[
                20 * mm,
                100 * mm,
                28 * mm,
                28 * mm,
            ],
            repeatRows=1,
        )

        service_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#102033")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D1D5DB")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )

        story.append(service_table)

    story.append(Paragraph("Planning contractuel", styles["ContractSection"]))

    intervention_data = [
        [
            "Intervention",
            "Heures moteur",
            "Date prevue",
            "Statut",
        ]
    ]

    for intervention in interventions:
        intervention_data.append(
            [
                safe_text(intervention["intervention_type"]),
                number(intervention["planned_engine_hours"], " h"),
                safe_text(intervention["planned_date"]),
                safe_text(intervention["status"]),
            ]
        )

    if len(intervention_data) == 1:
        intervention_data.append(["-", "-", "-", "-"])

    intervention_table = Table(
        intervention_data,
        colWidths=[
            60 * mm,
            38 * mm,
            38 * mm,
            38 * mm,
        ],
        repeatRows=1,
    )

    intervention_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#102033")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D1D5DB")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    story.append(intervention_table)

    story.append(PageBreak())

    terms_story(
        story,
        "Conditions Generales de Vente - CGV",
        cgv,
        styles,
    )

    story.append(Spacer(1, 10))

    terms_story(
        story,
        "Conditions Generales de Vente / Service - CGDV",
        cgdv,
        styles,
    )

    story.append(PageBreak())

    story.append(Paragraph("Acceptation du contrat", styles["ContractSection"]))

    story.append(
        Paragraph(
            "Les parties reconnaissent avoir pris connaissance du present "
            "contrat ainsi que des versions de CGV et CGDV qui lui sont "
            "associees.",
            styles["ContractSmall"],
        )
    )

    story.append(Spacer(1, 18))

    signature_table = Table(
        [
            ["Pour le dealer", "Pour le client"],
            ["Nom :", "Nom :"],
            ["Date :", "Date :"],
            ["Signature et cachet :", "Signature et cachet :"],
            ["", ""],
        ],
        colWidths=[88 * mm, 88 * mm],
    )

    signature_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#102033")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#9CA3AF")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 4), (-1, 4), 45),
            ]
        )
    )

    story.append(signature_table)

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawString(
            15 * mm,
            8 * mm,
            f"Contrat {contract['contract_number']}",
        )
        canvas.drawRightString(
            195 * mm,
            8 * mm,
            f"Page {document.page}",
        )
        canvas.restoreState()

    doc.build(
        story,
        onFirstPage=footer,
        onLaterPages=footer,
    )

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO contract_documents (
                contract_id,
                company_id,
                document_type,
                document_name,
                file_path,
                status,
                cgv_version_id,
                cgdv_version_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                contract_id,
                contract["company_id"],
                "contract_pdf",
                f"Contrat {contract['contract_number']}",
                filename,
                "generated",
                contract["cgv_version_id"],
                contract["cgdv_version_id"],
            ),
        )

        conn.commit()

    return output_path


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage : python export_contract_pdf.py <contract_id>")
        raise SystemExit(1)

    path = export_contract_pdf(int(sys.argv[1]))
    print(path)
