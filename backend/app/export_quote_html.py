import sys
import base64
import mimetypes
from pathlib import Path
from html import escape

from database import get_connection, init_db


BASE_DIR = Path(__file__).resolve().parents[2]
EXPORT_DIR = BASE_DIR / "data" / "exports"


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
        "logo_data_uri": None,
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

    logo_data_uri = None
    logo_filename = company["logo_filename"]
    if logo_filename:
        logo_path = LOGO_DIR / logo_filename
        if logo_path.exists():
            mime_type, _ = mimetypes.guess_type(str(logo_path))
            mime_type = mime_type or "image/png"
            encoded = base64.b64encode(logo_path.read_bytes()).decode("ascii")
            logo_data_uri = f"data:{mime_type};base64,{encoded}"

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
        "logo_data_uri": logo_data_uri,
    }


def render_company_identity_html(quote):
    branding = get_company_branding(quote)

    display_name = branding.get("display_name") or branding.get("company_name") or "Société"
    legal_name = branding.get("legal_name")
    logo_data_uri = branding.get("logo_data_uri")

    parts = ['<div class="company-identity">']

    if logo_data_uri:
        parts.append(f'<img class="company-logo" src="{logo_data_uri}" alt="Logo société">')
    else:
        parts.append(f'<div class="company-logo-fallback">{escape(str(display_name))}</div>')

    lines = []

    if legal_name and legal_name != display_name:
        lines.append(f"<strong>{escape(str(legal_name))}</strong>")
    else:
        lines.append(f"<strong>{escape(str(display_name))}</strong>")

    for key in ["address_line1", "address_line2"]:
        value = branding.get(key)
        if value:
            lines.append(escape(str(value)))

    postal_city = " ".join(
        str(v) for v in [branding.get("postal_code"), branding.get("city")]
        if v
    ).strip()
    if postal_city:
        lines.append(escape(postal_city))

    if branding.get("country"):
        lines.append(escape(str(branding["country"])))

    contacts = []
    if branding.get("phone"):
        contacts.append(f"Tél. {escape(str(branding['phone']))}")
    if branding.get("email"):
        contacts.append(escape(str(branding["email"])))
    if contacts:
        lines.append(" - ".join(contacts))

    if branding.get("website"):
        lines.append(escape(str(branding["website"])))

    legal = []
    if branding.get("siret"):
        legal.append(f"SIRET : {escape(str(branding['siret']))}")
    if branding.get("vat_number"):
        legal.append(f"TVA : {escape(str(branding['vat_number']))}")
    if legal:
        lines.append(" - ".join(legal))

    parts.append('<div class="company-lines">' + "<br>".join(lines) + "</div>")
    parts.append("</div>")

    return "\\n".join(parts)


def get_quote(quote_id: int):
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
            return None, [], []

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

    return quote, lines, interventions


