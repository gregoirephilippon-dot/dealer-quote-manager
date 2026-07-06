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
    """
    Compatible Python normal + PyInstaller EXE.

    En version EXE, sys.executable pointe vers Dealer Quote Manager.exe.
    Relancer sys.executable relance donc tout le serveur et bloque le port 8000.
    On exécute donc les scripts Python directement dans le même processus avec runpy.
    """
    import contextlib
    import io
    import runpy
    import sys as _sys
    import traceback

    if command and str(command[0]) == str(_sys.executable) and len(command) >= 2:
        script_arg = str(command[1]).replace("\\", "/")
        script_path = BASE_DIR / script_arg

        if not script_path.exists():
            script_path = Path(script_arg)

        if script_path.exists():
            old_argv = _sys.argv[:]
            stdout_buffer = io.StringIO()
            stderr_buffer = io.StringIO()

            try:
                _sys.argv = [str(script_path)] + [str(x) for x in command[2:]]

                with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
                    try:
                        runpy.run_path(str(script_path), run_name="__main__")
                    except SystemExit as exc:
                        code = exc.code
                        if code not in (None, 0):
                            raise RuntimeError(stderr_buffer.getvalue() or stdout_buffer.getvalue() or f"Erreur script {script_path} : {code}")

                return stdout_buffer.getvalue()

            except Exception:
                error_text = stderr_buffer.getvalue() or stdout_buffer.getvalue() or traceback.format_exc()
                raise RuntimeError(error_text)

            finally:
                _sys.argv = old_argv

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
        <a href="/dealer-discounts">Remise dealer</a>
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
        
    </div>
    <table>
        <thead><tr><th>ID</th><th>Date</th><th>Statut</th><th>Client</th><th>Moteur</th><th>Serial</th><th>Coût brut</th><th>Prix client</th><th>Mensuel</th><th>€/h</th><th>Actions</th></tr></thead>
        <tbody>{rows_html}</tbody>
    </table>"""
    return layout("Historique", content)


def instructions_page():
    service_rows = ""
    for item in SERVICE_CATALOG:
        service_rows += f"<tr><td>{item['id']}</td><td>{item['group']}</td><td>{item['name']}</td><td>{item['source']}</td></tr>"

    content = f"""
    <h2>Remise dealer</h2>
    
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

        # Remonte le total de l'onglet Overview colonne C dans le service 2.2.
        # Compatible EXE : ne relance pas l'application, met à jour la base directement.
        try:
            from overview_total_sync import apply_overview_total_to_service_2_2
            overview_totals = apply_overview_total_to_service_2_2(quote_id, upload_path)
            print(f"Overview C -> service 2.2 : {overview_totals}")
        except Exception as exc:
            print(f"Attention : impossible de remonter Overview C vers 2.2 : {exc}")

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



# --- Permanent package routes - added by install_packages_permanent.py ---
from fastapi.responses import HTMLResponse as _PkgHTMLResponse, RedirectResponse as _PkgRedirectResponse
from package_model import (
    apply_package_to_quote as _pkg_apply_package_to_quote,
    ensure_package_schema as _pkg_ensure_package_schema,
    get_package_status as _pkg_get_package_status,
)


def _pkg_panel_html(quote_id: int):
    _pkg_ensure_package_schema()
    current_key, current_name, packages = _pkg_get_package_status(quote_id)

    buttons = []
    for package in packages:
        active_class = "active" if package["active"] else ""
        active_label = " ✓" if package["active"] else ""
        buttons.append(f"""
            <a class="pkg-button {active_class}" href="/quote/{quote_id}/package/apply/{package['key']}">
                <span>{package['label']}{active_label}</span>
                <small>{package['matching']}/{package['total']} services</small>
            </a>
        """)

    current = current_name or "Non défini"

    return f"""
    <div class="pkg-panel">
        <div class="pkg-title">
            <b>Package devis</b>
            <span>Actuel : {current}</span>
        </div>
        <div class="pkg-buttons">
            {''.join(buttons)}
        </div>
        <div class="pkg-help">
            Basic, Base Care, Comfort Care et Advanced Care sont permanents.
            Le choix modifie les services inclus/exclus puis recalcule le devis.
        </div>
    </div>
    <style>
        .pkg-panel {{
            background: #fffaf0;
            border: 1px solid #d9c98b;
            border-radius: 14px;
            padding: 14px;
            margin: 14px 0 18px 0;
            box-shadow: 0 5px 18px rgba(16, 32, 51, 0.08);
            font-family: Arial, sans-serif;
        }}
        .pkg-title {{
            display: flex;
            justify-content: space-between;
            gap: 12px;
            color: #102033;
            margin-bottom: 10px;
        }}
        .pkg-title span {{
            color: #697386;
            font-size: 13px;
        }}
        .pkg-buttons {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
            gap: 10px;
        }}
        .pkg-button {{
            display: flex;
            flex-direction: column;
            gap: 3px;
            background: #ffffff;
            border: 1px solid #e1d5a3;
            color: #102033;
            border-radius: 11px;
            padding: 10px 12px;
            text-decoration: none;
            font-weight: 700;
        }}
        .pkg-button small {{
            color: #697386;
            font-weight: 400;
        }}
        .pkg-button.active {{
            background: #102033;
            color: white;
            border-color: #102033;
        }}
        .pkg-button.active small {{
            color: #e9dfbd;
        }}
        .pkg-help {{
            margin-top: 10px;
            font-size: 12px;
            color: #697386;
        }}
    </style>
    """


