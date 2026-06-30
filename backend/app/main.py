from pathlib import Path
import shutil
import subprocess
import sys

from fastapi import FastAPI, File, UploadFile, Form, Request
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from database import get_connection, init_db
from settings import ensure_default_settings, get_settings_dict, set_setting
from service_catalog import SERVICE_CATALOG


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
EXPORT_DIR = DATA_DIR / "exports"
JSON_DIR = DATA_DIR / "examples"

app = FastAPI(title="Dealer Quote Manager")


def run_command(command):
    result = subprocess.run(command, cwd=BASE_DIR, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout


def fmt_money(value, currency="EUR"):
    if value is None:
        return "-"
    return f"{value:,.2f} {currency}".replace(",", " ").replace(".", ",")


def fmt_number(value):
    if value is None:
        return ""
    return str(value)


def layout(title, content):
    return f"""<!doctype html>
<html lang="fr">
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>
        body {{ font-family: Arial, Helvetica, sans-serif; margin: 0; background: #f7f7f4; color: #1f2933; }}
        header {{ background: #102033; color: white; padding: 18px 28px; border-bottom: 4px solid #d8c38a; }}
        header h1 {{ margin: 0; font-size: 24px; }}
        nav {{ margin-top: 10px; }}
        nav a {{ color: white; margin-right: 18px; text-decoration: none; font-weight: bold; }}
        main {{ max-width: 1240px; margin: 28px auto; background: white; border-radius: 14px; padding: 28px; box-shadow: 0 8px 24px rgba(0,0,0,0.08); }}
        h2 {{ margin-top: 0; color: #102033; }}
        h3 {{ color: #102033; margin-top: 24px; }}
        .card {{ border: 1px solid #e5e7eb; border-radius: 12px; padding: 18px; margin-bottom: 18px; background: #fcfcfb; }}
        .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 14px; font-size: 13px; }}
        th {{ background: #102033; color: white; padding: 9px; text-align: left; }}
        td {{ border-bottom: 1px solid #e5e7eb; padding: 7px; vertical-align: top; }}
        tr:nth-child(even) td {{ background: #fafafa; }}
        input[type=file], input[type=number], input[type=text], select {{ padding: 8px; border: 1px solid #d0d5dd; border-radius: 8px; width: 100%; box-sizing: border-box; }}
        input[type=checkbox] {{ transform: scale(1.2); }}
        label {{ display: block; font-size: 13px; color: #344054; margin-bottom: 10px; }}
        button, .button {{ display: inline-block; background: #102033; color: white; border: 0; padding: 10px 14px; border-radius: 8px; text-decoration: none; cursor: pointer; font-weight: bold; margin-right: 6px; }}
        .button.secondary {{ background: #667085; }}
        .button.gold {{ background: #9a7a25; }}
        .button.green {{ background: #087443; }}
        .muted {{ color: #667085; font-size: 13px; }}
        .actions a {{ margin-right: 8px; margin-bottom: 5px; }}
        .warning {{ padding: 12px; background: #fffaeb; border: 1px solid #fedf89; border-radius: 10px; margin-bottom: 16px; }}
        .error {{ padding: 12px; background: #fef3f2; border: 1px solid #fecdca; border-radius: 10px; margin-bottom: 16px; white-space: pre-wrap; }}
        .legend span {{ display: inline-block; padding: 6px 10px; border-radius: 8px; margin-right: 8px; margin-bottom: 8px; font-size: 13px; }}
        .greenbox {{ background: #00b050; color: white; }}
        .bluebox {{ background: #00b0f0; color: white; }}
        .yellowbox {{ background: #ffc000; color: #111827; }}
        .greybox {{ background: #d0d0d0; color: #111827; }}
        .small-input {{ width: 90px !important; }}
        .wide-input {{ width: 180px !important; }}
    </style>
</head>
<body>
<header>
    <h1>Dealer Quote Manager</h1>
    <nav>
        <a href="/">Historique</a>
        <a href="/import">Importer Excel</a>
        <a href="/settings">Paramètres dealer</a>
        <a href="/instructions">Instructions constructeur</a>
    </nav>
</header>
<main>{content}</main>
</body>
</html>"""


def ensure_quote_services(quote_id):
    init_db()
    with get_connection() as conn:
        for item in SERVICE_CATALOG:
            conn.execute(
                """
                INSERT OR IGNORE INTO quote_services (
                    quote_id,
                    service_id,
                    service_group,
                    service_name,
                    source_excel,
                    included,
                    work_time_hours,
                    quantity,
                    unit_price,
                    fixed_price,
                    extra_travel,
                    calculated_price,
                    notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    quote_id,
                    item["id"],
                    item["group"],
                    item["name"],
                    item["source"],
                    0,
                    item["default_time"],
                    item["default_qty"],
                    item["default_unit"],
                    item["default_fixed"],
                    item["travel"],
                    0,
                    "",
                ),
            )
        conn.commit()


@app.get("/", response_class=HTMLResponse)
def home():
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, status, customer_name, product_designation, engine_serial_number,
                   currency, total_cost, selling_total, selling_monthly, selling_per_hour
            FROM quotes
            ORDER BY id DESC
            """
        ).fetchall()

    rows_html = ""
    for row in rows:
        currency = row["currency"] or "EUR"
        quote_id = row["id"]
        pdf_path = EXPORT_DIR / f"quote_{quote_id}.pdf"
        html_path = EXPORT_DIR / f"quote_{quote_id}.html"
        pdf_link = f'<a class="button gold" href="/exports/quote_{quote_id}.pdf" target="_blank">PDF</a>' if pdf_path.exists() else ""
        html_link = f'<a class="button secondary" href="/exports/quote_{quote_id}.html" target="_blank">HTML</a>' if html_path.exists() else ""

        rows_html += f"""
        <tr>
            <td>{quote_id}</td><td>{row['created_at']}</td><td>{row['status']}</td>
            <td>{row['customer_name'] or '-'}</td><td>{row['product_designation'] or '-'}</td>
            <td>{row['engine_serial_number'] or '-'}</td><td>{fmt_money(row['total_cost'], currency)}</td>
            <td><strong>{fmt_money(row['selling_total'], currency)}</strong></td>
            <td>{fmt_money(row['selling_monthly'], currency)}</td><td>{fmt_money(row['selling_per_hour'], currency)}/h</td>
            <td class="actions">
                <a class="button green" href="/quote/{quote_id}/inputs">Inputs</a>
                <a class="button" href="/quote/{quote_id}/services">Services & temps</a>
                <a class="button secondary" href="/quote/{quote_id}/export">Exporter</a>
                {html_link}{pdf_link}
            </td>
        </tr>"""

    if not rows_html:
        rows_html = '<tr><td colspan="11">Aucun devis pour le moment. Commence par importer un fichier Excel.</td></tr>'

    content = f"""
    <h2>Historique des devis</h2>
    <div class="card">
        <a class="button" href="/import">Importer un nouveau fichier Excel</a>
        <a class="button secondary" href="/instructions">Voir les instructions constructeur</a>
        
    </div>
    <table>
        <thead><tr><th>ID</th><th>Date</th><th>Statut</th><th>Client</th><th>Moteur</th><th>Serial</th><th>Coût brut</th><th>Prix client</th><th>Mensuel</th><th>€/h</th><th>Actions</th></tr></thead>
        <tbody>{rows_html}</tbody>
    </table>"""
    return layout("Historique", content)


@app.get("/instructions", response_class=HTMLResponse)
def instructions_page():
    service_rows = ""
    for item in SERVICE_CATALOG:
        service_rows += f"<tr><td>{item['id']}</td><td>{item['group']}</td><td>{item['name']}</td><td>{item['source']}</td></tr>"

    content = f"""
    <h2>Instructions constructeur</h2>
    
    <h3>Code couleur du classeur</h3>
    <div class="card legend">
        <span class="greybox">Information / nom</span>
        <span class="greenbox">Cellules à remplir</span>
        <span class="bluebox">Données récupérées</span>
        <span class="yellowbox">Formules</span>
    </div>
    <h3>Flux constructeur</h3>
    <div class="card">
        <ol>
            <li>Service Calculator / Product Center en anglais.</li>
            <li>Copie de l’export dans Service Calculation.</li>
            <li>Run Service Calculation.</li>
            <li>Public Master Data : moteur, contrat, heures, dates, limites.</li>
            <li>Internal Master Data : labour, travel, discounts, fees, inputs services.</li>
            <li>Quote Configuration : package et services inclus.</li>
            <li>Overview / Summary Services : prix final.</li>
        </ol>
    </div>
    <h3>Services configurables</h3>
    <table>
        <thead><tr><th>ID</th><th>Groupe</th><th>Service</th><th>Source Excel vérifiée</th></tr></thead>
        <tbody>{service_rows}</tbody>
    </table>
    """
    return layout("Instructions", content)


@app.get("/import", response_class=HTMLResponse)
def import_page():
    content = """
    <h2>Importer un fichier ServiceCalculationExport.xlsx</h2>
    <div class="card">
        <form action="/import" method="post" enctype="multipart/form-data">
            <p><input type="file" name="file" accept=".xlsx,.xlsm" required></p>
            <button type="submit">Importer et générer le devis</button>
        </form>
        
    </div>"""
    return layout("Importer", content)


@app.post("/import", response_class=HTMLResponse)
def import_file(file: UploadFile = File(...)):
    try:
        init_db()
        ensure_default_settings()
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        JSON_DIR.mkdir(parents=True, exist_ok=True)
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)

        safe_name = Path(file.filename).name
        upload_path = UPLOAD_DIR / safe_name
        with upload_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        json_path = JSON_DIR / "service_calculation_summary.json"

        run_command([sys.executable, "backend/app/importers/service_calculation_importer.py", str(upload_path), "--out", str(json_path), "--pretty"])
        create_output = run_command([sys.executable, "backend/app/create_quote_from_import.py", str(json_path)])

        quote_id = None
        for line in create_output.splitlines():
            if line.strip().startswith("Devis brouillon cree : ID"):
                quote_id = int(line.split("ID", 1)[1].strip())

        if quote_id is None:
            raise RuntimeError("Impossible de retrouver l'ID du devis cree.")

        ensure_quote_services(quote_id)
        run_command([sys.executable, "backend/app/apply_pricing.py", str(quote_id)])
        run_command([sys.executable, "backend/app/export_quote_html.py", str(quote_id)])
        run_command([sys.executable, "backend/app/export_quote_pdf.py", str(quote_id)])

        return RedirectResponse(url=f"/quote/{quote_id}/inputs", status_code=303)

    except Exception as exc:
        return layout("Erreur import", f"<h2>Erreur import</h2><div class='error'>{str(exc)}</div><a class='button' href='/import'>Retour import</a>")