def render_quote_html(quote, lines, interventions):
    currency = quote["currency"] or "EUR"

    product_designation = escape(str(quote["product_designation"] or ""))
    serial = escape(str(quote["engine_serial_number"] or ""))
    status = escape(str(quote["status"] or ""))
    created_at = escape(str(quote["created_at"] or ""))

    selling_total = quote["selling_total"] or 0
    total_hours = quote["total_hours"] or 0
    selling_per_hour = quote["selling_per_hour"]
    if selling_per_hour is None and total_hours:
        selling_per_hour = selling_total / total_hours

    intervention_rows = ""
    for intervention in interventions:
        intervention_rows += f"""
        <tr>
            <td>{escape(str(intervention["intervention_date"] or ""))}</td>
            <td>{number(intervention["engine_hours"], " h")}</td>
        </tr>
        """

    if not intervention_rows:
        intervention_rows = """
        <tr>
            <td colspan="2">Aucune intervention importee.</td>
        </tr>
        """

    html = f"""<!doctype html>
<html lang="fr">
<head>
    <meta charset="utf-8">
    <title>Offre contrat service - ID {quote['id']}</title>
    <style>
        body {{
            font-family: Arial, Helvetica, sans-serif;
            margin: 32px;
            color: #1f2933;
            background: #f7f7f4;
        }}
        .page {{
            max-width: 1000px;
            margin: 0 auto;
            background: white;
            padding: 32px;
            border-radius: 14px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.08);
        }}

        .company-identity {{
            min-width: 240px;
            max-width: 320px;
            text-align: right;
            font-size: 12px;
            line-height: 1.35;
            color: #374151;
            margin-bottom: 10px;
        }}
        .company-logo {{
            max-width: 180px;
            max-height: 70px;
            object-fit: contain;
            margin-bottom: 8px;
        }}
        .company-logo-fallback {{
            font-weight: bold;
            color: #102033;
            font-size: 18px;
            margin-bottom: 8px;
        }}
        .company-lines strong {{
            color: #102033;
            font-size: 13px;
        }}

        .header {{
            display: flex;
            justify-content: space-between;
            gap: 24px;
            border-bottom: 2px solid #d8c38a;
            padding-bottom: 18px;
            margin-bottom: 24px;
        }}
        h1 {{
            margin: 0;
            color: #102033;
            font-size: 28px;
        }}
        h2 {{
            margin-top: 32px;
            color: #102033;
            font-size: 20px;
            border-bottom: 1px solid #e5e7eb;
            padding-bottom: 8px;
        }}
        .muted {{
            color: #667085;
            font-size: 14px;
        }}
        .badge {{
            display: inline-block;
            padding: 6px 10px;
            border-radius: 999px;
            background: #eef2ff;
            color: #1e3a8a;
            font-weight: bold;
            font-size: 13px;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 14px;
            margin: 20px 0;
        }}
        .card {{
            border: 1px solid #e5e7eb;
            border-radius: 12px;
            padding: 14px;
            background: #fcfcfb;
        }}
        .label {{
            font-size: 12px;
            color: #667085;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }}
        .value {{
            font-size: 18px;
            font-weight: bold;
            margin-top: 6px;
        }}
        .total {{
            font-size: 24px;
            color: #102033;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 12px;
            font-size: 13px;
        }}
        th {{
            background: #102033;
            color: white;
            text-align: left;
            padding: 9px;
        }}
        td {{
            border-bottom: 1px solid #e5e7eb;
            padding: 8px;
            vertical-align: top;
        }}
        tr:nth-child(even) td {{
            background: #fafafa;
        }}
        .footer {{
            margin-top: 34px;
            padding-top: 16px;
            border-top: 1px solid #e5e7eb;
            color: #667085;
            font-size: 12px;
        }}
        @media print {{
            body {{
                background: white;
                margin: 0;
            }}
            .page {{
                box-shadow: none;
                border-radius: 0;
            }}
        }}
    </style>
</head>
<body>
    <div class="page">
        <div class="header">
            <div>
                <h1>Offre contrat service</h1>
                <div class="muted">Offre client generee par Dealer Quote Manager</div>
            </div>
            <div>
                {render_company_identity_html(quote)}
                <div class="badge" style="margin-top: 10px;">Statut : {status}</div>
                <div class="muted" style="margin-top: 8px;">Offre ID {quote['id']} - {created_at}</div>
            </div>
        </div>

        <h2>Informations moteur</h2>
        <div class="grid">
            <div class="card">
                <div class="label">Designation</div>
                <div class="value">{product_designation}</div>
            </div>
            <div class="card">
                <div class="label">Numero de serie</div>
                <div class="value">{serial}</div>
            </div>
            <div class="card">
                <div class="label">Produit</div>
                <div class="value">{escape(str(quote["product_name"] or "-"))}</div>
            </div>
            <div class="card">
                <div class="label">Pays</div>
                <div class="value">{escape(str(quote["country"] or "-"))}</div>
            </div>
        </div>

        <h2>Synthese de l offre client</h2>
        <div class="grid">
            <div class="card">
                <div class="label">Prix total contrat</div>
                <div class="value total">{money(selling_total, currency)}</div>
            </div>
            <div class="card">
                <div class="label">Prix mensuel</div>
                <div class="value">{money(quote["selling_monthly"], currency)}</div>
            </div>
            <div class="card">
                <div class="label">Prix horaire</div>
                <div class="value">{money(selling_per_hour, currency)}/h</div>
            </div>
            <div class="card">
                <div class="label">Heures contrat</div>
                <div class="value">{number(total_hours, " h")}</div>
            </div>
        </div>

        <h2>Planning des interventions</h2>
        <table>
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Heures moteur</th>
                </tr>
            </thead>
            <tbody>
                {intervention_rows}
            </tbody>
        </table>

        <h2>Conditions et remarques</h2>
        <p class="muted">Offre etablie sous reserve de validation technique, disponibilite des pieces et conditions contractuelles applicables.</p>

        <div class="footer">
            Offre client generee automatiquement par Dealer Quote Manager.
        </div>
    </div>
</body>
</html>
"""
    return html


def export_quote_html(quote_id: int):
    quote, lines, interventions = get_quote(quote_id)

    if quote is None:
        print(f"Devis introuvable : ID {quote_id}")
        return None

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = EXPORT_DIR / f"quote_{quote_id}.html"

    html = render_quote_html(quote, lines, interventions)
    output_path.write_text(html, encoding="utf-8")

    print(f"Export HTML cree : {output_path}")
    print(f"Devis ID {quote_id}")
    print(f"Moteur : {quote['product_designation']} / SN {quote['engine_serial_number']}")
    print(f"Prix client : {money(quote['selling_total'], quote['currency'] or 'EUR')}")

    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage : python backend/app/export_quote_html.py 1")
        raise SystemExit(1)

    export_quote_html(int(sys.argv[1]))