@app.get("/quote/{quote_id}/package/apply/{package_key}")
def quote_package_apply_permanent(quote_id: int, package_key: str):
    _pkg_apply_package_to_quote(quote_id, package_key)
    return _PkgRedirectResponse(url=f"/quote/{quote_id}/services", status_code=303)


@app.get("/quote/{quote_id}/packages", response_class=_PkgHTMLResponse)
def quote_packages_permanent_page(quote_id: int):
    current_key, current_name, packages = _pkg_get_package_status(quote_id)

    cards = []
    for package in packages:
        active = "active" if package["active"] else ""
        cards.append(f"""
        <div class="card {active}">
            <h2>{package['label']}</h2>
            <p>{package['description']}</p>
            <div class="small">{package['matching']}/{package['total']} services inclus actuellement</div>
            <div class="service-list">{', '.join(package['services'])}</div>
            <a class="btn" href="/quote/{quote_id}/package/apply/{package['key']}">Choisir {package['label']}</a>
        </div>
        """)

    return f"""
    <!doctype html>
    <html lang="fr">
    <head>
        <meta charset="utf-8">
        <title>Packages - Devis {quote_id}</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 28px; background: #f6f3ea; color: #172033; }}
            a {{ color: #172033; font-weight: 700; }}
            .top {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 22px; }}
            .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; }}
            .card {{ background: white; border: 1px solid #d9c98b; border-radius: 14px; padding: 18px; box-shadow: 0 5px 16px rgba(0,0,0,0.06); }}
            .card.active {{ border: 3px solid #102033; }}
            h1 {{ margin: 0; }}
            h2 {{ margin-top: 0; }}
            .btn {{ display: inline-block; margin-top: 12px; padding: 10px 14px; border-radius: 10px; background: #102033; color: white; text-decoration: none; }}
            .small {{ color: #697386; font-size: 13px; margin-top: 8px; }}
            .service-list {{ color: #697386; font-size: 12px; margin-top: 10px; line-height: 1.4; }}
        </style>
    </head>
    <body>
        <div class="top">
            <h1>Packages permanents - Devis {quote_id}</h1>
            <div><a href="/quote/{quote_id}/services">Services & temps</a> | <a href="/">Accueil</a></div>
        </div>
        <p>Package actuel : <b>{current_name or 'Non défini'}</b></p>
        <div class="grid">{''.join(cards)}</div>
    </body>
    </html>
    """


@app.middleware("http")
async def _pkg_inject_panel_middleware(request, call_next):
    response = await call_next(request)

    path = request.url.path
    if response.status_code != 200:
        return response

    if not (path.endswith("/services") and path.startswith("/quote/")):
        return response

    try:
        quote_id = int(path.strip("/").split("/")[1])
    except Exception:
        return response

    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type:
        return response

    body = b""
    async for chunk in response.body_iterator:
        body += chunk

    try:
        html = body.decode("utf-8")
    except Exception:
        return response

    panel = _pkg_panel_html(quote_id)

    if "<body>" in html:
        html = html.replace("<body>", "<body>" + panel, 1)
    elif "<body " in html:
        idx = html.find(">", html.find("<body "))
        if idx != -1:
            html = html[:idx + 1] + panel + html[idx + 1:]
        else:
            html = panel + html
    else:
        html = panel + html

    headers = dict(response.headers)
    headers.pop("content-length", None)

    return _PkgHTMLResponse(content=html, status_code=response.status_code, headers=headers)
# --- End permanent package routes ---



# --- Shutdown route - added by install_shutdown_button.py ---
import os as _shutdown_os
import threading as _shutdown_threading
import time as _shutdown_time

from fastapi.responses import HTMLResponse as _ShutdownHTMLResponse