@app.get("/quote/{quote_id}/inputs", response_class=HTMLResponse)
def quote_inputs_page(quote_id: int):
    init_db()
    ensure_quote_services(quote_id)
    with get_connection() as conn:
        quote = conn.execute("SELECT * FROM quotes WHERE id = ?", (quote_id,)).fetchone()

    if quote is None:
        return HTMLResponse(layout("Introuvable", f"<div class='error'>Devis introuvable : {quote_id}</div>"), status_code=404)

    contract_years = ""
    if quote["total_hours"] and quote["hours_per_year"]:
        contract_years = quote["total_hours"] / quote["hours_per_year"]

    content = f"""
    <h2>Inputs devis ID {quote_id}</h2>
    
    <form action="/quote/{quote_id}/inputs" method="post">
        <h3>Public Master Data — Client & moteur</h3>
        <div class="card grid">
            <label>Customer name<input type="text" name="customer_name" value="{quote['customer_name'] or ''}"></label>
            <label>Product designation<input type="text" name="product_designation" value="{quote['product_designation'] or ''}"></label>
            <label>Serial number<input type="text" name="engine_serial_number" value="{quote['engine_serial_number'] or ''}"></label>
            <label>Product name<input type="text" name="product_name" value="{quote['product_name'] or ''}"></label>
            <label>Country<input type="text" name="country" value="{quote['country'] or ''}"></label>
            <label>Statut<select name="status">
                <option value="draft" {'selected' if quote['status'] == 'draft' else ''}>draft</option>
                <option value="sent" {'selected' if quote['status'] == 'sent' else ''}>sent</option>
                <option value="accepted" {'selected' if quote['status'] == 'accepted' else ''}>accepted</option>
                <option value="refused" {'selected' if quote['status'] == 'refused' else ''}>refused</option>
            </select></label>
        </div>
        <h3>Contrat & coûts importés</h3>
        <div class="card grid">
            <label>Contract length calculée<input type="number" step="0.01" value="{fmt_number(contract_years)}" disabled></label>
            <label>Total calculation hours<input type="number" step="0.01" name="total_hours" value="{fmt_number(quote['total_hours'])}"></label>
            <label>Op hours per year<input type="number" step="0.01" name="hours_per_year" value="{fmt_number(quote['hours_per_year'])}"></label>
            <label>Labour rate input<input type="number" step="0.01" name="labour_rate" value="{fmt_number(quote['labour_rate'])}"></label>
            <label>Total parts cost<input type="number" step="0.01" name="total_parts" value="{fmt_number(quote['total_parts'])}"></label>
            <label>Total labour cost<input type="number" step="0.01" name="total_labour" value="{fmt_number(quote['total_labour'])}"></label>
            <label>Total misc cost<input type="number" step="0.01" name="total_misc" value="{fmt_number(quote['total_misc'])}"></label>
            <label>Currency<input type="text" name="currency" value="{quote['currency'] or 'EUR'}"></label>
        </div>
        <button type="submit">Enregistrer inputs + recalculer</button>
        <a class="button" href="/quote/{quote_id}/services">Services & temps</a>
        <a class="button secondary" href="/">Retour historique</a>
    </form>"""
    return layout("Inputs devis", content)


