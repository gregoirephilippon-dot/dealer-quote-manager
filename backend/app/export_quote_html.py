import sys
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
                <div class="badge">Statut : {status}</div>
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