def _shutdown_button_html():
    return """
    <div class="shutdown-bar">
        <a class="shutdown-btn" href="/shutdown/confirm">Quitter le logiciel</a>
    </div>
    <style>
        .shutdown-bar {
            position: fixed;
            right: 18px;
            bottom: 18px;
            z-index: 99999;
            font-family: Arial, sans-serif;
        }
        .shutdown-btn {
            display: inline-block;
            padding: 10px 14px;
            border-radius: 999px;
            background: #7a1f1f;
            color: white !important;
            text-decoration: none;
            font-size: 13px;
            font-weight: 700;
            box-shadow: 0 6px 18px rgba(0,0,0,0.22);
        }
        .shutdown-btn:hover {
            background: #9f2525;
        }
    </style>
    """


def _shutdown_process_soon():
    def _stop():
        _shutdown_time.sleep(0.8)
        _shutdown_os._exit(0)

    _shutdown_threading.Thread(target=_stop, daemon=True).start()


@app.get("/shutdown/confirm", response_class=_ShutdownHTMLResponse)
def shutdown_confirm_page():
    return """
    <!doctype html>
    <html lang="fr">
    <head>
        <meta charset="utf-8">
        <title>Quitter Dealer Quote Manager</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background: #f6f3ea;
                color: #172033;
                margin: 0;
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            .card {
                background: white;
                border: 1px solid #d9c98b;
                border-radius: 18px;
                padding: 28px;
                max-width: 520px;
                box-shadow: 0 8px 26px rgba(0,0,0,0.12);
                text-align: center;
            }
            h1 { margin-top: 0; }
            .actions {
                display: flex;
                justify-content: center;
                gap: 12px;
                margin-top: 22px;
            }
            a {
                display: inline-block;
                padding: 11px 16px;
                border-radius: 12px;
                text-decoration: none;
                font-weight: 700;
            }
            .quit { background: #7a1f1f; color: white; }
            .back { background: #102033; color: white; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>Quitter le logiciel ?</h1>
            <p>Cette action arrête le serveur local Dealer Quote Manager et libère le port 8000.</p>
            <div class="actions">
                <a class="quit" href="/shutdown">Oui, quitter</a>
                <a class="back" href="/">Annuler</a>
            </div>
        </div>
    </body>
    </html>
    """


@app.get("/shutdown", response_class=_ShutdownHTMLResponse)
def shutdown_app():
    _shutdown_process_soon()
    return """
    <!doctype html>
    <html lang="fr">
    <head>
        <meta charset="utf-8">
        <title>Dealer Quote Manager arrêté</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background: #f6f3ea;
                color: #172033;
                margin: 0;
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            .card {
                background: white;
                border: 1px solid #d9c98b;
                border-radius: 18px;
                padding: 28px;
                max-width: 520px;
                box-shadow: 0 8px 26px rgba(0,0,0,0.12);
                text-align: center;
            }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>Logiciel arrêté</h1>
            <p>Tu peux maintenant fermer cette page.</p>
            <p>La fenêtre noire va se fermer automatiquement.</p>
        </div>
    </body>
    </html>
    """


@app.middleware("http")
async def _shutdown_button_middleware(request, call_next):
    response = await call_next(request)

    path = request.url.path
    if path.startswith("/shutdown"):
        return response

    if response.status_code != 200:
        return response

    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type:
        return response

    body = b""
    async for chunk in response.body_iterator:
        body += chunk

    try:
        html = body.decode("utf-8")
    except Exception:
        return response

    button = _shutdown_button_html()

    if "</body>" in html:
        html = html.replace("</body>", button + "</body>", 1)
    else:
        html = html + button

    headers = dict(response.headers)
    headers.pop("content-length", None)

    return _ShutdownHTMLResponse(
        content=html,
        status_code=response.status_code,
        headers=headers,
    )
# --- End shutdown route ---


# --- Dealer discount settings routes - no floating button ---
from fastapi import Request as _DealerDiscountRequest
from fastapi.responses import HTMLResponse as _DealerDiscountHTMLResponse, RedirectResponse as _DealerDiscountRedirectResponse

from dealer_discount_settings import (
    ensure_dealer_discount_schema as _dd_ensure_schema,
    get_dealer_discount_codes as _dd_get_codes,
    reset_dealer_discount_codes as _dd_reset_codes,
    update_dealer_discount_codes as _dd_update_codes,
)