@app.post("/quote/{quote_id}/inputs")
def save_quote_inputs(
    quote_id: int,
    customer_name: str = Form(""),
    product_designation: str = Form(""),
    engine_serial_number: str = Form(""),
    product_name: str = Form(""),
    country: str = Form(""),
    status: str = Form("draft"),
    total_hours: float = Form(0),
    hours_per_year: float = Form(0),
    labour_rate: float = Form(0),
    total_parts: float = Form(0),
    total_labour: float = Form(0),
    total_misc: float = Form(0),
    currency: str = Form("EUR"),
):
    init_db()
    total_cost = (total_parts or 0) + (total_labour or 0) + (total_misc or 0)
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE quotes
            SET customer_name=?, product_designation=?, engine_serial_number=?, product_name=?, country=?, status=?,
                total_hours=?, hours_per_year=?, labour_rate=?, total_parts=?, total_labour=?, total_misc=?, total_cost=?, currency=?
            WHERE id=?
            """,
            (customer_name.strip(), product_designation.strip(), engine_serial_number.strip(), product_name.strip(), country.strip(), status,
             total_hours, hours_per_year, labour_rate, total_parts, total_labour, total_misc, total_cost, currency.strip() or "EUR", quote_id),
        )
        conn.commit()

    regenerate_quote(quote_id)
    return RedirectResponse(url=f"/quote/{quote_id}/inputs", status_code=303)


@app.get("/quote/{quote_id}/services", response_class=HTMLResponse)
def quote_services_page(quote_id: int):
    init_db()
    ensure_quote_services(quote_id)

    with get_connection() as conn:
        quote = conn.execute("SELECT * FROM quotes WHERE id = ?", (quote_id,)).fetchone()
        services = conn.execute("SELECT * FROM quote_services WHERE quote_id = ? ORDER BY service_id", (quote_id,)).fetchall()

    if quote is None:
        return HTMLResponse(layout("Introuvable", f"<div class='error'>Devis introuvable : {quote_id}</div>"), status_code=404)

    currency = quote["currency"] or "EUR"

    rows = ""
    for s in services:
        checked = "checked" if s["included"] else ""
        yes_selected = "selected" if str(s["extra_travel"]).lower() == "yes" else ""
        excl_selected = "selected" if str(s["extra_travel"]).lower() != "yes" else ""
        rows += f"""
        <tr>
            <td><input type="checkbox" name="included_{s['id']}" {checked}></td>
            <td><strong>{s['service_id']}</strong><br><span class="muted">{s['source_excel'] or ''}</span></td>
            <td>{s['service_group']}</td>
            <td>{s['service_name']}</td>
            <td><input class="small-input" type="number" step="0.01" name="time_{s['id']}" value="{fmt_number(s['work_time_hours'])}"></td>
            <td><input class="small-input" type="number" step="0.01" name="qty_{s['id']}" value="{fmt_number(s['quantity'])}"></td>
            <td><input class="small-input" type="number" step="0.01" name="unit_{s['id']}" value="{fmt_number(s['unit_price'])}"></td>
            <td><input class="small-input" type="number" step="0.01" name="fixed_{s['id']}" value="{fmt_number(s['fixed_price'])}"></td>
            <td><select class="wide-input" name="travel_{s['id']}"><option value="Exclude" {excl_selected}>Exclude</option><option value="Yes" {yes_selected}>Yes</option></select></td>
            <td>{fmt_money(s['calculated_price'], currency)}</td>
        </tr>"""

    content = f"""
    <h2>Services & temps — Devis ID {quote_id}</h2>
    
    <form action="/quote/{quote_id}/services" method="post">
        <table>
            <thead>
                <tr>
                    <th>Inclure</th><th>ID / source</th><th>Groupe</th><th>Service</th>
                    <th>Temps h</th><th>Qté</th><th>Prix unit.</th><th>Prix fixe</th><th>Extra travel</th><th>Calculé</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
        <br>
        <button type="submit">Enregistrer services + recalculer</button>
        <a class="button secondary" href="/quote/{quote_id}/inputs">Retour inputs</a>
        <a class="button secondary" href="/">Historique</a>
    </form>"""
    return layout("Services & temps", content)


@app.post("/quote/{quote_id}/services")
async def save_quote_services(quote_id: int, request: Request):
    init_db()
    ensure_quote_services(quote_id)
    form = await request.form()

    with get_connection() as conn:
        services = conn.execute("SELECT * FROM quote_services WHERE quote_id = ?", (quote_id,)).fetchall()
        for s in services:
            row_id = s["id"]
            service_id = s["service_id"]
            included = 1 if f"included_{row_id}" in form else 0

            def get_float(prefix, default=0):
                raw = form.get(f"{prefix}_{row_id}", default)
                try:
                    return float(raw or 0)
                except ValueError:
                    return default

            work_time = get_float("time")
            qty = get_float("qty")
            unit = get_float("unit")
            fixed = get_float("fixed")
            travel = form.get(f"travel_{row_id}", "Exclude")

            conn.execute(
                """
                UPDATE quote_services
                SET included=?, work_time_hours=?, quantity=?, unit_price=?, fixed_price=?, extra_travel=?
                WHERE id=?
                """,
                (included, work_time, qty, unit, fixed, travel, row_id),
            )

        conn.commit()

    regenerate_quote(quote_id)
    return RedirectResponse(url=f"/quote/{quote_id}/services", status_code=303)


def regenerate_quote(quote_id):
    run_command([sys.executable, "backend/app/apply_pricing.py", str(quote_id)])
    run_command([sys.executable, "backend/app/export_quote_html.py", str(quote_id)])
    run_command([sys.executable, "backend/app/export_quote_pdf.py", str(quote_id)])


@app.get("/settings", response_class=HTMLResponse)
def settings_page():
    ensure_default_settings()
    settings = get_settings_dict()
    fields = [
        ("parts_margin_percent", "Marge pièces (%)"),
        ("labour_margin_percent", "Marge main d'œuvre (%)"),
        ("admin_fee_percent", "Frais administratifs (%)"),
        ("logistics_fee_percent", "Frais logistiques (%)"),
        ("travel_fee_fixed", "Frais déplacement fixes"),
        ("indexation_percent", "Indexation (%)"),
    ]
    inputs = ""
    for key, label in fields:
        inputs += f'<p><label><strong>{label}</strong><br><input type="number" step="0.01" name="{key}" value="{settings.get(key, 0)}"></label></p>'

    content = f"<h2>Paramètres dealer</h2><div class='card'><form action='/settings' method='post'>{inputs}<button type='submit'>Enregistrer</button></form></div>"
    return layout("Paramètres", content)


@app.post("/settings")
def save_settings(
    parts_margin_percent: float = Form(...),
    labour_margin_percent: float = Form(...),
    admin_fee_percent: float = Form(...),
    logistics_fee_percent: float = Form(...),
    travel_fee_fixed: float = Form(...),
    indexation_percent: float = Form(...),
):
    ensure_default_settings()
    set_setting("parts_margin_percent", parts_margin_percent)
    set_setting("labour_margin_percent", labour_margin_percent)
    set_setting("admin_fee_percent", admin_fee_percent)
    set_setting("logistics_fee_percent", logistics_fee_percent)
    set_setting("travel_fee_fixed", travel_fee_fixed)
    set_setting("indexation_percent", indexation_percent)
    return RedirectResponse(url="/settings", status_code=303)


@app.get("/quote/{quote_id}/export")
def export_quote(quote_id: int):
    regenerate_quote(quote_id)
    return RedirectResponse(url="/", status_code=303)


@app.get("/exports/{filename}")
def get_export(filename: str):
    path = EXPORT_DIR / filename
    if not path.exists():
        return HTMLResponse(layout("Introuvable", f"<div class='error'>Fichier introuvable : {filename}</div>"), status_code=404)
    return FileResponse(path)


if __name__ == "__main__":
    import uvicorn
    init_db()
    ensure_default_settings()
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/exports-static", StaticFiles(directory=str(EXPORT_DIR)), name="exports-static")
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
