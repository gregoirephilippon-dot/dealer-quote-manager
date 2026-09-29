import sys
from pathlib import Path

from database import get_connection, init_db
from client_translation import translate_service_name_for_client
from final_parts import build_final_parts


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
CONTRACT_ASSET_DIR = Path(__file__).resolve().parent / "contract_assets"
CGV_BANNER_PATH = CONTRACT_ASSET_DIR / "CGV.jpg"


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


def safe_float(value, default=0.0):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return float(default)


def load_imported_quote_raw(quote):
    try:
        quote_keys = quote.keys()
    except Exception:
        quote_keys = []

    if (
        "import_id" not in quote_keys
        or quote["import_id"] is None
    ):
        return None

    try:
        import json as _import_json

        with get_connection() as conn:
            import_row = conn.execute(
                """
                SELECT raw_json
                FROM imports
                WHERE id = ?
                """,
                (quote["import_id"],),
            ).fetchone()

        if not import_row or not import_row["raw_json"]:
            return None

        return _import_json.loads(
            import_row["raw_json"]
        )

    except Exception:
        return None


def build_planned_engine_hours_by_intervention(
    quote,
    interventions,
    raw_import=None,
):
    """
    Recale uniquement le compteur affiche dans le planning.

    Les interventions et toutes les donnees de maintenance
    restent celles du fichier Excel importe.

    None comme valeur de compteur signifie que le compteur reel
    de la machine n'a pas encore ete renseigne.
    """
    try:
        quote_keys = quote.keys()
    except Exception:
        quote_keys = []

    if (
        "import_id" not in quote_keys
        or quote["import_id"] is None
    ):
        return None

    if "current_engine_hours" not in quote_keys:
        return None

    current_engine_hours = quote["current_engine_hours"]

    if current_engine_hours is None:
        return {
            intervention["id"]: None
            for intervention in interventions
        }

    try:
        if raw_import is None:
            raw_import = load_imported_quote_raw(
                quote
            )

        if raw_import is None:
            return None

        calculation_basis = (
            raw_import.get("calculation_basis")
            or {}
        )

        maintenance_total_hours = float(
            calculation_basis.get(
                "total_calculation_hours",
                0,
            )
            or 0
        )

        source_hours_values = [
            float(
                intervention["engine_hours"]
                or 0
            )
            for intervention in interventions
        ]

        if (
            maintenance_total_hours <= 0
            or not source_hours_values
        ):
            return None

        # Origine arithmetique servant uniquement a convertir
        # les paliers Excel en ecarts de maintenance.
        # Ce n'est PAS un compteur moteur importe.
        schedule_origin = (
            max(source_hours_values)
            - maintenance_total_hours
        )

        real_meter = max(
            0.0,
            float(current_engine_hours),
        )

        planned_by_id = {}

        for intervention in interventions:
            source_hours = float(
                intervention["engine_hours"]
                or 0
            )

            maintenance_offset = (
                source_hours
                - schedule_origin
            )

            if maintenance_offset < -0.01:
                continue

            if (
                maintenance_offset
                > maintenance_total_hours + 0.01
            ):
                continue

            planned_by_id[intervention["id"]] = (
                real_meter
                + maintenance_offset
            )

        return planned_by_id

    except Exception:
        # Anciennes donnees / anciens imports :
        # conserver le comportement historique.
        return None


def exported_engine_hours(
    intervention,
    planned_by_id,
):
    if planned_by_id is None:
        return intervention["engine_hours"]

    return planned_by_id.get(
        intervention["id"]
    )