@app.get("/dealer-discounts", response_class=_DealerDiscountHTMLResponse)
def dealer_discounts_page():
    _dd_ensure_schema()
    rows = _dd_get_codes()

    table_rows = []
    for row in rows:
        dc = row["dc"]
        table_rows.append(f"""
            <tr>
                <td class="dc">{dc}</td>
                <td><input name="group_name_{dc}" value="{row['group_name']}"></td>
                <td><textarea name="example_products_{dc}">{row['example_products']}</textarea></td>
                <td><input class="number" name="dealer_discount_{dc}" value="{row['dealer_discount_percent']}"></td>
                <td><input class="number" name="customer_type_discount_{dc}" value="{row['customer_type_discount_percent']}"></td>
            </tr>
        """)

    return f"""
    <!doctype html>
    <html lang="fr">
    <head>
        <meta charset="utf-8">
        <title>Remise dealer</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                margin: 26px;
                background: #f6f3ea;
                color: #172033;
            }}
            .top {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                gap: 16px;
                margin-bottom: 18px;
            }}
            h1 {{
                margin: 0;
            }}
            a {{
                color: #102033;
                font-weight: 700;
                text-decoration: none;
            }}
            .panel {{
                background: white;
                border: 1px solid #d9c98b;
                border-radius: 16px;
                padding: 18px;
                box-shadow: 0 5px 18px rgba(16, 32, 51, 0.08);
                margin-bottom: 18px;
            }}
            .help {{
                color: #667085;
                line-height: 1.45;
                font-size: 14px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                background: white;
                border-radius: 14px;
                overflow: hidden;
            }}
            th {{
                background: #102033;
                color: white;
                text-align: left;
                padding: 10px;
                font-size: 13px;
            }}
            td {{
                border-bottom: 1px solid #e6e0c8;
                padding: 8px;
                vertical-align: top;
            }}
            .dc {{
                font-weight: 700;
                text-align: center;
                width: 55px;
            }}
            input, textarea {{
                width: 100%;
                box-sizing: border-box;
                border: 1px solid #d9d2b5;
                border-radius: 8px;
                padding: 8px;
                font-family: Arial, sans-serif;
                font-size: 13px;
                background: #fffdf7;
            }}
            textarea {{
                min-height: 48px;
                resize: vertical;
            }}
            .number {{
                text-align: right;
                width: 110px;
            }}
            .actions {{
                display: flex;
                gap: 10px;
                margin-top: 16px;
            }}
            button, .button {{
                display: inline-block;
                border: 0;
                border-radius: 10px;
                padding: 11px 15px;
                background: #102033;
                color: white !important;
                font-weight: 700;
                cursor: pointer;
                text-decoration: none;
            }}
            .danger {{
                background: #7a1f1f;
            }}
            .note {{
                font-size: 12px;
                color: #667085;
                margin-top: 10px;
            }}
        </style>
    </head>
    <body>
        <div class="top">
            <h1>Remise dealer</h1>
            <div>
                <a href="/">Accueil</a>
            </div>
        </div>

        <div class="panel help">
            <b>Source constructeur :</b> onglet Internal Master Data, colonnes
            <b>Example products</b> et <b>Dealer discount</b>.
            <br>
            Les remises sont saisies en pourcentage : <b>49</b> = 49%.
            Elles sont stockées dans la base locale et peuvent être ajustées selon le dealer.
        </div>

        <form method="post" action="/dealer-discounts">
            <table>
                <thead>
                    <tr>
                        <th>DC</th>
                        <th>Group</th>
                        <th>Example products</th>
                        <th>Dealer discount %</th>
                        <th>Customer type discount %</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(table_rows)}
                </tbody>
            </table>

            <div class="actions">
                <button type="submit">Enregistrer les remises</button>
                <a class="button danger" href="/dealer-discounts/reset">Réinitialiser valeurs constructeur</a>
            </div>

            <div class="note">
                Cette page rend les remises visibles et paramétrables.
                L’application des remises dans un calcul détaillé par code DC se fera dans une étape dédiée si on décide de recalculer les pièces ligne par ligne.
            </div>
        </form>
    </body>
    </html>
    """


@app.post("/dealer-discounts")
async def dealer_discounts_save(request: _DealerDiscountRequest):
    form = await request.form()
    _dd_update_codes(form)
    return _DealerDiscountRedirectResponse(url="/dealer-discounts", status_code=303)


@app.get("/dealer-discounts/reset")
def dealer_discounts_reset():
    _dd_reset_codes()
    return _DealerDiscountRedirectResponse(url="/dealer-discounts", status_code=303)
# --- End dealer discount settings routes ---


if __name__ == "__main__":
    import uvicorn
    init_db()
    ensure_default_settings()
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/exports-static", StaticFiles(directory=str(EXPORT_DIR)), name="exports-static")
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