def build_pdf(quote, lines, interventions, settings, services, output_path: Path):
    currency = quote["currency"] or "EUR"
    final_lines = build_final_parts(quote, lines)

    technical_total_hours = safe_float(
        quote["total_hours"]
    )
    technical_hours_per_year = safe_float(
        quote["hours_per_year"]
    )

    raw_import = load_imported_quote_raw(quote)
    uses_imported_total_hours = False

    if raw_import is not None:
        calculation_basis = (
            raw_import.get("calculation_basis")
            or {}
        )

        source_total_hours = safe_float(
            calculation_basis.get(
                "total_calculation_hours",
                0,
            )
        )

        source_hours_per_year = safe_float(
            calculation_basis.get(
                "op_hours_per_year",
                0,
            )
        )

        if source_total_hours > 0:
            technical_total_hours = (
                source_total_hours
            )
            uses_imported_total_hours = True

        if source_hours_per_year > 0:
            technical_hours_per_year = (
                source_hours_per_year
            )

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
                Paragraph("Contrat de maintenance pieces et service", styles["TitleBlue"]),
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

    story.append(Paragraph("Informations client", styles["Section"]))
    add_kv_table(
        story,
        [
            ["Client", quote["customer_name"] or "-", "SIRET", quote["customer_siret"] or "-"],
            ["Adresse", quote["customer_address"] or "-", "Code postal", quote["customer_postal_code"] or "-"],
            ["Ville", quote["customer_city"] or "-", "Contact", quote["customer_contact"] or "-"],
            ["Telephone", quote["customer_phone"] or "-", "E-mail", quote["customer_email"] or "-"],
        ],
    )

    story.append(Spacer(1, 8))

    story.append(Paragraph("Informations moteur", styles["Section"]))
    add_kv_table(
        story,
        [
            ["Designation", quote["product_designation"] or "-", "Numero de serie", quote["engine_serial_number"] or "-"],
            ["Produit", quote["product_name"] or "-", "Pays", quote["country"] or "-"],
            ["Devise", currency, "Heures contrat", number(technical_total_hours, " h")],
            ["Heures par an", number(technical_hours_per_year, " h"), "", ""],
        ],
    )

    selling_total = quote["selling_total"] or 0
    total_hours = technical_total_hours
    selling_per_hour = quote["selling_per_hour"]

    if uses_imported_total_hours and total_hours:
        selling_per_hour = (
            selling_total / total_hours
        )
    elif selling_per_hour is None and total_hours:
        selling_per_hour = (
            selling_total / total_hours
        )

    story.append(Paragraph("Synthese de l offre client", styles["Section"]))
    add_kv_table(
        story,
        [
            ["Prix total contrat", money(selling_total, currency), "Prix mensuel", money(quote["selling_monthly"], currency)],
            ["Prix horaire", money(selling_per_hour, currency) + "/h" if selling_per_hour is not None else "-", "Services inclus", str(len(services))],
            ["Heures contrat", number(total_hours, " h"), "Devise", currency],
        ],
    )

    story.append(Paragraph("Cadre du contrat", styles["Section"]))
    contract_info_rows = [
        ["Type de contrat", "Maintenance pieces et service", "Document", "Offre client"],
    ]

    extra_warranty_enabled = (
        bool(quote["extra_warranty_enabled"])
        if "extra_warranty_enabled" in quote.keys()
        else False
    )

    if extra_warranty_enabled:
        contract_info_rows.append(
            ["Garantie supplementaire", "1 an", "Limite fonctionnement", "3000 heures moteur"]
        )

    contract_info_rows.append(
        ["Perimetre", "Selon services inclus ci-dessous", "Validation", "Sous reserve technique"]
    )

    add_kv_table(
        story,
        contract_info_rows,
    )

    if services:
        story.append(Paragraph("Services inclus", styles["Section"]))
        service_data = [["Service"]]
        for service in services:
            service_data.append(
                [
                    translate_service_name_for_client(
                        service["service_name"] or ""
                    ),
                ]
            )

        service_table = Table(service_data, colWidths=[175 * mm], repeatRows=1)
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
    planned_engine_hours_by_id = (
        build_planned_engine_hours_by_intervention(
            quote,
            interventions,
            raw_import=raw_import,
        )
    )

    for intervention in interventions:
        intervention_data.append(
            [
                intervention["intervention_date"] or "",
                (
                    number(
                        exported_engine_hours(
                            intervention,
                            planned_engine_hours_by_id,
                        ),
                        " h",
                    )
                    if exported_engine_hours(
                        intervention,
                        planned_engine_hours_by_id,
                    ) is not None
                    else "-"
                ),
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

    # Detail client des lignes importees :
    # aucune information interne de groupe, reference ou prix.
    if final_lines:
        story.append(
            Paragraph(
                "Détail des éléments inclus",
                styles["Section"],
            )
        )

        client_line_data = [
            ["Description", "Quantité"]
        ]

        for line in final_lines:
            if safe_float(line["quantity"]) == 0:
                continue

            source_description = str(
                line["description"] or ""
            ).strip()

            # Masquer les lignes de repere A, B, C, etc.
            if (
                len(source_description) == 1
                and source_description.upper()
                in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            ):
                continue

            translated_description = (
                translate_service_name_for_client(
                    source_description
                )
            )

            normalized_description = " ".join(
                str(translated_description or "")
                .casefold()
                .replace("’", "'")
                .strip()
                .rstrip(".")
                .split()
            )

            hidden_oil_notice = (
                "huile moteur et filtres à huile : "
                "veuillez consulter les spécifications relatives à l'huile "
                "dans le protocole d'entretien disponible dans l'espace produits"
            )

            if normalized_description == hidden_oil_notice:
                continue

            client_line_data.append(
                [
                    translated_description or "-",
                    number(line["quantity"]),
                ]
            )

        client_line_table = Table(
            client_line_data,
            colWidths=[145 * mm, 25 * mm],
            repeatRows=1,
        )

        client_line_table.setStyle(
            TableStyle(
                [
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, 0),
                        colors.HexColor("#102033"),
                    ),
                    (
                        "TEXTCOLOR",
                        (0, 0),
                        (-1, 0),
                        colors.white,
                    ),
                    (
                        "FONTNAME",
                        (0, 0),
                        (-1, 0),
                        "Helvetica-Bold",
                    ),
                    (
                        "FONTNAME",
                        (0, 1),
                        (-1, -1),
                        "Helvetica",
                    ),
                    (
                        "FONTSIZE",
                        (0, 0),
                        (-1, -1),
                        8,
                    ),
                    (
                        "GRID",
                        (0, 0),
                        (-1, -1),
                        0.3,
                        colors.HexColor("#E5E7EB"),
                    ),
                    (
                        "VALIGN",
                        (0, 0),
                        (-1, -1),
                        "TOP",
                    ),
                    (
                        "ALIGN",
                        (1, 1),
                        (1, -1),
                        "RIGHT",
                    ),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [
                            colors.white,
                            colors.HexColor("#FAFAFA"),
                        ],
                    ),
                    (
                        "TOPPADDING",
                        (0, 0),
                        (-1, -1),
                        4,
                    ),
                    (
                        "BOTTOMPADDING",
                        (0, 0),
                        (-1, -1),
                        4,
                    ),
                ]
            )
        )

        story.append(client_line_table)

    story.append(Spacer(1, 18))
    story.append(Paragraph("Signatures", styles["Section"]))
    signature_table = Table(
        [
            ["Pour le dealer", "Pour le client"],
            ["Date, nom, signature et cachet", "Date, nom, signature et cachet"],
            ["", ""],
        ],
        colWidths=[85 * mm, 85 * mm],
    )
    signature_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#102033")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#9CA3AF")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 2), (-1, 2), 38),
            ]
        )
    )

    story.append(signature_table)
    story.append(Spacer(1, 14))

    if not CGV_BANNER_PATH.exists():
        raise FileNotFoundError(
            f"Bandeau CGV introuvable : {CGV_BANNER_PATH}"
        )

    cgv_banner = Image(str(CGV_BANNER_PATH))
    cgv_banner._restrictSize(125 * mm, 25 * mm)

    banner_table = Table(
        [[cgv_banner]],
        colWidths=[125 * mm],
    )

    banner_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    story.append(banner_table)

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
