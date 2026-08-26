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
import app_config as config
from service_2_2_detail_calculation import apply_service_2_2_detail_calculation
from pricing_trace_view import get_pricing_result_html
from fluid_catalog import (
    search_engine_oil_catalog_items,
    search_engine_coolant_catalog_items,
)

BASE_DIR = Path(__file__).resolve().parents[2]

def _safe_uploaded_excel_path(upload_dir, filename, prefix="upload"):
    from pathlib import Path
    import re
    import uuid

    upload_dir = Path(upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    raw_name = filename or "uploaded.xlsx"
    suffix = Path(raw_name).suffix.lower()

    if suffix not in (".xlsx", ".xlsm", ".xls"):
        suffix = ".xlsx"

    clean_prefix = re.sub(r"[^A-Za-z0-9_-]+", "_", str(prefix)).strip("_") or "upload"
    return upload_dir / f"{clean_prefix}_{uuid.uuid4().hex[:8]}{suffix}"

DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
EXPORT_DIR = DATA_DIR / "exports"
JSON_DIR = DATA_DIR / "examples"

app = FastAPI(title="Dealer Quote Manager")

config.ensure_storage_dirs()
app.mount("/logos", StaticFiles(directory=config.LOGO_DIR), name="logos")


@app.exception_handler(Exception)
async def clean_global_error_handler(request: Request, exc: Exception):
    import traceback

    error_detail = str(exc) or exc.__class__.__name__
    traceback.print_exc()

    content = f"""
    <h2>Une erreur est survenue</h2>
    <div class="card">
        <p>
            Le logiciel a rencontré une erreur pendant le traitement.
            Les données enregistrées ne sont pas supprimées.
        </p>
        <p>
            <a class="button" href="/">Retour aux offres contrats</a>
            <button class="button secondary" type="button" onclick="history.back()">Retour page précédente</button>
        </p>
    </div>
    <div class="card">
        <h3>Détail technique</h3>
        <div class="error">{error_detail}</div>
    </div>
    """
    return HTMLResponse(layout("Erreur", content), status_code=500)


@app.get("/login", response_class=HTMLResponse)
def login_page():
    content = """
    <h2>Connexion</h2>
    <form method="post" action="/login" class="card">
        <label>Email
            <input type="email" name="email" autocomplete="username" required>
        </label>
        <label>Mot de passe
            <input type="password" name="password" autocomplete="current-password" required>
        </label>
        <button type="submit">Se connecter</button>
    </form>
    """
    return layout("Connexion", content)




@app.get("/logout")
def logout():
    import session_security

    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(session_security.SESSION_COOKIE_NAME)
    return response


@app.get("/me", response_class=HTMLResponse)
def current_user_page(request: Request):
    import session_security

    token = request.cookies.get(session_security.SESSION_COOKIE_NAME)
    email = session_security.verify_session_token(token) if token else None

    if not email:
        return RedirectResponse(url="/login", status_code=303)

    return layout(
        "Utilisateur connecté",
        f"""
        <h2>Session active</h2>
        <p>Connecté avec : <strong>{email}</strong></p>
        <p>
            <a class="button" href="/">Accueil</a>
            <a class="button secondary" href="/logout">Déconnexion</a>
        </p>
        """,
    )

def login_page_with_error(message: str):
    import html as _html

    safe_message = _html.escape(message or "Connexion refusée")

    return f"""
    <!doctype html>
    <html lang="fr">
    <head>
        <meta charset="utf-8">
        <title>Connexion</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f3f4f6;
                margin: 0;
                padding: 40px;
            }}
            .login-card {{
                max-width: 420px;
                margin: 80px auto;
                background: white;
                border-radius: 14px;
                padding: 28px;
                box-shadow: 0 10px 30px rgba(0,0,0,.08);
            }}
            h1 {{
                margin-top: 0;
            }}
            .error {{
                background: #fee2e2;
                color: #991b1b;
                border: 1px solid #fecaca;
                padding: 12px;
                border-radius: 10px;
                margin-bottom: 16px;
                font-weight: 700;
            }}
            label {{
                display: block;
                margin-top: 12px;
                font-weight: 700;
            }}
            input {{
                width: 100%;
                padding: 10px;
                margin-top: 6px;
                box-sizing: border-box;
            }}
            button {{
                margin-top: 18px;
                width: 100%;
                padding: 12px;
                border: 0;
                border-radius: 10px;
                background: #2563eb;
                color: white;
                font-weight: 700;
                cursor: pointer;
            }}
        </style>
    </head>
    <body>
        <div class="login-card">
            <h1>Connexion</h1>
            <div class="error">{safe_message}</div>
            <form method="post" action="/login">
                <label>Email</label>
                <input type="email" name="email" required autofocus>
                <label>Mot de passe</label>
                <input type="password" name="password" required>
                <button type="submit">Se connecter</button>
            </form>
        </div>
    </body>
    </html>
    """


@app.post("/login")
def login_submit(
    email: str = Form(""),
    password: str = Form(""),
):
    import server_user_model as identity

    if identity.verify_user_password(email, password):
        user = identity.get_user_by_email(email)

        user_status = None
        if user:
            try:
                user_status = user["status"]
            except Exception:
                user_status = None

        if not user or user_status != "active":
            return HTMLResponse(
                login_page_with_error("Compte utilisateur désactivé."),
                status_code=403,
            )

        if not identity.user_has_active_company_access(email):
            return HTMLResponse(
                login_page_with_error("Aucun accès société actif actif. Contactez votre administrateur."),
                status_code=403,
            )

        import session_security

        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            key=session_security.SESSION_COOKIE_NAME,
            value=session_security.create_session_token(email),
            httponly=True,
            samesite="lax",
            max_age=session_security.SESSION_DURATION_SECONDS,
        )
        return response

    return HTMLResponse(
        layout(
            "Connexion refusée",
            """
            <h2>Connexion refusée</h2>
            <div class="error">Email ou mot de passe incorrect.</div>
            <p><a class="button secondary" href="/login">Réessayer</a></p>
            """,
        ),
        status_code=401,
    )

def get_logged_user_email(request: Request) -> str | None:
    import session_security

    token = request.cookies.get(session_security.SESSION_COOKIE_NAME)
    if not token:
        return None

    return session_security.verify_session_token(token)


def require_login(request: Request):
    email = get_logged_user_email(request)
    if not email:
        return RedirectResponse(url="/login", status_code=303)
    return None


@app.middleware("http")
async def global_login_guard(request: Request, call_next):
    public_paths = {
        "/login",
        "/logout",
        "/health",
        "/favicon.ico",
    }

    path = request.url.path

    if path in public_paths:
        return await call_next(request)

    token = request.cookies.get("dealer_quote_session")
    email = None

    if token:
        import session_security
        email = session_security.verify_session_token(token)

    if not email:
        return RedirectResponse(url="/login", status_code=303)

    return await call_next(request)


def get_active_company_id_for_request(request: Request) -> int:
    import server_user_model as identity

    email = get_logged_user_email(request)
    if email:
        return identity.get_active_company_id_for_user(email)

    return get_active_company_id_for_request(request)


def get_active_company_name_for_request(request: Request) -> str:
    import server_user_model as identity

    email = get_logged_user_email(request)
    if email:
        return identity.get_active_company_name_for_user(email)

    return get_active_company_name_for_request(request)


def get_quote_for_active_company_request(conn, quote_id: int, request: Request):
    active_company_id = get_active_company_id_for_request(request)

    return conn.execute(
        "SELECT * FROM quotes WHERE id = ? AND company_id = ?",
        (quote_id, active_company_id),
    ).fetchone()


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
        <a href="/">Offres contrats</a>
        <a href="/settings">Paramètres calcul</a>
        <a href="/dealer-discounts">Codes remises</a>
        <a href="/price-catalog">Catalogue pièces</a>
        <a href="/server/company-switch">Changer société</a>
        <a href="/server/companies">Sociétés</a>
        <a href="/server/company-branding">Identité société</a>
        <a href="/login">Connexion</a>
        <a href="/logout">Déconnexion</a>
        <a href="/server/users">Utilisateurs</a>
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


def get_feedback_webhook_url():
    path = DATA_DIR / "feedback_webhook_url.txt"
    if path.exists():
        return path.read_text(encoding="utf-8-sig").strip()
    return ""


def save_feedback_local(payload):
    import csv
    from datetime import datetime

    feedback_dir = DATA_DIR / "feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)

    csv_path = feedback_dir / "retours_experience.csv"
    exists = csv_path.exists()

    fieldnames = [
        "created_at",
        "user_name",
        "page_context",
        "feedback_type",
        "rating",
        "quote_id",
        "message",
        "suggestion",
        "priority",
        "app_version",
    ]

    row = {"created_at": datetime.now().isoformat(timespec="seconds")}
    row.update(payload)

    with csv_path.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        if not exists:
            writer.writeheader()
        writer.writerow(row)

    return csv_path


def send_feedback_to_google_sheet(payload):
    """
    Envoi optionnel vers Google Sheet via Apps Script.
    Si data/feedback_webhook_url.txt n'existe pas, on sauvegarde seulement en local.
    """
    url = get_feedback_webhook_url()
    if not url:
        return False, "Webhook Google Sheet non configuré"

    try:
        import json
        import urllib.request

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            response.read()
        return True, "Envoyé vers Google Sheet"
    except Exception as exc:
        return False, str(exc)


@app.post("/feedback")
def feedback_submit(
    user_name: str = Form(""),
    page_context: str = Form(""),
    feedback_type: str = Form(""),
    rating: str = Form(""),
    quote_id: str = Form(""),
    message: str = Form(""),
    suggestion: str = Form(""),
    priority: str = Form(""),
):
    payload = {
        "user_name": user_name.strip(),
        "page_context": page_context.strip(),
        "feedback_type": feedback_type.strip(),
        "rating": rating.strip(),
        "quote_id": quote_id.strip(),
        "message": message.strip(),
        "suggestion": suggestion.strip(),
        "priority": priority.strip(),
        "app_version": "test",
    }

    try:
        save_feedback_local(payload)
    except PermissionError:
        # CSV ouvert/verrouillé, par exemple dans Excel.
        # On n'empêche pas l'envoi vers Google Sheet.
        pass

    send_feedback_to_google_sheet(payload)

    from fastapi.responses import RedirectResponse
    return RedirectResponse("/", status_code=303)




@app.get("/health")
def health_check():
    from pathlib import Path
    import sqlite3
    import app_config as config

    config.ensure_storage_dirs()

    db_status = "unknown"
    db_path = None

    if config.DATABASE_URL.startswith("sqlite:///"):
        db_relative = config.DATABASE_URL.replace("sqlite:///", "", 1)
        db_path = config.BASE_DIR / db_relative
        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute("SELECT 1")
            db_status = "ok"
        except Exception as exc:
            db_status = f"error: {exc}"
    else:
        db_status = "not_checked_yet"

    storage_checks = {
        "storage": config.STORAGE_DIR.exists(),
        "uploads": config.UPLOAD_DIR.exists(),
        "pdf": config.PDF_DIR.exists(),
        "logos": config.LOGO_DIR.exists(),
        "contracts": config.CONTRACT_DIR.exists(),
        "signed": config.SIGNED_DIR.exists(),
        "backups": config.BACKUP_DIR.exists(),
        "feedback": config.FEEDBACK_DIR.exists(),
    }

    identity_status = {
        "enabled": False,
        "companies": None,
        "users": None,
        "company_access": None,
        "error": None,
    }

    try:
        import server_user_model as identity

        identity.init_server_identity_tables()
        identity_status["enabled"] = True
        identity_status["companies"] = len(identity.list_companies())
        identity_status["users"] = len(identity.list_users())
        identity_status["company_access"] = len(identity.list_company_access())
    except Exception as exc:
        identity_status["error"] = str(exc)

    return {
        "status": "ok",
        "app_name": config.APP_NAME,
        "app_version": config.APP_VERSION,
        "app_env": config.APP_ENV,
        "public_url": config.PUBLIC_URL,
        "database_url": config.DATABASE_URL,
        "database_status": db_status,
        "database_path": str(db_path) if db_path else None,
        "storage": storage_checks,
        "identity": identity_status,
    }




@app.get("/server/identity", response_class=HTMLResponse)
def server_identity_page(request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    import server_user_model as identity
    from server_identity import get_role_label

    identity.init_server_identity_tables()

    companies = identity.list_companies()
    users = identity.list_users()
    accesses = identity.list_company_access()

    def esc(value):
        import html
        return html.escape(str(value)) if value is not None else ""

    companies_rows = "".join(
        f"""
        <tr>
            <td>{row['id']}</td>
            <td>{esc(row['name'])}</td>
            <td>{esc(row['slug'])}</td>
            <td>{esc(row['status'])}</td>
            <td>{esc(row['created_at'])}</td>
        </tr>
        """
        for row in companies
    ) or "<tr><td colspan='5'>Aucune société</td></tr>"

    users_rows = "".join(
        f"""
        <tr>
            <td>{row['id']}</td>
            <td>{esc(row['email'])}</td>
            <td>{esc(row['full_name'])}</td>
            <td>{esc(row['status'])}</td>
            <td>{esc(row['created_at'])}</td>
        </tr>
        """
        for row in users
    ) or "<tr><td colspan='5'>Aucun utilisateur</td></tr>"

    access_rows = "".join(
        f"""
        <tr>
            <td>{row['id']}</td>
            <td>{esc(row['company_name'])}</td>
            <td>{esc(row['user_email'])}</td>
            <td>{esc(row['role'])}</td>
            <td>{esc(get_role_label(row['role']))}</td>
            <td>{esc(row['status'])}</td>
        </tr>
        """
        for row in accesses
    ) or "<tr><td colspan='6'>Aucun accès</td></tr>"

    return f"""
    <html>
    <head>
        <meta charset="utf-8">
        <title>Identité serveur - Dealer Quote Manager</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f5f7fb;
                color: #1f2937;
                margin: 0;
                padding: 30px;
            }}
            .container {{
                max-width: 1200px;
                margin: auto;
            }}
            h1 {{
                margin-bottom: 5px;
            }}
            .muted {{
                color: #6b7280;
                margin-bottom: 25px;
            }}
            .card {{
                background: white;
                border-radius: 14px;
                padding: 20px;
                margin-bottom: 22px;
                box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 12px;
            }}
            th, td {{
                border-bottom: 1px solid #e5e7eb;
                padding: 10px;
                text-align: left;
                font-size: 14px;
            }}
            th {{
                background: #f9fafb;
                font-weight: 700;
            }}
            .warning {{
                background: #fff7ed;
                border: 1px solid #fed7aa;
                color: #9a3412;
                padding: 12px 14px;
                border-radius: 10px;
                margin-bottom: 20px;
            }}
            a {{
                color: #2563eb;
                text-decoration: none;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Identité serveur</h1>
            <div class="muted">Lecture développement : sociétés, utilisateurs et rôles d'accès.</div>

            <div class="warning">
                Page temporaire non sécurisée. À protéger plus tard par login OWNER / SUPER_ADMIN / TECH_ADMIN.
            </div>

            <p><a href="/">← Retour accueil</a> | <a href="/health">Voir /health</a></p>

            <div class="card">
                <h2>Sociétés</h2>
                <table>
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Nom</th>
                            <th>Slug</th>
                            <th>Statut</th>
                            <th>Création</th>
                        </tr>
                    </thead>
                    <tbody>{companies_rows}</tbody>
                </table>
            </div>

            <div class="card">
                <h2>Utilisateurs</h2>
                <table>
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Email</th>
                            <th>Nom</th>
                            <th>Statut</th>
                            <th>Création</th>
                        </tr>
                    </thead>
                    <tbody>{users_rows}</tbody>
                </table>
            </div>

            <div class="card">
                <h2>Accès société / utilisateur</h2>
                <table>
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Société</th>
                            <th>Utilisateur</th>
                            <th>Rôle</th>
                            <th>Libellé</th>
                            <th>Statut</th>
                        </tr>
                    </thead>
                    <tbody>{access_rows}</tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """




@app.get("/server/identity/new", response_class=HTMLResponse)
def server_identity_new_page(request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    from server_identity import ServerRole, get_role_label

    role_options = "".join(
        f"<option value='{role.value}'>{role.value} - {get_role_label(role.value)}</option>"
        for role in ServerRole
    )

    return f"""
    <html>
    <head>
        <meta charset="utf-8">
        <title>Créer accès serveur</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f5f7fb;
                color: #1f2937;
                padding: 30px;
            }}
            .container {{
                max-width: 760px;
                margin: auto;
                background: white;
                padding: 25px;
                border-radius: 14px;
                box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
            }}
            label {{
                display: block;
                margin-top: 14px;
                font-weight: 700;
            }}
            input, select {{
                width: 100%;
                padding: 10px;
                margin-top: 5px;
                border: 1px solid #d1d5db;
                border-radius: 8px;
            }}
            button {{
                margin-top: 20px;
                padding: 12px 18px;
                border: 0;
                border-radius: 9px;
                background: #2563eb;
                color: white;
                font-weight: 700;
                cursor: pointer;
            }}
            .warning {{
                background: #fff7ed;
                border: 1px solid #fed7aa;
                color: #9a3412;
                padding: 12px;
                border-radius: 10px;
                margin-bottom: 20px;
            }}
            a {{
                color: #2563eb;
                text-decoration: none;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Créer société / utilisateur</h1>

            <div class="warning">
                Page temporaire de développement. À protéger plus tard par login.
            </div>

            <p><a href="/server/identity">← Retour identité serveur</a></p>

            <form method="post" action="/server/identity/new">
                <label>Nom société</label>
                <input name="company_name" placeholder="Client Test 1" required>

                <label>Slug société</label>
                <input name="company_slug" placeholder="client-test-1" required>

                <label>Email utilisateur</label>
                <input name="user_email" type="email" placeholder="testeur@societe.fr" required>

                <label>Nom utilisateur</label>
                <input name="full_name" placeholder="Nom Prénom">

                <label>Rôle</label>
                <select name="role">
                    {role_options}
                </select>

                <button type="submit">Créer l'accès</button>
            </form>
        </div>
    </body>
    </html>
    """


@app.post("/server/identity/new")
def server_identity_create(
    request: Request,
    company_name: str = Form(...),
    company_slug: str = Form(...),
    user_email: str = Form(...),
    full_name: str = Form(""),
    role: str = Form(...),
):
    admin_response = require_owner_or_super_admin(request)
    if admin_response:
        return admin_response

    import server_user_model as identity
    from fastapi.responses import RedirectResponse

    identity.init_server_identity_tables()

    company_id = identity.create_company(company_name.strip(), company_slug.strip().lower())
    user_id = identity.create_user(user_email.strip().lower(), full_name.strip())
    identity.grant_company_access(company_id, user_id, role)

    return RedirectResponse("/server/identity", status_code=303)






@app.get("/server/company-branding", response_class=HTMLResponse)
def server_company_branding_page(request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    import server_user_model as identity
    import html

    context = get_request_company_context(request)
    if not context:
        return company_context_required_page()

    company_id = int(context["company_id"])
    company = identity.get_company_by_id(company_id)

    if not company:
        return HTMLResponse("Société introuvable", status_code=404)

    def value(field):
        try:
            return html.escape(str(company[field] or ""))
        except Exception:
            return ""

    company_name = value("name")
    logo_filename = company["logo_filename"] if "logo_filename" in company.keys() else None

    logo_html = "<p>Aucun logo importé pour cette société.</p>"
    if logo_filename:
        logo_url = f"/logos/{html.escape(logo_filename)}"
        logo_html = f"""
        <p>Logo actuel :</p>
        <div style="padding:12px;border:1px solid #e5e7eb;border-radius:10px;background:white;">
            <img src="{logo_url}" alt="Logo société" style="max-width:260px;max-height:120px;">
        </div>
        <p class="muted">Fichier : {html.escape(logo_filename)}</p>
        """

    content = f"""
    <section class="card">
        <h2>Identité société</h2>
        <p class="muted">Société active : <strong>{company_name}</strong></p>
        <p class="muted">Ces informations seront utilisées pour présenter proprement les devis et exports.</p>
    </section>

    <section class="card">
        <h3>Logo</h3>
        {logo_html}

        <form method="post" action="/server/company-branding/logo" enctype="multipart/form-data">
            <label>Importer un logo PNG/JPG</label>
            <input type="file" name="logo" accept=".png,.jpg,.jpeg" required>
            <button type="submit">Importer le logo</button>
        </form>
    </section>

    <section class="card">
        <h3>Informations société</h3>

        <form method="post" action="/server/company-branding">
            <label>Nom affiché sur le devis</label>
            <input name="display_name" value="{value("display_name")}" placeholder="{company_name}">

            <label>Raison sociale</label>
            <input name="legal_name" value="{value("legal_name")}" placeholder="Ex : GWEN SERVICE SAS">

            <label>Adresse ligne 1</label>
            <input name="address_line1" value="{value("address_line1")}" placeholder="Rue, ZA, bâtiment...">

            <label>Adresse ligne 2</label>
            <input name="address_line2" value="{value("address_line2")}" placeholder="Complément d'adresse">

            <div style="display:grid;grid-template-columns:1fr 2fr;gap:12px;">
                <div>
                    <label>Code postal</label>
                    <input name="postal_code" value="{value("postal_code")}">
                </div>
                <div>
                    <label>Ville</label>
                    <input name="city" value="{value("city")}">
                </div>
            </div>

            <label>Pays</label>
            <input name="country" value="{value("country")}" placeholder="France">

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                <div>
                    <label>Téléphone</label>
                    <input name="phone" value="{value("phone")}">
                </div>
                <div>
                    <label>Email</label>
                    <input name="email" value="{value("email")}">
                </div>
            </div>

            <label>Site web</label>
            <input name="website" value="{value("website")}" placeholder="https://...">

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                <div>
                    <label>SIRET</label>
                    <input name="siret" value="{value("siret")}">
                </div>
                <div>
                    <label>TVA intracommunautaire</label>
                    <input name="vat_number" value="{value("vat_number")}">
                </div>
            </div>

            <button type="submit">Enregistrer l'identité société</button>
        </form>
    </section>
    """

    return layout("Identité société", content)


@app.post("/server/company-branding", response_class=HTMLResponse)
async def server_company_branding_update(
    request: Request,
    display_name: str = Form(""),
    legal_name: str = Form(""),
    address_line1: str = Form(""),
    address_line2: str = Form(""),
    postal_code: str = Form(""),
    city: str = Form(""),
    country: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    website: str = Form(""),
    siret: str = Form(""),
    vat_number: str = Form(""),
):
    login_response = require_login(request)
    if login_response:
        return login_response

    import server_user_model as identity

    context = get_request_company_context(request)
    if not context:
        return company_context_required_page()

    company_id = int(context["company_id"])

    def clean(value: str):
        value = (value or "").strip()
        return value or None

    identity.update_company_branding(
        company_id=company_id,
        display_name=clean(display_name),
        legal_name=clean(legal_name),
        address_line1=clean(address_line1),
        address_line2=clean(address_line2),
        postal_code=clean(postal_code),
        city=clean(city),
        country=clean(country),
        phone=clean(phone),
        email=clean(email),
        website=clean(website),
        siret=clean(siret),
        vat_number=clean(vat_number),
    )

    return RedirectResponse(url="/server/company-branding", status_code=303)


@app.post("/server/company-branding/logo", response_class=HTMLResponse)
async def server_company_branding_logo_upload(request: Request, logo: UploadFile = File(...)):
    login_response = require_login(request)
    if login_response:
        return login_response

    import server_user_model as identity
    import re

    context = get_request_company_context(request)
    if not context:
        return company_context_required_page()

    company_id = int(context["company_id"])
    company_name = str(context["company_name"] or f"societe-{company_id}")

    original_name = logo.filename or ""
    suffix = Path(original_name).suffix.lower()

    if suffix not in [".png", ".jpg", ".jpeg"]:
        return HTMLResponse(
            layout(
                "Logo société",
                """
                <h2>Logo société</h2>
                <div class="card">
                    <p>Format refusé. Utilise un fichier PNG, JPG ou JPEG.</p>
                    <p><a class="button secondary" href="/server/company-branding">Retour</a></p>
                </div>
                """,
            ),
            status_code=400,
        )

    safe_slug = re.sub(r"[^a-z0-9_-]+", "-", company_name.lower()).strip("-") or f"societe-{company_id}"
    filename = f"company_{company_id}_{safe_slug}{suffix}"

    config.LOGO_DIR.mkdir(parents=True, exist_ok=True)
    destination = config.LOGO_DIR / filename

    with destination.open("wb") as buffer:
        shutil.copyfileobj(logo.file, buffer)

    identity.set_company_logo_filename(company_id, filename)

    return RedirectResponse(url="/server/company-branding", status_code=303)


@app.get("/server/company-switch", response_class=HTMLResponse)
def server_company_switch_page(request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    import server_user_model as identity

    email = get_logged_user_email(request)

    if identity.user_has_any_role(email, ["OWNER", "SUPER_ADMIN"]):
        companies = [
            {
                "id": company["id"],
                "name": company["name"],
                "role": "SUPER_ADMIN",
            }
            for company in identity.list_companies()
            if str(company["status"] or "") == "active"
        ]
    else:
        companies = identity.list_companies_for_user(email)

    active_company_id = get_active_company_id_for_request(request)
    active_company_name = get_active_company_name_for_request(request)

    if not companies:
        return layout(
            "Changer société",
            """
            <h2>Changer société active</h2>
            <div class="error">Aucune société accessible pour cet utilisateur.</div>
            <p><a class="button secondary" href="/">Retour</a></p>
            """,
        )

    options = "".join(
        f"<option value='{company['id']}' {'selected' if int(company['id']) == int(active_company_id) else ''}>{company['name']} — {company['role']}</option>"
        for company in companies
    )

    content = f"""
    <h2>Changer société active</h2>
    <p>Société active actuelle : <strong>{active_company_name}</strong></p>

    <form method="post" action="/server/company-switch" class="card">
        <label>Société
            <select name="company_id">
                {options}
            </select>
        </label>
        <button type="submit">Changer de société</button>
        <a class="button secondary" href="/">Retour</a>
    </form>
    """

    return layout("Changer société", content)


@app.post("/server/company-switch")
def server_company_switch_submit(
    request: Request,
    company_id: int = Form(...),
):
    login_response = require_login(request)
    if login_response:
        return login_response

    import server_user_model as identity

    email = get_logged_user_email(request)

    if identity.user_has_any_role(email, ["OWNER", "SUPER_ADMIN"]):
        company = identity.get_company_by_id(company_id)
        if company is None or str(company["status"] or "") != "active":
            return HTMLResponse(
                layout(
                    "Changer société",
                    """
                    <h2>Changer société active</h2>
                    <div class="error">Société introuvable ou inactive.</div>
                    <p><a class="button secondary" href="/server/company-switch">Retour</a></p>
                    """
                ),
                status_code=400,
            )

        current_user = identity.get_user_by_email(email)
        if current_user and not identity.user_has_company_access(email, company_id):
            identity.grant_company_access(
                int(company_id),
                int(current_user["id"]),
                "SUPER_ADMIN",
            )

    identity.set_active_company_id_for_user(email, company_id)

    return RedirectResponse(url="/", status_code=303)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    init_db()

    import server_user_model as identity
    active_company_id = get_active_company_id_for_request(request)
    active_company_name = get_active_company_name_for_request(request)

    with get_connection() as conn:

        rows = conn.execute(
            """
            SELECT
                   q.id, q.created_at, q.status, q.customer_name, q.product_designation, q.engine_serial_number,
                   q.currency, q.total_cost, q.selling_total, q.selling_monthly, q.selling_per_hour, q.total_hours,
                   COALESCE(c.name, 'Sans société') AS company_name
            FROM quotes q
            LEFT JOIN companies c ON c.id = q.company_id
            WHERE q.company_id = ?
            ORDER BY q.id DESC
            """,
            (active_company_id,),
        ).fetchall()

    can_view_dealer_exports = can_access_dealer_exports(request)

    rows_html = ""
    for row in rows:
        if str(row["status"] or "") == "archived":
            continue

        currency = row["currency"] or "EUR"
        quote_id = row["id"]

        total_cost = row["total_cost"] or 0
        selling_total = row["selling_total"] or 0
        total_hours = row["total_hours"] or 0

        cost_per_hour = total_cost / total_hours if total_hours else None
        margin_amount = selling_total - total_cost
        margin_percent = (margin_amount / total_cost * 100) if total_cost else None

        cost_per_hour_txt = f"{fmt_money(cost_per_hour, currency)}/h" if cost_per_hour is not None else "-"
        selling_per_hour_txt = f"{fmt_money(row['selling_per_hour'], currency)}/h" if row["selling_per_hour"] is not None else "-"
        margin_amount_txt = fmt_money(margin_amount, currency)
        margin_percent_txt = f"{margin_percent:.2f} %" if margin_percent is not None else "-"

        pdf_path = EXPORT_DIR / f"quote_{quote_id}.pdf"
        html_path = EXPORT_DIR / f"quote_{quote_id}.html"
        dealer_pdf_path = EXPORT_DIR / f"quote_{quote_id}_dealer.pdf"
        dealer_html_path = EXPORT_DIR / f"quote_{quote_id}_dealer.html"
        pdf_link = f'<a class="button gold" href="/exports/quote_{quote_id}.pdf" target="_blank">PDF client</a>' if pdf_path.exists() else ""
        html_link = f'<a class="button secondary" href="/exports/quote_{quote_id}.html" target="_blank">HTML client</a>' if html_path.exists() else ""
        dealer_pdf_link = f'<a class="button danger" href="/exports/quote_{quote_id}_dealer.pdf" target="_blank">PDF dealer</a>' if can_view_dealer_exports and dealer_pdf_path.exists() else ""
        dealer_html_link = f'<a class="button secondary" href="/exports/quote_{quote_id}_dealer.html" target="_blank">HTML dealer</a>' if can_view_dealer_exports and dealer_html_path.exists() else ""

        rows_html += f"""
        <tr>
            <td>{quote_id}</td><td>{row['created_at']}</td><td>{row['status']}</td>
            <td>{row['company_name'] or 'Sans société'}</td>
            <td>{row['customer_name'] or '-'}</td><td>{row['product_designation'] or '-'}</td>
            <td>{row['engine_serial_number'] or '-'}</td><td>{fmt_money(row['total_cost'], currency)}</td>
            <td><strong>{fmt_money(row['selling_total'], currency)}</strong></td>
            <td>{fmt_money(row['selling_monthly'], currency)}</td>
            <td>{cost_per_hour_txt}</td>
            <td><strong>{selling_per_hour_txt}</strong></td>
            <td><strong>{margin_amount_txt}</strong></td>
            <td><strong>{margin_percent_txt}</strong></td>
            <td class="actions">
                <a class="button green" href="/quote/{quote_id}/inputs">Données contrat / moteur</a>
                <a class="button" href="/quote/{quote_id}/services">Construction de l’offre</a>
                <a class="button secondary" href="/quote/{quote_id}/export">Générer exports</a>
                {f'<a class="button gold" href="/quote/{quote_id}/contract/create">Cr&eacute;er le contrat</a>' if str(row['status'] or '') == 'accepted' else ''}
                {f'<a class="button danger" href="/quote/{quote_id}/archive/confirm">Archiver</a>' if str(row['status']) in ['draft', 'sent', 'refused'] else ''}
                {f'<a class="button secondary" href="/quote/{quote_id}/restore">Restaurer</a>' if str(row['status']) == 'archived' else ''}
                {html_link}{pdf_link}{dealer_html_link}{dealer_pdf_link}
            </td>
        </tr>"""

    if not rows_html:
        rows_html = '<tr><td colspan="15">Aucune offre de contrat pour le moment. Commence par importer un fichier Service Calculator.</td></tr>'

    content = f"""
    <h2>Offres de contrat de service</h2>
    <div class="card">
        <strong>Société active :</strong> {active_company_name}
    </div>
    <div class="card">
        <a class="button" href="/import">Importer un nouveau fichier Service Calculator</a>
        <a class="button green" href="/contracts">Contrats</a>
        <button class="button secondary" type="button" onclick="document.getElementById('feedbackModal').style.display='block'">Retour d'expérience</button>
    </div>

    <div id="feedbackModal" style="display:none; position:fixed; z-index:9999; left:0; top:0; width:100%; height:100%; background:rgba(0,0,0,0.45);">
        <div style="background:#fff; color:#111; max-width:720px; margin:5% auto; padding:22px; border-radius:14px; box-shadow:0 10px 30px rgba(0,0,0,0.25);">
            <div style="display:flex; justify-content:space-between; align-items:center; gap:12px;">
                <h3 style="margin:0;">Retour d'expérience logiciel</h3>
                <button class="button secondary" type="button" onclick="document.getElementById('feedbackModal').style.display='none'">Fermer</button>
            </div>

            <form method="post" action="/feedback" style="margin-top:18px;">
                <div class="grid">
                    <label>Nom utilisateur
                        <input name="user_name" placeholder="Nom / testeur">
                    </label>

                    <label>Page concernée
                        <select name="page_context">
                            <option>Offres de contrat de service</option>
                            <option>Import</option>
                            <option>Construction de l’offre</option>
                            <option>PDF</option>
                            <option>Paramètres de calcul dealer</option>
                            <option>Codes remises dealer</option>
                            <option>Autre</option>
                        </select>
                    </label>

                    <label>Type de retour
                        <select name="feedback_type">
                            <option>Bug</option>
                            <option>Suggestion</option>
                            <option>Compréhension</option>
                            <option>Calcul</option>
                            <option>Affichage</option>
                            <option>PDF</option>
                            <option>Import Excel</option>
                        </select>
                    </label>

                    <label>Note /10
                        <input name="rating" type="number" min="0" max="10" step="1">
                    </label>

                    <label>Offre / devis ID concerné
                        <input name="quote_id" placeholder="ex : 23">
                    </label>

                    <label>Priorité
                        <select name="priority">
                            <option>Basse</option>
                            <option>Moyenne</option>
                            <option>Haute</option>
                            <option>Bloquant</option>
                        </select>
                    </label>
                </div>

                <label>Message / problème rencontré
                    <textarea name="message" rows="5" placeholder="Décrire le retour d'expérience"></textarea>
                </label>

                <label>Suggestion / amélioration proposée
                    <textarea name="suggestion" rows="3" placeholder="Idée ou correction souhaitée"></textarea>
                </label>

                <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:14px;">
                    <button class="button secondary" type="button" onclick="document.getElementById('feedbackModal').style.display='none'">Annuler</button>
                    <button class="button green" type="submit">Envoyer</button>
                </div>
            </form>
        </div>
    </div>
    <table>
        <thead><tr>
            <th>ID</th>
            <th>Date</th>
            <th>Statut</th>
            <th>Société</th>
            <th>Client</th>
            <th>Moteur</th>
            <th>Serial</th>
            <th>Cout brut</th>
            <th>Prix client</th>
            <th>Mensuel</th>
            <th>Cout/h</th>
            <th>Prix client/h</th>
            <th>Marge EUR</th>
            <th>Marge %</th>
            <th>Actions</th>
        </tr></thead>
        <tbody>{rows_html}</tbody>
    </table>"""
    return layout("Offres contrats", content)

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
            <li>Overview / Summary Prestations incluses au contrat : prix final.</li>
        </ol>
    </div>
    <h3>Prestations incluses au contrat configurables</h3>
    <table>
        <thead><tr><th>ID</th><th>Groupe</th><th>Service</th><th>Source Excel vérifiée</th></tr></thead>
        <tbody>{service_rows}</tbody>
    </table>
    """
    return layout("Instructions", content)

@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

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
def import_file(request: Request, file: UploadFile = File(...)):
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
        from create_quote_from_import import create_quote_from_json

        quote_id = create_quote_from_json(
            str(json_path),
            company_id=get_active_company_id_for_request(request),
        )

        if quote_id is None:
            raise RuntimeError("Impossible de créer le devis importé.")

        ensure_quote_services(quote_id)

        # Remonte le total de l'onglet Overview colonne C dans le service 2.2.
        # Compatible EXE : ne relance pas l'application, met à jour la base directement.
        try:
            from overview_total_sync import apply_overview_total_to_service_2_2
            overview_totals = apply_overview_total_to_service_2_2(quote_id, upload_path)
            # Ne pas écraser le montant commercial Overview par le détail technique Hidden for import.
            # L'Overview est déjà la sortie calculée du calculateur Volvo précédent.
            # Le détail Hidden for import restera réservé à un audit séparé.
            print(f"Overview C -> service 2.2 : {overview_totals}")
        except Exception as exc:
            print(f"Attention : impossible de remonter Overview C vers 2.2 : {exc}")

        run_command([sys.executable, "backend/app/apply_pricing.py", str(quote_id)])
        run_command([sys.executable, "backend/app/export_quote_html.py", str(quote_id)])
        run_command([sys.executable, "backend/app/export_quote_pdf.py", str(quote_id)])
        run_command([sys.executable, "backend/app/export_quote_dealer_html.py", str(quote_id)])
        run_command([sys.executable, "backend/app/export_quote_dealer_pdf.py", str(quote_id)])

        return RedirectResponse(url=f"/quote/{quote_id}/inputs", status_code=303)

    except Exception as exc:
        return layout("Erreur import", f"<h2>Erreur import</h2><div class='error'>{str(exc)}</div><a class='button' href='/import'>Retour import</a>")



def get_quote_for_active_company(conn, quote_id: int):
    import server_user_model as identity

    active_company_id = identity.get_active_company_id()

    return conn.execute(
        "SELECT * FROM quotes WHERE id = ? AND company_id = ?",
        (quote_id, active_company_id),
    ).fetchone()


def quote_access_denied_response(quote_id: int):
    return HTMLResponse(
        layout(
            "Accès refusé",
            f"""
            <div class="error">
                Devis introuvable ou non autorisé pour la société active : {quote_id}
            </div>
            <p>
                <a class="button secondary" href="/">Retour offres contrats</a>
                <a class="button" href="/server/company-switch">Changer société</a>
            </p>
            """,
        ),
        status_code=404,
    )




def get_quote_for_current_company(request: Request, quote_id: int):
    context = get_request_company_context(request)
    company_id = int(context["company_id"])

    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM quotes WHERE id = ? AND company_id = ?",
            (quote_id, company_id),
        ).fetchone()


@app.get("/quote/{quote_id}/archive/confirm", response_class=HTMLResponse)
def quote_archive_confirm_page(quote_id: int, request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    quote = get_quote_for_current_company(request, quote_id)
    if not quote:
        return HTMLResponse(
            layout(
                "Cotation introuvable",
                """
                <h2>Archiver cotation</h2>
                <div class="error">Cotation introuvable ou non accessible pour cette société.</div>
                <p><a class="button secondary" href="/">Retour</a></p>
                """
            ),
            status_code=404,
        )

    status = str(quote["status"] or "")
    if status == "accepted":
        return HTMLResponse(
            layout(
                "Archivage refusé",
                """
                <h2>Archivage refusé</h2>
                <div class="error">
                    Une cotation acceptée ne peut pas être archivée depuis cette action.
                </div>
                <p><a class="button secondary" href="/">Retour offres contrats</a></p>
                """
            ),
            status_code=403,
        )

    if status == "archived":
        return RedirectResponse(url="/", status_code=303)

    customer = quote["customer_name"] or "-"
    engine = quote["engine_serial_number"] or "-"
    product = quote["product_designation"] or quote["product_name"] or "-"

    content = f"""
    <h2>Confirmer l’archivage</h2>

    <div class="warning">
        <p><strong>Attention :</strong> la cotation ne sera pas supprimée.</p>
        <p>Elle sera seulement passée au statut <strong>archived</strong> pour conserver l’historique.</p>
    </div>

    <div class="card">
        <p><strong>Cotation :</strong> #{quote_id}</p>
        <p><strong>Client :</strong> {customer}</p>
        <p><strong>Moteur / produit :</strong> {product}</p>
        <p><strong>N° série :</strong> {engine}</p>
        <p><strong>Statut actuel :</strong> {status}</p>
    </div>

    <form method="post" action="/quote/{quote_id}/archive" class="card">
        <button type="submit" class="danger">Confirmer l’archivage</button>
        <a class="button secondary" href="/">Annuler</a>
    </form>
    """

    return layout("Archiver cotation", content)


@app.post("/quote/{quote_id}/archive", response_class=HTMLResponse)
def quote_archive_submit(quote_id: int, request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    quote = get_quote_for_current_company(request, quote_id)
    if not quote:
        return HTMLResponse(
            layout(
                "Cotation introuvable",
                """
                <h2>Archiver cotation</h2>
                <div class="error">Cotation introuvable ou non accessible pour cette société.</div>
                <p><a class="button secondary" href="/">Retour</a></p>
                """
            ),
            status_code=404,
        )

    status = str(quote["status"] or "")
    if status == "accepted":
        return HTMLResponse(
            layout(
                "Archivage refusé",
                """
                <h2>Archivage refusé</h2>
                <div class="error">Une cotation acceptée ne peut pas être archivée.</div>
                <p><a class="button secondary" href="/">Retour offres contrats</a></p>
                """
            ),
            status_code=403,
        )

    with get_connection() as conn:
        conn.execute(
            "UPDATE quotes SET status = ? WHERE id = ?",
            ("archived", quote_id),
        )
        conn.commit()

    return RedirectResponse(url="/", status_code=303)


@app.get("/quote/{quote_id}/restore")
def quote_restore(quote_id: int, request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    quote = get_quote_for_current_company(request, quote_id)
    if not quote:
        return RedirectResponse(url="/", status_code=303)

    status = str(quote["status"] or "")
    if status == "archived":
        with get_connection() as conn:
            conn.execute(
                "UPDATE quotes SET status = ? WHERE id = ?",
                ("draft", quote_id),
            )
            conn.commit()

    return RedirectResponse(url="/", status_code=303)




@app.get("/archives", response_class=HTMLResponse)
def archives_page(request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    context = get_request_company_context(request)
    company_id = int(context["company_id"])
    can_view_dealer_exports = user_can_view_dealer_exports(request)

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                q.id, q.created_at, q.status, q.customer_name, q.product_designation,
                q.engine_serial_number, q.product_name, q.country
            FROM quotes q
            WHERE q.company_id = ? AND q.status = 'archived'
            ORDER BY q.created_at DESC
            """,
            (company_id, today.isoformat(), limit_date.isoformat()),
        ).fetchall()

    table_rows = ""

    for row in rows:
        if str(row["status"] or "") == "archived":
            continue

        quote_id = row["id"]
        customer = row["customer_name"] or "-"
        product = row["product_designation"] or row["product_name"] or "-"
        serial = row["engine_serial_number"] or "-"
        country = row["country"] or "-"
        created_at = row["created_at"] or "-"
        status = row["status"] or "-"

        table_rows += f"""
        <tr>
            <td>{quote_id}</td>
            <td>{created_at}</td>
            <td>{status}</td>
            <td>{customer}</td>
            <td>{product}</td>
            <td>{serial}</td>
            <td>{country}</td>
            <td>
                <a class="button secondary" href="/quote/{quote_id}/restore-simple">Restaurer</a>
                <a class="button green" href="/quote/{quote_id}/inputs">Voir</a>
            </td>
        </tr>
        """

    if not table_rows:
        table_rows = """
        <tr>
            <td colspan="8">Aucune cotation archivée pour cette société.</td>
        </tr>
        """

    content = f"""
    <h2>Archives des cotations</h2>

    <p>
        <a class="button secondary" href="/">Retour aux offres actives</a>
    </p>

    <table>
        <thead>
            <tr>
                <th>ID</th>
                <th>Créée le</th>
                <th>Statut</th>
                <th>Client</th>
                <th>Produit</th>
                <th>N° série</th>
                <th>Pays</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody>
            {table_rows}
        </tbody>
    </table>
    """

    return layout("Archives cotations", content)





def ensure_quote_fluid_columns():
    columns = [
        ("oil_catalog_part_no", "TEXT"),
        ("oil_price_per_liter", "REAL DEFAULT 0"),
        ("oil_service_count", "REAL DEFAULT 0"),
        ("oil_quantity_per_service", "REAL DEFAULT 0"),
        ("oil_packaging_mode", "TEXT DEFAULT 'consumed'"),
        ("oil_packaging_liters", "REAL DEFAULT 0"),
        ("coolant_catalog_part_no", "TEXT"),
        ("coolant_price_per_liter", "REAL DEFAULT 0"),
        ("coolant_service_count", "REAL DEFAULT 0"),
        ("coolant_quantity_per_service", "REAL DEFAULT 0"),
        ("coolant_concentrate_percent", "REAL DEFAULT 100"),
        ("coolant_packaging_mode", "TEXT DEFAULT 'consumed'"),
        ("coolant_packaging_liters", "REAL DEFAULT 0"),
        ("fluid_total", "REAL DEFAULT 0"),
        ("replace_overview_fluids", "INTEGER DEFAULT 0"),
        ("replace_imported_oil", "INTEGER DEFAULT 0"),
        ("replace_imported_coolant", "INTEGER DEFAULT 0"),
        ("pricing_trace_json", "TEXT"),
    ]

    with get_connection() as conn:
        for column_name, column_type in columns:
            try:
                conn.execute(f"ALTER TABLE quotes ADD COLUMN {column_name} {column_type}")
                conn.commit()
            except Exception:
                pass



def get_import_control_html(conn, quote):
    quote_id = quote["id"]
    currency = quote["currency"] or "EUR"

    service = conn.execute("""
        SELECT service_id, service_name, included, fixed_price, calculated_price, source_excel, notes
        FROM quote_services
        WHERE quote_id = ? AND service_id = '2,2'
    """, (quote_id,)).fetchone()

    settings = get_settings_dict()

    messages_ok = []
    messages_warn = []
    messages_info = []

    if service and is_locked_imported_service(service):
        messages_ok.append(
            f"Service 2,2 détecté depuis l’import Volvo / Overview, coché et verrouillé. "
            f"Montant Overview repris : {fmt_money(service['fixed_price'], currency)}."
        )
    else:
        messages_warn.append(
            "Service 2,2 non détecté comme import Volvo / Overview. Vérifier le fichier importé."
        )

    if not quote["total_hours"] or float(quote["total_hours"] or 0) <= 0:
        messages_warn.append("Heures contrat non renseignées : le prix final contrat n’est pas complet.")

    if not quote["hours_per_year"] or float(quote["hours_per_year"] or 0) <= 0:
        messages_warn.append("Heures/an non renseignées : le mensuel et le prix/heure ne peuvent pas être calculés correctement.")

    if not quote["labour_rate"] or float(quote["labour_rate"] or 0) <= 0:
        messages_warn.append("Taux horaire main-d’œuvre non renseigné.")

    messages_info.append(f"Pièces importées : {fmt_money(quote['total_parts'], currency)}.")
    messages_info.append(f"Main-d’œuvre importée : {fmt_money(quote['total_labour'], currency)}.")
    messages_info.append(f"Divers importé : {fmt_money(quote['total_misc'], currency)}.")

    messages_info.append(f"Marge main-d’œuvre logiciel : {settings.get('labour_margin_percent', 0)} %.")
    messages_info.append(f"Frais admin logiciel : {settings.get('admin_fee_percent', 0)} %.")
    messages_info.append(f"Frais logistique logiciel : {settings.get('logistics_fee_percent', 0)} %.")
    messages_info.append(
        f"Indexation pièces logiciel : année 2 = {settings.get('indexation_parts_year_2', 0)} %, "
        f"année 3 = {settings.get('indexation_parts_year_3', 0)} %."
    )

    def li(items):
        return "".join(f"<li>{item}</li>" for item in items)

    status_title = "✅ Import contrôlé"
    status_class = "ok"
    if messages_warn:
        status_title = "⚠️ Import à compléter"
        status_class = "warning"

    return f"""
    <div class="card {status_class}">
        <h3>{status_title}</h3>
        {f'<h4>Validé</h4><ul>{li(messages_ok)}</ul>' if messages_ok else ''}
        {f'<h4>À vérifier / compléter</h4><ul>{li(messages_warn)}</ul>' if messages_warn else ''}
        <h4>Paramètres appliqués</h4>
        <ul>{li(messages_info)}</ul>
    </div>
    """


@app.get("/quote/{quote_id}/inputs", response_class=HTMLResponse)
def quote_inputs_page(quote_id: int, request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    init_db()
    ensure_quote_services(quote_id)
    ensure_quote_fluid_columns()
    with get_connection() as conn:
        quote = get_quote_for_active_company_request(conn, quote_id, request)

        if quote is None:
            return quote_access_denied_response(quote_id)

        import_control_html = get_import_control_html(conn, quote)
        pricing_result_html = get_pricing_result_html(quote)

        imported_oil_row = conn.execute(
            """
            SELECT id, quantity, description, part_number
            FROM quote_lines
            WHERE quote_id = ?
              AND COALESCE(quantity, 0) > 0
              AND (
                    lower(trim(COALESCE(description, ''))) = 'engine oil'
                 OR TRIM(COALESCE(part_number, '')) IN (
                        '24567220', '24567221', '24567222', '54419768'
                    )
              )
            LIMIT 1
            """,
            (quote_id,),
        ).fetchone()

        imported_coolant_row = conn.execute(
            """
            SELECT id, quantity, description, part_number
            FROM quote_lines
            WHERE quote_id = ?
              AND COALESCE(quantity, 0) > 0
              AND (
                    lower(trim(COALESCE(description, ''))) = 'volvo coolant ready mixed'
                 OR TRIM(COALESCE(part_number, '')) IN (
                        '22567233', '22567259', '22567215',
                        '24712786', '24712788', '24712790',
                        '24712783', '22567261', '22567217'
                    )
              )
            LIMIT 1
            """,
            (quote_id,),
        ).fetchone()

    imported_oil = imported_oil_row is not None
    imported_coolant = imported_coolant_row is not None

    replace_imported_oil = bool(quote["replace_imported_oil"])
    replace_imported_coolant = bool(quote["replace_imported_coolant"])

    oil_locked = imported_oil and not replace_imported_oil
    coolant_locked = imported_coolant and not replace_imported_coolant

    oil_readonly = "readonly" if oil_locked else ""
    coolant_readonly = "readonly" if coolant_locked else ""

    oil_style = (
        "opacity:0.55; background:#f1f1f1;"
        if oil_locked else ""
    )
    coolant_style = (
        "opacity:0.55; background:#f1f1f1;"
        if coolant_locked else ""
    )

    oil_status = (
        f"Huile importee detectee : {float(imported_oil_row['quantity'] or 0):g} unite(s)."
        if imported_oil
        else "Aucune huile importee detectee."
    )

    coolant_status = (
        f"Coolant importe detecte : {float(imported_coolant_row['quantity'] or 0):g} unite(s)."
        if imported_coolant
        else "Aucun coolant importe detecte."
    )

    oil_catalog_items = [
        item
        for item in search_engine_oil_catalog_items()
        if float(item.get("suggested_packaging_liters") or 0) > 0
    ]

    coolant_catalog_items = [
        item
        for item in search_engine_coolant_catalog_items()
        if float(item.get("suggested_packaging_liters") or 0) > 0
    ]

    selected_oil_part = str(quote["oil_catalog_part_no"] or "")
    selected_coolant_part = str(quote["coolant_catalog_part_no"] or "")

    selected_coolant_type = ""
    for item in coolant_catalog_items:
        if str(item.get("part_no") or "") == selected_coolant_part:
            selected_coolant_type = str(
                item.get("coolant_type_label") or ""
            ).strip()
            break

    imported_coolant_part = (
        str(imported_coolant_row["part_number"] or "").strip()
        if imported_coolant
        else ""
    )

    imported_coolant_type = ""
    if imported_coolant_part:
        for item in coolant_catalog_items:
            if str(item.get("part_no") or "") == imported_coolant_part:
                imported_coolant_type = str(
                    item.get("coolant_type_label") or ""
                ).strip()
                break

    def coolant_family(type_label):
        value = str(type_label or "").strip().lower()

        if value.startswith("vert"):
            return "Vert"

        if value.startswith("vcs-2 orange"):
            return "VCS-2 orange"

        return ""

    selected_coolant_family = coolant_family(selected_coolant_type)
    imported_coolant_family = coolant_family(imported_coolant_type)

    selected_coolant_type_html = ""
    if selected_coolant_part:
        selected_label = selected_coolant_type or "Type non identifie"
        selected_coolant_type_html = (
            "<p style='margin:6px 0;'>"
            "<strong>Reference selectionnee :</strong> "
            f"{selected_label}"
            "</p>"
        )

    imported_coolant_type_html = ""
    if imported_coolant:
        imported_label = imported_coolant_type or "Type non identifiable depuis le fichier Volvo"
        imported_coolant_type_html = (
            "<p style='margin:6px 0;'>"
            "<strong>Coolant importe :</strong> "
            f"{imported_label}"
            "</p>"
        )

    coolant_compatibility_html = ""

    if (
        imported_coolant_family
        and selected_coolant_family
        and imported_coolant_family != selected_coolant_family
    ):
        coolant_compatibility_html = (
            "<div style='"
            "margin:10px 0 14px 0;"
            "padding:12px 14px;"
            "border:1px solid #c62828;"
            "border-radius:8px;"
            "background:#ffebee;"
            "color:#8e0000;"
            "'>"
            "<strong>ALERTE COMPATIBILITE COOLANT</strong><br>"
            f"Le coolant importe est de type {imported_coolant_family}, "
            f"alors que la reference selectionnee est {selected_coolant_family}. "
            "Ces familles ne doivent pas etre melangees sans procedure adaptee "
            "de vidange/rincage."
            "</div>"
        )

    elif (
        imported_coolant
        and not imported_coolant_family
        and selected_coolant_family
    ):
        coolant_compatibility_html = (
            "<div style='"
            "margin:10px 0 14px 0;"
            "padding:12px 14px;"
            "border:1px solid #d6a000;"
            "border-radius:8px;"
            "background:#fff8dd;"
            "color:#6b5200;"
            "'>"
            "<strong>Compatibilite coolant non verifiable automatiquement</strong><br>"
            "Le fichier Volvo indique un coolant ready mixed mais ne fournit "
            "aucune reference permettant de determiner s'il s'agit de Vert "
            "ou de VCS-2 orange. Verifier le type present dans le moteur avant remplacement."
            "</div>"
        )

    oil_packaging_liters = 0
    for item in oil_catalog_items:
        if str(item.get("part_no") or "") == selected_oil_part:
            oil_packaging_liters = float(
                item.get("suggested_packaging_liters") or 0
            )
            break

    coolant_packaging_liters = 0
    for item in coolant_catalog_items:
        if str(item.get("part_no") or "") == selected_coolant_part:
            coolant_packaging_liters = float(
                item.get("suggested_packaging_liters") or 0
            )
            break

    oil_options = [
        '<option value="">-- Choisir une reference huile --</option>'
    ]

    for item in oil_catalog_items:
        part_no = str(item.get("part_no") or "")
        liters = float(item.get("suggested_packaging_liters") or 0)
        catalog_price = float(item.get("price_excl_vat") or 0)
        price_liter = catalog_price / liters if liters else 0
        selected = "selected" if part_no == selected_oil_part else ""

        oil_options.append(
            f'<option value="{part_no}" '
            f'data-price-liter="{price_liter:.6f}" {selected}>'
            f'{part_no} | {liters:g} L | '
            f'{catalog_price:.2f} EUR | {price_liter:.2f} EUR/L'
            f'</option>'
        )

    coolant_options = [
        '<option value="">-- Choisir une reference coolant --</option>'
    ]

    for item in coolant_catalog_items:
        part_no = str(item.get("part_no") or "")
        liters = float(item.get("suggested_packaging_liters") or 0)
        catalog_price = float(item.get("price_excl_vat") or 0)
        price_liter = catalog_price / liters if liters else 0
        coolant_type = str(item.get("coolant_type_label") or "").strip()
        selected = "selected" if part_no == selected_coolant_part else ""

        label = coolant_type or "Type non identifie"

        coolant_options.append(
            f'<option value="{part_no}" '
            f'data-price-liter="{price_liter:.6f}" {selected}>'
            f'{part_no} | {label} | {liters:g} L | '
            f'{catalog_price:.2f} EUR | {price_liter:.2f} EUR/L'
            f'</option>'
        )

    oil_catalog_options_html = "".join(oil_options)
    coolant_catalog_options_html = "".join(coolant_options)

    contract_years = ""
    if quote["total_hours"] and quote["hours_per_year"]:
        contract_years = quote["total_hours"] / quote["hours_per_year"]

    content = f"""
    <h2>Données contrat / moteur ID {quote_id}</h2>

    <form action="/quote/{quote_id}/inputs" method="post">
        <h3>Informations client, moteur et contrat</h3>
        <div class="card grid">
            <label>Client<input type="text" name="customer_name" value="{quote['customer_name'] or ''}"></label>
            <label>Désignation produit<input type="text" name="product_designation" value="{quote['product_designation'] or ''}"></label>
            <label>Numéro de série moteur<input type="text" name="engine_serial_number" value="{quote['engine_serial_number'] or ''}"></label>
            <label>Nom produit<input type="text" name="product_name" value="{quote['product_name'] or ''}"></label>
            <label>Pays<input type="text" name="country" value="{quote['country'] or ''}"></label>
            <label>Statut<select name="status">
                <option value="draft" {'selected' if quote['status'] == 'draft' else ''}>draft</option>
                <option value="sent" {'selected' if quote['status'] == 'sent' else ''}>sent</option>
                <option value="accepted" {'selected' if quote['status'] == 'accepted' else ''}>accepted</option>
                <option value="refused" {'selected' if quote['status'] == 'refused' else ''}>refused</option>
                <option value="archived" {'selected' if quote['status'] == 'archived' else ''}>archived</option>
            </select></label>
        </div>
        <h3>Contrat & coûts importés</h3>
        <div class="card grid">
            <label>Duree contrat calculee<input type="number" step="0.01" value="{fmt_number(contract_years)}" disabled></label>
            <label>Heures moteur contrat<input type="number" step="0.01" name="total_hours" value="{fmt_number(quote['total_hours'])}"></label>
            <label>Heures moteur par an<input type="number" step="0.01" name="hours_per_year" value="{fmt_number(quote['hours_per_year'])}"></label>
            <label>Taux horaire main-d’œuvre input<input type="number" step="0.01" name="labour_rate" value="{fmt_number(quote['labour_rate'])}"></label>
            <label>Coût total pièces<input type="number" step="0.01" name="total_parts" value="{fmt_number(quote['total_parts'])}"></label>
            <label>Coût total main-d’œuvre<input type="number" step="0.01" name="total_labour" value="{fmt_number(quote['total_labour'])}"></label>
            <label>Coût divers<input type="number" step="0.01" name="total_misc" value="{fmt_number(quote['total_misc'])}"></label>

            <input
                type="hidden"
                name="replace_overview_fluids"
                value="{"1" if quote["replace_overview_fluids"] else ""}"
            >

            <h2 style="
                grid-column:1 / -1;
                margin:22px 0 4px 0;
                padding-top:18px;
                border-top:1px solid #d8dee6;
            ">Fluides de maintenance</h2>

            <div class="card" style="
                {oil_style}
                grid-column:1 / -1;
                padding:20px;
                margin:0;
                border:1px solid #d8dee6;
                border-radius:10px;
            ">
                <h3 style="margin-top:0; margin-bottom:8px;">Huile moteur</h3>

                <p class="muted">
                    {oil_status}
                </p>

                {"<p class='muted' style='margin:4px 0 10px 0;'><strong>Verrouille :</strong> huile deja presente dans le fichier Volvo.</p>" if oil_locked else ""}

                <label style="display:flex; gap:8px; align-items:center; margin-bottom:12px; opacity:1;">
                    <input
                        type="checkbox"
                        name="replace_imported_oil"
                        {"checked" if replace_imported_oil else ""}
                        {"disabled" if not imported_oil else ""}
                        onchange="this.form.submit()"
                    >
                    <span><strong>Neutraliser l'huile importee et utiliser le calcul logiciel</strong></span>
                </label>

                <div class="grid">
                    <label style="grid-column:1 / -1;">
                        Reference huile Volvo
                        <input type="hidden" name="oil_packaging_liters" value="{oil_packaging_liters:g}">
                        <select
                            id="oil_catalog_part_no"
                            name="oil_catalog_part_no"
                            {"disabled" if oil_locked else ""}
                            onchange="
                                const opt = this.options[this.selectedIndex];
                                document.getElementById('oil_price_per_liter').value =
                                    opt.dataset.priceLiter || '';
                                this.form.submit();
                            "
                        >
                            {oil_catalog_options_html}
                        </select>
                    </label>

                    <label>
                        Prix huile / litre
                        <input
                            type="number"
                            step="0.01"
                            id="oil_price_per_liter"
                            name="oil_price_per_liter"
                            value="{fmt_number(quote['oil_price_per_liter'])}"
                            {oil_readonly}
                        >
                    </label>

                    <label>
                        Nb services huile
                        <input
                            type="number"
                            step="0.01"
                            name="oil_service_count"
                            value="{fmt_number(quote['oil_service_count'])}"
                            {oil_readonly}
                        >
                    </label>

                    <label>
                        Mode facturation huile
                        <select name="oil_packaging_mode" {oil_readonly} onchange="this.form.submit();">
                            <option value="consumed" {"selected" if (quote["oil_packaging_mode"] or "consumed") == "consumed" else ""}>
                                Litres consommes
                            </option>
                            <option value="package" {"selected" if quote["oil_packaging_mode"] == "package" else ""}>
                                Conditionnement complet
                            </option>
                        </select>
                        <small class="muted">
                            Conditionnement selectionne : {oil_packaging_liters:g} L
                        </small>
                    </label>

                    <label>
                        Litres huile / service
                        <input
                            type="number"
                            step="0.01"
                            name="oil_quantity_per_service"
                            value="{fmt_number(quote['oil_quantity_per_service'])}"
                            {oil_readonly}
                        >
                    </label>
                </div>
            </div>

            <div class="card" style="
                {coolant_style}
                grid-column:1 / -1;
                padding:20px;
                margin:0;
                border:1px solid #d8dee6;
                border-radius:10px;
            ">
                <h3 style="margin-top:0; margin-bottom:8px;">Coolant / liquide de refroidissement</h3>

                <p class="muted">
                    {coolant_status}
                </p>

                {imported_coolant_type_html}
                {selected_coolant_type_html}
                {coolant_compatibility_html}

                {"<p class='muted' style='margin:4px 0 10px 0;'><strong>Verrouille :</strong> coolant deja present dans le fichier Volvo.</p>" if coolant_locked else ""}

                <label style="display:flex; gap:8px; align-items:center; margin-bottom:12px; opacity:1;">
                    <input
                        type="checkbox"
                        name="replace_imported_coolant"
                        {"checked" if replace_imported_coolant else ""}
                        {"disabled" if not imported_coolant else ""}
                        onchange="this.form.submit()"
                    >
                    <span><strong>Neutraliser le coolant importe et utiliser le calcul logiciel</strong></span>
                </label>

                <div class="grid">
                    <label style="grid-column:1 / -1;">
                        Reference coolant Volvo
                        <input type="hidden" name="coolant_packaging_liters" value="{coolant_packaging_liters:g}">
                        <select
                            id="coolant_catalog_part_no"
                            name="coolant_catalog_part_no"
                            {"disabled" if coolant_locked else ""}
                            onchange="
                                const opt = this.options[this.selectedIndex];
                                document.getElementById('coolant_price_per_liter').value =
                                    opt.dataset.priceLiter || '';
                                this.form.submit();
                            "
                        >
                            {coolant_catalog_options_html}
                        </select>
                    </label>

                    <label>
                        Prix coolant / litre
                        <input
                            type="number"
                            step="0.01"
                            id="coolant_price_per_liter"
                            name="coolant_price_per_liter"
                            value="{fmt_number(quote['coolant_price_per_liter'])}"
                            {coolant_readonly}
                        >
                    </label>

                    <label>
                        Nb services coolant
                        <input
                            type="number"
                            step="0.01"
                            name="coolant_service_count"
                            value="{fmt_number(quote['coolant_service_count'])}"
                            {coolant_readonly}
                        >
                    </label>

                    <label>
                        Mode facturation coolant
                        <select name="coolant_packaging_mode" {coolant_readonly} onchange="this.form.submit();">
                            <option value="consumed" {"selected" if (quote["coolant_packaging_mode"] or "consumed") == "consumed" else ""}>
                                Litres consommes
                            </option>
                            <option value="package" {"selected" if quote["coolant_packaging_mode"] == "package" else ""}>
                                Conditionnement complet
                            </option>
                        </select>
                        <small class="muted">
                            Conditionnement selectionne : {coolant_packaging_liters:g} L
                        </small>
                    </label>

                    <label>
                        Litres circuit coolant / service
                        <input
                            type="number"
                            step="0.01"
                            name="coolant_quantity_per_service"
                            value="{fmt_number(quote['coolant_quantity_per_service'])}"
                            {coolant_readonly}
                        >
                    </label>

                    <label>
                        Part de concentre (%)
                        <input
                            type="number"
                            min="0"
                            max="100"
                            step="0.1"
                            name="coolant_concentrate_percent"
                            value="{fmt_number(quote['coolant_concentrate_percent'])}"
                            {coolant_readonly}
                        >
                        <small class="muted">
                            Utilise uniquement pour une reference concentree.
                            Ready mixed = 100 % du volume circuit.
                        </small>
                    </label>
                </div>
            </div>

            <div class="card" style="
                grid-column:1 / -1;
                margin:0;
                padding:16px 20px;
                border:1px solid #d8dee6;
                border-radius:10px;
            ">
                <label style="max-width:360px;">
                    Total huile + coolant logiciel
                    <input
                        type="number"
                        step="0.01"
                        value="{fmt_number(quote['fluid_total'])}"
                        readonly
                    >
                </label>

                <p class="muted">
                    Le rattachement financier reste provisoirement inchange.
                    Le prochain controle determinera automatiquement si chaque fluide doit etre rattache au service 2.1 ou 2.2.
                </p>
            </div>
            <label>Devise<input type="text" name="currency" value="{quote['currency'] or 'EUR'}"></label>
        </div>
        <button type="submit">Enregistrer données contrat + recalculer</button>
        <a class="button" href="/quote/{quote_id}/services">Construction de l’offre</a>
        <a class="button secondary" href="/">Retour offres contrats</a>
    </form>

    {import_control_html}

    {pricing_result_html}
    """
    return layout("Données contrat / moteur", content)

@app.post("/quote/{quote_id}/inputs")
def save_quote_inputs(
    quote_id: int,
    request: Request,
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
    oil_catalog_part_no: str = Form(""),
    oil_price_per_liter: float = Form(0),
    oil_service_count: float = Form(0),
    oil_quantity_per_service: float = Form(0),
    oil_packaging_mode: str = Form('consumed'),
    oil_packaging_liters: float = Form(0),
    coolant_catalog_part_no: str = Form(""),
    coolant_price_per_liter: float = Form(0),
    coolant_service_count: float = Form(0),
    coolant_quantity_per_service: float = Form(0),
    coolant_concentrate_percent: float = Form(100),
    coolant_packaging_mode: str = Form('consumed'),
    coolant_packaging_liters: float = Form(0),
    replace_overview_fluids: str | None = Form(None),
    replace_imported_oil: str | None = Form(None),
    replace_imported_coolant: str | None = Form(None),
    currency: str = Form("EUR"),
):
    login_response = require_login(request)
    if login_response:
        return login_response

    init_db()

    ensure_quote_fluid_columns()
    with get_connection() as conn:
        quote = get_quote_for_active_company_request(conn, quote_id, request)
        if quote is None:
            return quote_access_denied_response(quote_id)

    fluid_total = (
        (oil_price_per_liter or 0) * (oil_service_count or 0) * (oil_quantity_per_service or 0)
        + (
            (coolant_price_per_liter or 0)
            * (coolant_service_count or 0)
            * (coolant_quantity_per_service or 0)
            * (
                max(0, min(100, coolant_concentrate_percent or 100)) / 100
                if (coolant_catalog_part_no or "").strip() in {"22567215", "22567217"}
                else 1
            )
        )
    )

    total_cost = (total_parts or 0) + (total_labour or 0) + (total_misc or 0)
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE quotes
            SET customer_name=?, product_designation=?, engine_serial_number=?, product_name=?, country=?, status=?,
                total_hours=?, hours_per_year=?, labour_rate=?, total_parts=?, total_labour=?, total_misc=?,
                oil_catalog_part_no=?,
                oil_price_per_liter=?, oil_service_count=?, oil_quantity_per_service=?,
                oil_packaging_mode=?,
                oil_packaging_liters=?,
                coolant_catalog_part_no=?,
                coolant_price_per_liter=?, coolant_service_count=?, coolant_quantity_per_service=?,
                coolant_concentrate_percent=?,
                coolant_packaging_mode=?,
                coolant_packaging_liters=?,
                fluid_total=?,
                replace_overview_fluids=?,
                replace_imported_oil=?,
                replace_imported_coolant=?,
                total_cost=?, currency=?
            WHERE id=? AND company_id=?
            """,
            (customer_name.strip(), product_designation.strip(), engine_serial_number.strip(), product_name.strip(), country.strip(), status,
             total_hours, hours_per_year, labour_rate, total_parts, total_labour, total_misc,
             oil_catalog_part_no.strip() or None,
             oil_price_per_liter, oil_service_count, oil_quantity_per_service,
             oil_packaging_mode.strip() or 'consumed',
             oil_packaging_liters,
             coolant_catalog_part_no.strip() or None,
             coolant_price_per_liter, coolant_service_count, coolant_quantity_per_service,
             coolant_concentrate_percent,
             coolant_packaging_mode.strip() or 'consumed',
             coolant_packaging_liters,
             fluid_total,
             1 if replace_overview_fluids else 0,
             1 if replace_imported_oil else 0,
             1 if replace_imported_coolant else 0,
             total_cost, currency.strip() or "EUR", quote_id, get_active_company_id_for_request(request)),
        )
        conn.commit()

    regenerate_quote(quote_id)
    run_command([sys.executable, "backend/app/apply_pricing.py", str(quote_id)])
    return RedirectResponse(url=f"/quote/{quote_id}/inputs", status_code=303)


def is_locked_imported_service(row):
    source = str(row["source_excel"] or "").lower()
    notes = str(row["notes"] or "").lower()
    return (
        "overview" in source
        or "service detecte depuis import volvo" in notes
        or "service détecté depuis import volvo" in notes
    )


@app.get("/quote/{quote_id}/services", response_class=HTMLResponse)
def quote_services_page(quote_id: int, request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    init_db()
    ensure_quote_services(quote_id)

    with get_connection() as conn:
        quote = get_quote_for_active_company_request(conn, quote_id, request)

        if quote is None:
            return quote_access_denied_response(quote_id)

        services = conn.execute("SELECT * FROM quote_services WHERE quote_id = ? ORDER BY service_id", (quote_id,)).fetchall()

    currency = quote["currency"] or "EUR"

    rows = ""
    for s in services:
        locked = is_locked_imported_service(s)
        checked = "checked" if s["included"] or locked else ""
        disabled = "disabled" if locked else ""
        locked_hidden = f'<input type="hidden" name="included_{s["id"]}" value="1">' if locked else ""
        locked_badge = "<br><span class=\"muted\"><strong>Import Volvo - verrouille</strong></span>" if locked else ""
        readonly = "readonly" if locked else ""
        select_disabled = "disabled" if locked else ""
        travel_hidden = f'<input type="hidden" name="travel_{s["id"]}" value="{s["extra_travel"] or "Exclude"}">' if locked else ""
        yes_selected = "selected" if str(s["extra_travel"]).lower() == "yes" else ""
        excl_selected = "selected" if str(s["extra_travel"]).lower() != "yes" else ""
        rows += f"""
        <tr>
            <td>{locked_hidden}<input type="checkbox" name="included_{s['id']}" {checked} {disabled}></td>
            <td><strong>{s['service_id']}</strong><br><span class="muted">{s['source_excel'] or ''}</span>{locked_badge}</td>
            <td>{s['service_group']}</td>
            <td>{s['service_name']}</td>
            <td><input class="small-input" type="number" step="0.01" name="time_{s['id']}" value="{fmt_number(s['work_time_hours'])}" {readonly}></td>
            <td><input class="small-input" type="number" step="0.01" name="qty_{s['id']}" value="{fmt_number(s['quantity'])}" {readonly}></td>
            <td><input class="small-input" type="number" step="0.01" name="unit_{s['id']}" value="{fmt_number(s['unit_price'])}" {readonly}></td>
            <td><input class="small-input" type="number" step="0.01" name="fixed_{s['id']}" value="{fmt_number(s['fixed_price'])}" {readonly}></td>
            <td>{travel_hidden}<select class="wide-input" name="travel_{s['id']}" {select_disabled}><option value="Exclude" {excl_selected}>Exclude</option><option value="Yes" {yes_selected}>Yes</option></select></td>
            <td>{fmt_money(s['calculated_price'], currency)}</td>
        </tr>"""

    content = f"""
    <h2>Prestations incluses au contrat & temps — Devis ID {quote_id}</h2>
    
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
        <button type="submit">Enregistrer prestations + recalculer</button>
        <a class="button secondary" href="/quote/{quote_id}/inputs">Retour données contrat</a>
        <a class="button secondary" href="/">Historique</a>
    </form>"""
    return layout("Prestations incluses au contrat & temps", content)

@app.post("/quote/{quote_id}/services")
async def save_quote_services(quote_id: int, request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    init_db()
    ensure_quote_services(quote_id)

    with get_connection() as conn:
        quote = get_quote_for_active_company_request(conn, quote_id, request)
        if quote is None:
            return quote_access_denied_response(quote_id)

    form = await request.form()

    with get_connection() as conn:
        services = conn.execute("SELECT * FROM quote_services WHERE quote_id = ?", (quote_id,)).fetchall()
        for s in services:
            row_id = s["id"]
            service_id = s["service_id"]
            if is_locked_imported_service(s):
                included = 1
            else:
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
                WHERE id=? AND quote_id=?
                """,
                (included, work_time, qty, unit, fixed, travel, row_id, quote_id),
            )

        conn.commit()

    regenerate_quote(quote_id)
    return RedirectResponse(url=f"/quote/{quote_id}/services", status_code=303)

def regenerate_quote(quote_id):
    run_command([sys.executable, "backend/app/apply_pricing.py", str(quote_id)])
    run_command([sys.executable, "backend/app/export_quote_html.py", str(quote_id)])
    run_command([sys.executable, "backend/app/export_quote_pdf.py", str(quote_id)])
    run_command([sys.executable, "backend/app/export_quote_dealer_html.py", str(quote_id)])
    run_command([sys.executable, "backend/app/export_quote_dealer_pdf.py", str(quote_id)])



def ensure_yearly_indexation_settings(max_years: int = 10):
    for year_number in range(1, max_years + 1):
        default_value = 0
        existing = get_settings_dict()

        parts_key = f"indexation_parts_year_{year_number}"
        labour_key = f"indexation_labour_year_{year_number}"

        if parts_key not in existing:
            set_setting(parts_key, default_value)

        if labour_key not in existing:
            set_setting(labour_key, default_value)


def build_yearly_indexation_settings_html(settings: dict, max_years: int = 10) -> str:
    rows = ""

    for year_number in range(1, max_years + 1):
        parts_key = f"indexation_parts_year_{year_number}"
        labour_key = f"indexation_labour_year_{year_number}"

        parts_value = settings.get(parts_key, 0)
        labour_value = settings.get(labour_key, 0)

        note = ""
        if year_number == 1:
            note = "<div class='small'>Année de départ : généralement 0 %.</div>"

        rows += f"""
        <tr>
            <td><strong>Année {year_number}</strong>{note}</td>
            <td>
                <input type="number" step="0.01" name="{parts_key}" value="{fmt_number(parts_value)}">
            </td>
            <td>
                <input type="number" step="0.01" name="{labour_key}" value="{fmt_number(labour_value)}">
            </td>
        </tr>
        """

    return f"""
    <h3>Indexations annuelles</h3>
    <div class="card">
        <p>
            Ces valeurs remplacent l’ancienne indexation annuelle unique.
            Chaque contrat utilisera uniquement les années correspondant à sa durée calculée.
        </p>
        <table>
            <thead>
                <tr>
                    <th>Année</th>
                    <th>Indexation pièces (%)</th>
                    <th>Indexation main-d’œuvre (%)</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
    </div>
    """





# ============================================================
# V1.1 - MODULE CONTRATS
# ============================================================

def get_contract_for_current_company(request: Request, contract_id: int):
    company_id = get_active_company_id_for_request(request)

    with get_connection() as conn:
        return conn.execute(
            """
            SELECT *
            FROM contracts
            WHERE id = ?
              AND company_id = ?
            """,
            (contract_id, company_id),
        ).fetchone()


def contract_module_navigation():
    return """
    <div class="card" style="display:flex; flex-wrap:wrap; gap:8px;">
        <a class="button secondary" href="/contracts">Tableau de bord</a>
        <a class="button green" href="/contracts">Mes contrats</a>
        <span class="button secondary">Interventions</span>
        <a class="button secondary" href="/contracts/parts-forecast">Prevision pieces</a>
        <a class="button secondary" href="/contracts/planning">Planning &amp; Agenda</a>
        <a class="button secondary" href="/contracts/delivery-history">Historique diffusion</a>
        <span class="button secondary">Documents</span>
        <a class="button secondary" href="/contracts/settings/recipients">Parametres</a>
    </div>
    """


@app.get("/contracts", response_class=HTMLResponse)
def contracts_page(request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    init_db()

    company_id = get_active_company_id_for_request(request)
    company_name = get_active_company_name_for_request(request)

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM contracts
            WHERE company_id = ?
            ORDER BY id DESC
            """,
            (company_id,),
        ).fetchall()

    rows_html = ""

    for row in rows:
        currency = row["currency"] or "EUR"

        rows_html += f"""
        <tr>
            <td><strong>{row["contract_number"]}</strong></td>
            <td>{row["status"] or "-"}</td>
            <td>{row["customer_name"] or "-"}</td>
            <td>{row["product_designation"] or row["product_name"] or "-"}</td>
            <td>{row["engine_serial_number"] or "-"}</td>
            <td>{row["start_date"] or "-"}</td>
            <td>{row["planned_end_date"] or "-"}</td>
            <td>{fmt_number(row["current_engine_hours"])} h</td>
            <td>{fmt_number(row["planned_end_engine_hours"])} h</td>
            <td>{fmt_money(row["contract_total"], currency)}</td>
            <td>
                <a class="button green" href="/contract/{row['id']}">
                    Ouvrir
                </a>

                <form
                    method="post"
                    action="/contract/{row['id']}/delete"
                    style="display:inline;"
                    onsubmit="return confirm('SUPPRESSION DEFINITIVE du contrat {row["contract_number"]} et de toutes ses donnees de suivi ?');"
                >
                    <button type="submit">
                        Supprimer
                    </button>
                </form>
            </td>
        </tr>
        """

    if not rows_html:
        rows_html = """
        <tr>
            <td colspan="11">
                Aucun contrat pour le moment.
                Un contrat pourra etre cree depuis un devis accepte.
            </td>
        </tr>
        """

    content = f"""
    <h2>Contrats</h2>

    {contract_module_navigation()}

    <div class="card">
        <strong>Societe active :</strong> {company_name}
    </div>

    <div class="card">
        <h3>Mes contrats</h3>

        <div style="overflow-x:auto;">
            <table>
                <thead>
                    <tr>
                        <th>Contrat</th>
                        <th>Statut</th>
                        <th>Client</th>
                        <th>Machine / moteur</th>
                        <th>No serie</th>
                        <th>Debut</th>
                        <th>Fin prevue</th>
                        <th>Compteur actuel</th>
                        <th>Compteur fin</th>
                        <th>Montant</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
    </div>

    <a class="button secondary" href="/">
        Retour aux offres
    </a>
    """

    return layout("Contrats", content)



@app.get("/contracts/parts-forecast", response_class=HTMLResponse)
def contract_parts_forecast_page(request: Request, days: int = 365):
    login_response = require_login(request)
    if login_response:
        return login_response

    if days not in (30, 90, 180, 365):
        days = 365

    from datetime import date, timedelta
    today = date.today()
    limit_date = today + timedelta(days=days)

    init_db()

    company_id = get_active_company_id_for_request(request)
    company_name = get_active_company_name_for_request(request)

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                p.part_number,
                p.description,
                SUM(p.planned_quantity) AS total_quantity,
                COUNT(DISTINCT i.contract_id) AS contract_count,
                COUNT(DISTINCT i.id) AS intervention_count
            FROM contract_intervention_parts p
            JOIN contract_interventions i
              ON i.id = p.contract_intervention_id
            JOIN contracts c
              ON c.id = i.contract_id
            WHERE i.status = 'planned'
              AND c.company_id = ?
              AND i.planned_date IS NOT NULL
              AND i.planned_date >= ?
              AND i.planned_date <= ?
            GROUP BY p.part_number, p.description
            ORDER BY total_quantity DESC, p.part_number
            LIMIT 10
            """,
            (company_id, today.isoformat(), limit_date.isoformat()),
        ).fetchall()

    rows_html = ""

    for row in rows:
        rows_html += f"""
        <tr>
            <td><strong><a href="/contracts/parts-forecast/{row['part_number']}?days={days}">{row["part_number"] or "-"}</a></strong></td>
            <td>{row["description"] or "-"}</td>
            <td>{fmt_number(row["total_quantity"])}</td>
            <td>{row["contract_count"]}</td>
            <td>{row["intervention_count"]}</td>
        </tr>
        """

    if not rows_html:
        rows_html = """
        <tr>
            <td colspan="5">Aucune piece planifiee.</td>
        </tr>
        """

    content = f"""
    <h2>Prevision pieces</h2>

    {contract_module_navigation()}

    <div class="card">
        <strong>Societe active :</strong> {company_name}
    </div>

    <div class="card">
        <h3>Top 10 pieces a prevoir</h3>
        <div style="display:flex; flex-wrap:wrap; gap:8px; margin-bottom:12px;">
            <a class="button secondary" href="/contracts/parts-forecast?days=30">30 jours</a>
            <a class="button secondary" href="/contracts/parts-forecast?days=90">90 jours</a>
            <a class="button secondary" href="/contracts/parts-forecast?days=180">180 jours</a>
            <a class="button secondary" href="/contracts/parts-forecast?days=365">365 jours</a>
        </div>
        <p><strong>Periode affichee :</strong> {days} jours</p>

        <div style="overflow-x:auto;">
            <table>
                <thead>
                    <tr>
                        <th>Reference</th>
                        <th>Designation</th>
                        <th>Quantite prevue</th>
                        <th>Contrats</th>
                        <th>Interventions</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
    </div>
    """

    return layout("Prevision pieces", content)



@app.get("/contracts/parts-forecast/{part_number}", response_class=HTMLResponse)
def contract_parts_forecast_detail_page(
    part_number: str,
    request: Request,
    days: int = 365,
):
    login_response = require_login(request)
    if login_response:
        return login_response

    if days not in (30, 90, 180, 365):
        days = 365

    from datetime import date, timedelta

    today = date.today()
    limit_date = today + timedelta(days=days)

    init_db()

    company_id = get_active_company_id_for_request(request)

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                c.id AS contract_id,
                c.contract_number,
                c.customer_name,
                i.intervention_type,
                i.planned_date,
                i.planned_engine_hours,
                p.description,
                p.planned_quantity
            FROM contract_intervention_parts p
            JOIN contract_interventions i
              ON i.id = p.contract_intervention_id
            JOIN contracts c
              ON c.id = i.contract_id
            WHERE p.part_number = ?
              AND i.status = 'planned'
              AND c.company_id = ?
              AND i.planned_date IS NOT NULL
              AND i.planned_date >= ?
              AND i.planned_date <= ?
            ORDER BY i.planned_date, c.contract_number
            """,
            (
                part_number,
                company_id,
                today.isoformat(),
                limit_date.isoformat(),
            ),
        ).fetchall()

    rows_html = ""

    for row in rows:
        rows_html += f"""
        <tr>
            <td>
                <a href="/contract/{row["contract_id"]}">
                    {row["contract_number"]}
                </a>
            </td>
            <td>{row["customer_name"] or "-"}</td>
            <td>{row["intervention_type"] or "-"}</td>
            <td>{row["planned_date"] or "-"}</td>
            <td>{fmt_number(row["planned_engine_hours"])} h</td>
            <td>{fmt_number(row["planned_quantity"])}</td>
        </tr>
        """

    if not rows_html:
        rows_html = """
        <tr>
            <td colspan="6">Aucun besoin planifie pour cette periode.</td>
        </tr>
        """

    description = rows[0]["description"] if rows else "-"

    content = f"""
    <h2>Detail prevision piece</h2>

    {contract_module_navigation()}

    <div class="card">
        <strong>Reference :</strong> {part_number}<br>
        <strong>Designation :</strong> {description}<br>
        <strong>Periode :</strong> {days} jours
    </div>

    <div class="card">
        <a class="button secondary"
           href="/contracts/parts-forecast?days={days}">
            Retour a la prevision pieces
        </a>
    </div>

    <div class="card">
        <h3>Contrats et interventions concernes</h3>

        <div style="overflow-x:auto;">
            <table>
                <thead>
                    <tr>
                        <th>Contrat</th>
                        <th>Client</th>
                        <th>Intervention</th>
                        <th>Date prevue</th>
                        <th>Compteur prevu</th>
                        <th>Quantite</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
    </div>
    """

    return layout("Detail prevision piece", content)



@app.get("/contracts/planning", response_class=HTMLResponse)
def contracts_planning_page(
    request: Request,
    days: int = 365,
):
    login_response = require_login(request)
    if login_response:
        return login_response

    if days not in (30, 90, 180, 365):
        days = 365

    from datetime import date, timedelta

    today = date.today()
    limit_date = today + timedelta(days=days)

    init_db()

    company_id = get_active_company_id_for_request(request)
    company_name = get_active_company_name_for_request(request)

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                i.id AS intervention_id,
                i.intervention_type,
                i.planned_engine_hours,
                i.planned_date,
                c.id AS contract_id,
                c.contract_number,
                c.customer_name,
                c.product_designation,
                c.engine_serial_number
            FROM contract_interventions i
            JOIN contracts c
              ON c.id = i.contract_id
            WHERE i.status = 'planned'
              AND c.company_id = ?
              AND i.planned_date IS NOT NULL
              AND i.planned_date >= ?
              AND i.planned_date <= ?
            ORDER BY
                i.planned_date,
                c.contract_number,
                i.planned_engine_hours
            """,
            (
                company_id,
                today.isoformat(),
                limit_date.isoformat(),
            ),
        ).fetchall()

    rows_html = ""

    for row in rows:
        rows_html += f"""
        <tr>
            <td>{row["planned_date"] or "-"}</td>
            <td>
                <a href="/contract/{row["contract_id"]}">
                    {row["contract_number"]}
                </a>
            </td>
            <td>{row["customer_name"] or "-"}</td>
            <td>{row["product_designation"] or "-"}</td>
            <td>{row["engine_serial_number"] or "-"}</td>
            <td>{row["intervention_type"] or "-"}</td>
            <td>{fmt_number(row["planned_engine_hours"])} h</td>
        </tr>
        """

    if not rows_html:
        rows_html = """
        <tr>
            <td colspan="7">
                Aucune intervention planifiee sur cette periode.
            </td>
        </tr>
        """

    content = f"""
    <h2>Planning &amp; Agenda</h2>

    {contract_module_navigation()}

    <div class="card">
        <strong>Societe active :</strong> {company_name}
    </div>

    <div class="card">
        <h3>Interventions a venir</h3>

        <div style="display:flex; flex-wrap:wrap; gap:8px; margin-bottom:12px;">
            <a class="button secondary" href="/contracts/planning?days=30">30 jours</a>
            <a class="button secondary" href="/contracts/planning?days=90">90 jours</a>
            <a class="button secondary" href="/contracts/planning?days=180">180 jours</a>
            <a class="button secondary" href="/contracts/planning?days=365">365 jours</a>
        </div>

        <p>
            <strong>Periode affichee :</strong>
            {days} jours
        </p>

        <div style="overflow-x:auto;">
            <table>
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Contrat</th>
                        <th>Client</th>
                        <th>Machine / moteur</th>
                        <th>No serie</th>
                        <th>Intervention</th>
                        <th>Compteur prevu</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
    </div>
    """

    return layout("Planning & Agenda", content)




@app.get("/contracts/delivery-history", response_class=HTMLResponse)
def contract_delivery_history_page(
    request: Request,
    profile: str = "",
    status: str = "",
):
    login_response = require_login(request)
    if login_response:
        return login_response

    init_db()

    context = get_request_company_context(request)
    if not context:
        return company_context_required_page()

    company_id = get_active_company_id_for_request(request)
    company_name = get_active_company_name_for_request(request)

    from html import escape as html_escape

    profile = (profile or "").strip().lower()
    status = (status or "").strip().lower()

    allowed_profiles = {
        "",
        "atelier",
        "magasin",
        "facturation",
        "commerce",
    }

    allowed_statuses = {
        "",
        "sent",
        "error",
        "simulated",
    }

    if profile not in allowed_profiles:
        profile = ""

    if status not in allowed_statuses:
        status = ""

    sql = """
        SELECT
            l.id,
            l.created_at,
            l.sent_at,
            l.event_key,
            l.event_revision,
            l.subject,
            l.status,
            l.error_message,
            p.profile_key,
            p.profile_name,
            r.recipient_name,
            r.email
        FROM contract_delivery_log l
        JOIN contract_delivery_profiles p
          ON p.id = l.profile_id
        LEFT JOIN contract_delivery_recipients r
          ON r.id = l.recipient_id
        WHERE l.company_id = ?
    """

    params = [company_id]

    if profile:
        sql += " AND p.profile_key = ?"
        params.append(profile)

    if status:
        sql += " AND l.status = ?"
        params.append(status)

    sql += " ORDER BY l.id DESC LIMIT 500"

    with get_connection() as conn:
        rows = conn.execute(
            sql,
            params,
        ).fetchall()

    rows_html = ""

    for row in rows:
        sent_at = format_paris_datetime(
            row["sent_at"]
            or row["created_at"]
        )

        profile_name = html_escape(
            str(
                row["profile_name"]
                or row["profile_key"]
                or "-"
            )
        )

        recipient_name = html_escape(
            str(row["recipient_name"] or "")
        )

        recipient_email = html_escape(
            str(row["email"] or "-")
        )

        recipient_text = recipient_email

        if recipient_name:
            recipient_text = (
                f"{recipient_name}<br>"
                f"<span class='muted'>{recipient_email}</span>"
            )

        subject = html_escape(
            str(row["subject"] or "-")
        )

        event_key = html_escape(
            str(row["event_key"] or "-")
        )

        row_status = html_escape(
            str(row["status"] or "-")
        )

        error = html_escape(
            str(row["error_message"] or "")
        )

        if not error:
            error = "-"

        rows_html += f"""
        <tr>
            <td>{sent_at}</td>
            <td>{profile_name}</td>
            <td>{recipient_text}</td>
            <td>
                {event_key}
                <br>
                <span class="muted">
                    Revision {int(row["event_revision"] or 0)}
                </span>
            </td>
            <td>{subject}</td>
            <td><strong>{row_status}</strong></td>
            <td>{error}</td>
        </tr>
        """

    if not rows_html:
        rows_html = """
        <tr>
            <td colspan="7" class="muted">
                Aucune diffusion pour ces criteres.
            </td>
        </tr>
        """

    def selected(value, current):
        return "selected" if value == current else ""

    content = f"""
    <h2>Historique des diffusions</h2>

    {contract_module_navigation()}

    <div class="card">
        <strong>Societe active :</strong>
        {html_escape(str(company_name))}
    </div>

    <div class="card">
        <h3>Filtres</h3>

        <form method="get" action="/contracts/delivery-history">
            <div class="grid">
                <label>
                    Profil
                    <select name="profile">
                        <option value="" {selected("", profile)}>
                            Tous
                        </option>
                        <option value="atelier" {selected("atelier", profile)}>
                            Atelier
                        </option>
                        <option value="magasin" {selected("magasin", profile)}>
                            Magasin
                        </option>
                        <option value="facturation" {selected("facturation", profile)}>
                            Facturation
                        </option>
                        <option value="commerce" {selected("commerce", profile)}>
                            Commerce
                        </option>
                    </select>
                </label>

                <label>
                    Statut
                    <select name="status">
                        <option value="" {selected("", status)}>
                            Tous
                        </option>
                        <option value="sent" {selected("sent", status)}>
                            Envoye
                        </option>
                        <option value="error" {selected("error", status)}>
                            Erreur
                        </option>
                        <option value="simulated" {selected("simulated", status)}>
                            Simulation
                        </option>
                    </select>
                </label>
            </div>

            <button class="button green" type="submit">
                Filtrer
            </button>

            <a
                class="button secondary"
                href="/contracts/delivery-history"
            >
                Reinitialiser
            </a>
        </form>
    </div>

    <div class="card">
        <h3>Dernieres diffusions</h3>

        <div style="overflow-x:auto;">
            <table>
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Profil</th>
                        <th>Destinataire</th>
                        <th>Evenement</th>
                        <th>Sujet</th>
                        <th>Statut</th>
                        <th>Erreur</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>

        <p class="muted">
            Affichage limite aux 500 dernieres diffusions.
        </p>
    </div>
    """

    return layout(
        "Historique diffusions contrats",
        content,
    )


@app.get("/contracts/settings/recipients", response_class=HTMLResponse)
def contract_recipients_page(request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    init_db()

    context = get_request_company_context(request)
    if not context:
        return company_context_required_page()

    role = str(context.get("role") or "").upper()
    if role not in ("OWNER", "SUPER_ADMIN", "COMPANY_ADMIN"):
        return admin_required_page()

    company_id = get_active_company_id_for_request(request)
    company_name = get_active_company_name_for_request(request)

    import server_user_model as identity
    identity.ensure_company_delivery_profiles(company_id)

    from html import escape as html_escape

    with get_connection() as conn:
        profiles = conn.execute(
            """
            SELECT id, profile_key, profile_name, is_active
            FROM contract_delivery_profiles
            WHERE company_id = ?
            ORDER BY
                CASE profile_key
                    WHEN 'atelier' THEN 1
                    WHEN 'magasin' THEN 2
                    WHEN 'facturation' THEN 3
                    WHEN 'commerce' THEN 4
                    ELSE 99
                END
            """,
            (company_id,),
        ).fetchall()

        recipients = conn.execute(
            """
            SELECT
                r.id,
                r.profile_id,
                r.recipient_name,
                r.email,
                r.is_active,
                r.attach_ics
            FROM contract_delivery_recipients r
            JOIN contract_delivery_profiles p
              ON p.id = r.profile_id
            WHERE p.company_id = ?
            ORDER BY p.id, r.id
            """,
            (company_id,),
        ).fetchall()

        rules = conn.execute(
            """
            SELECT
                r.id,
                r.profile_id,
                r.rule_key,
                r.event_type,
                r.trigger_type,
                r.trigger_value,
                r.is_active
            FROM contract_delivery_rules r
            JOIN contract_delivery_profiles p
              ON p.id = r.profile_id
            WHERE p.company_id = ?
            ORDER BY p.id, r.id
            """,
            (company_id,),
        ).fetchall()

    recipients_by_profile = {}
    for recipient in recipients:
        recipients_by_profile.setdefault(
            int(recipient["profile_id"]),
            [],
        ).append(recipient)

    rules_by_profile = {}
    for rule in rules:
        rules_by_profile.setdefault(
            int(rule["profile_id"]),
            [],
        ).append(rule)

    profile_html = ""

    descriptions = {
        "atelier": "Interventions, informations machine et liste des pieces necessaires.",
        "magasin": "Previsions et besoins consolides en pieces.",
        "facturation": "Echeances de facturation selon les dates contractuelles.",
        "commerce": "Debut, fin et renouvellement des contrats.",
    }

    for profile in profiles:
        profile_id = int(profile["id"])
        profile_key = str(profile["profile_key"] or "")
        profile_name = html_escape(str(profile["profile_name"] or profile_key))

        rows_html = ""

        for recipient in recipients_by_profile.get(profile_id, []):
            recipient_id = int(recipient["id"])
            recipient_name = html_escape(str(recipient["recipient_name"] or ""))
            email = html_escape(str(recipient["email"] or ""))
            is_recipient_active = bool(int(recipient["is_active"] or 0))
            active_text = "Oui" if is_recipient_active else "Non"
            toggle_recipient_text = "Desactiver" if is_recipient_active else "Activer"
            ics_text = "Oui" if int(recipient["attach_ics"] or 0) else "Non"

            rows_html += f"""
            <tr>
                <td>{recipient_name or '-'}</td>
                <td>{email}</td>
                <td>{active_text}</td>
                <td>{ics_text}</td>
                <td style="white-space:nowrap;">
                    <form action="/contracts/settings/recipients/{recipient_id}/toggle"
                          method="post"
                          style="display:inline;">
                        <button class="button secondary" type="submit">
                            {toggle_recipient_text}
                        </button>
                    </form>

                    <form action="/contracts/settings/recipients/{recipient_id}/delete"
                          method="post"
                          style="display:inline;"
                          onsubmit="return confirm('Supprimer ce destinataire ?');">
                        <button type="submit">Supprimer</button>
                    </form>
                </td>
            </tr>
            """

        if not rows_html:
            rows_html = """
            <tr>
                <td colspan="5" class="muted">
                    Aucun destinataire configure.
                </td>
            </tr>
            """

        description = descriptions.get(profile_key, "")

        rules_rows_html = ""

        for rule in rules_by_profile.get(profile_id, []):
            rule_id = int(rule["id"])
            event_type = str(rule["event_type"] or "")
            trigger_type = str(rule["trigger_type"] or "")
            trigger_value = float(rule["trigger_value"] or 0)
            is_rule_active = bool(int(rule["is_active"] or 0))
            active_text = "Oui" if is_rule_active else "Non"
            toggle_rule_text = "Desactiver" if is_rule_active else "Activer"

            if trigger_type == "hours_before":
                rule_label = f"{trigger_value:g} h avant intervention"
            elif event_type == "billing":
                rule_label = f"{trigger_value:g} jours avant echeance de facturation"
            elif event_type == "contract_end":
                rule_label = f"{trigger_value:g} jours avant fin / renouvellement du contrat"
            else:
                rule_label = f"{trigger_value:g} jours avant intervention"

            rules_rows_html += f"""
            <tr>
                <td>{rule_label}</td>
                <td>{active_text}</td>
                <td style="white-space:nowrap;">
                    <form action="/contracts/settings/rules/{rule_id}/toggle"
                          method="post"
                          style="display:inline;">
                        <button class="button secondary" type="submit">
                            {toggle_rule_text}
                        </button>
                    </form>

                    <form action="/contracts/settings/rules/{rule_id}/delete"
                          method="post"
                          style="display:inline;"
                          onsubmit="return confirm('Supprimer cette regle ?');">
                        <button type="submit">Supprimer</button>
                    </form>
                </td>
            </tr>
            """

        if not rules_rows_html:
            rules_rows_html = """
            <tr>
                <td colspan="3" class="muted">
                    Aucune regle automatique configuree.
                </td>
            </tr>
            """

        if profile_key in ("atelier", "magasin"):
            event_type_value = "intervention"
            trigger_field_html = """
                <label>
                    Type de seuil
                    <select name="trigger_type">
                        <option value="hours_before">Heures avant intervention</option>
                        <option value="days_before">Jours avant intervention</option>
                    </select>
                </label>
            """
        elif profile_key == "facturation":
            event_type_value = "billing"
            trigger_field_html = """
                <input type="hidden" name="trigger_type" value="days_before">
                <label>
                    Type de seuil
                    <input value="Jours avant echeance contractuelle" readonly>
                </label>
            """
        else:
            event_type_value = "contract_end"
            trigger_field_html = """
                <input type="hidden" name="trigger_type" value="days_before">
                <label>
                    Type de seuil
                    <input value="Jours avant fin / renouvellement" readonly>
                </label>
            """

        profile_html += f"""
        <div class="card">
            <h3>{profile_name}</h3>
            <p class="muted">{description}</p>

            <form
                action="/contracts/settings/profiles/{profile_id}/test"
                method="post"
                style="margin:12px 0 18px 0;"
                onsubmit="return confirm('Envoyer un email TEST aux destinataires actifs de ce profil ?');"
            >
                <button class="button secondary" type="submit">
                    Envoyer un test
                </button>
            </form>

            <div style="overflow-x:auto;">
                <table>
                    <thead>
                        <tr>
                            <th>Nom</th>
                            <th>Email</th>
                            <th>Actif</th>
                            <th>Agenda .ics</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>

            <form action="/contracts/settings/recipients/add"
                  method="post"
                  style="margin-top:16px;">
                <input type="hidden" name="profile_id" value="{profile_id}">

                <div class="grid">
                    <label>
                        Nom
                        <input type="text" name="recipient_name">
                    </label>

                    <label>
                        Email
                        <input type="email" name="email" required>
                    </label>

                    <label>
                        Ajouter une invitation agenda .ics
                        <select name="attach_ics">
                            <option value="1">Oui</option>
                            <option value="0">Non</option>
                        </select>
                    </label>
                </div>

                <button type="submit">Ajouter le destinataire</button>
            </form>

            <hr style="margin:24px 0;">

            <h4>Regles automatiques</h4>

            <div style="overflow-x:auto;">
                <table>
                    <thead>
                        <tr>
                            <th>Declenchement</th>
                            <th>Actif</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rules_rows_html}
                    </tbody>
                </table>
            </div>

            <form action="/contracts/settings/rules/add"
                  method="post"
                  style="margin-top:16px;">

                <input type="hidden" name="profile_id" value="{profile_id}">
                <input type="hidden" name="event_type" value="{event_type_value}">

                <div class="grid">
                    {trigger_field_html}

                    <label>
                        Valeur du seuil
                        <input
                            type="number"
                            name="trigger_value"
                            min="0"
                            step="1"
                            required
                        >
                    </label>
                </div>

                <button type="submit">Ajouter la regle</button>
            </form>
        </div>
        """

    content = f"""
    <h2>Parametres contrats - Diffusion</h2>

    {contract_module_navigation()}

    <div class="card">
        <strong>Societe active :</strong> {html_escape(str(company_name))}
        <p class="muted">
            Chaque societe possede ses propres destinataires.
            Une meme personne peut etre ajoutee a plusieurs profils.
        </p>
    </div>

    {profile_html}
    """

    return layout("Diffusion contrats", content)



@app.post("/contracts/settings/profiles/{profile_id}/test", response_class=HTMLResponse)
def contract_delivery_profile_test(
    profile_id: int,
    request: Request,
):
    login_response = require_login(request)
    if login_response:
        return login_response

    init_db()

    context = get_request_company_context(request)
    if not context:
        return company_context_required_page()

    role = str(
        context.get("role") or ""
    ).upper()

    if role not in (
        "OWNER",
        "SUPER_ADMIN",
        "COMPANY_ADMIN",
    ):
        return admin_required_page()

    company_id = get_active_company_id_for_request(
        request
    )

    company_name = get_active_company_name_for_request(
        request
    )

    with get_connection() as conn:
        profile_row = conn.execute(
            """
            SELECT
                id,
                profile_key,
                profile_name
            FROM contract_delivery_profiles
            WHERE id = ?
              AND company_id = ?
            """,
            (
                profile_id,
                company_id,
            ),
        ).fetchone()

        if not profile_row:
            return HTMLResponse(
                layout(
                    "Profil introuvable",
                    """
                    <div class="card">
                        Profil de diffusion introuvable
                        ou non autorise.
                    </div>
                    """,
                ),
                status_code=404,
            )

        recipients = conn.execute(
            """
            SELECT
                id,
                recipient_name,
                email
            FROM contract_delivery_recipients
            WHERE profile_id = ?
              AND is_active = 1
            ORDER BY id
            """,
            (profile_id,),
        ).fetchall()

    if not recipients:
        return HTMLResponse(
            layout(
                "Aucun destinataire",
                f"""
                <div class="card">
                    <h3>Aucun destinataire actif</h3>
                    <p>
                        Ajoute ou active au moins un
                        destinataire pour ce profil.
                    </p>

                    <a
                        class="button secondary"
                        href="/contracts/settings/recipients"
                    >
                        Retour aux parametres
                    </a>
                </div>
                """,
            ),
            status_code=400,
        )

    from datetime import date, datetime, timedelta
    from html import escape as html_escape

    from contract_delivery_mail import (
        build_delivery_email,
    )

    from contract_delivery_processor import (
        _send_email_smtp,
        _smtp_settings,
        DEFAULT_FROM_ADDRESS,
    )

    profile_key = str(
        profile_row["profile_key"] or ""
    )

    profile_name = str(
        profile_row["profile_name"]
        or profile_key
    )

    today = date.today()
    tomorrow = today + timedelta(days=1)

    uid_stamp = datetime.now().strftime(
        "%Y%m%d%H%M%S%f"
    )

    ics_content = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Dealer Quote Manager//Test//FR\r\n"
        "CALSCALE:GREGORIAN\r\n"
        "METHOD:PUBLISH\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:dqm:test:{company_id}:{profile_id}:{uid_stamp}"
        "@dealer-quote-manager\r\n"
        "SEQUENCE:0\r\n"
        f"DTSTART;VALUE=DATE:{today.strftime('%Y%m%d')}\r\n"
        f"DTEND;VALUE=DATE:{tomorrow.strftime('%Y%m%d')}\r\n"
        f"SUMMARY:TEST diffusion {profile_name}\r\n"
        f"DESCRIPTION:Test de diffusion Dealer Quote Manager - "
        f"{profile_name}\r\n"
        "STATUS:CONFIRMED\r\n"
        "TRANSP:TRANSPARENT\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    settings = _smtp_settings()

    from_address = (
        settings["user"]
        or DEFAULT_FROM_ADDRESS
    )

    subject = (
        f"[TEST] Diffusion {profile_name} - "
        f"{company_name}"
    )

    body_text = (
        "TEST DE DIFFUSION\n\n"
        f"Societe : {company_name}\n"
        f"Profil : {profile_name}\n\n"
        "Ce message confirme le bon fonctionnement "
        "de la diffusion email de Dealer Quote Manager.\n\n"
        "Aucune echeance contractuelle reelle "
        "n'est associee a ce test."
    )

    sent = []
    errors = []

    for recipient in recipients:
        email = str(
            recipient["email"] or ""
        ).strip()

        if not email:
            continue

        message = build_delivery_email(
            from_address=from_address,
            to_address=email,
            subject=subject,
            body_text=body_text,
            ics_content=ics_content,
            event_key=f"test-{profile_key}",
        )

        test_event_key = (
            f"test:{profile_key}:{uid_stamp}:{recipient['id']}"
        )
        test_event_uid = (
            f"dqm:test:{company_id}:{profile_id}:"
            f"{uid_stamp}:{recipient['id']}"
            "@dealer-quote-manager"
        )

        try:
            _send_email_smtp(message)
            sent.append(email)

            with get_connection() as log_conn:
                log_conn.execute(
                    """
                    INSERT INTO contract_delivery_log (
                        company_id,
                        profile_id,
                        recipient_id,
                        rule_id,
                        event_key,
                        event_uid,
                        event_revision,
                        subject,
                        status,
                        sent_at,
                        error_message
                    )
                    VALUES (
                        ?, ?, ?, NULL, ?, ?, 0, ?,
                        'sent',
                        CURRENT_TIMESTAMP,
                        NULL
                    )
                    """,
                    (
                        company_id,
                        profile_id,
                        recipient["id"],
                        test_event_key,
                        test_event_uid,
                        subject,
                    ),
                )
                log_conn.commit()

        except Exception as exc:
            error_text = str(exc)

            errors.append(
                (
                    email,
                    error_text,
                )
            )

            with get_connection() as log_conn:
                log_conn.execute(
                    """
                    INSERT INTO contract_delivery_log (
                        company_id,
                        profile_id,
                        recipient_id,
                        rule_id,
                        event_key,
                        event_uid,
                        event_revision,
                        subject,
                        status,
                        sent_at,
                        error_message
                    )
                    VALUES (
                        ?, ?, ?, NULL, ?, ?, 0, ?,
                        'error',
                        NULL,
                        ?
                    )
                    """,
                    (
                        company_id,
                        profile_id,
                        recipient["id"],
                        test_event_key,
                        test_event_uid,
                        subject,
                        error_text,
                    ),
                )
                log_conn.commit()

    sent_html = ""

    for email in sent:
        sent_html += (
            "<li>"
            + html_escape(email)
            + "</li>"
        )

    error_html = ""

    for email, error in errors:
        error_html += (
            "<li>"
            + html_escape(email)
            + " : "
            + html_escape(error)
            + "</li>"
        )

    if not sent_html:
        sent_html = "<li>Aucun</li>"

    if not error_html:
        error_html = "<li>Aucune</li>"

    content = f"""
    <h2>Test diffusion - {html_escape(profile_name)}</h2>

    {contract_module_navigation()}

    <div class="card">
        <h3>Resultat du test</h3>

        <p>
            <strong>Profil :</strong>
            {html_escape(profile_name)}
        </p>

        <p>
            <strong>Envoyes :</strong>
        </p>
        <ul>
            {sent_html}
        </ul>

        <p>
            <strong>Erreurs :</strong>
        </p>
        <ul>
            {error_html}
        </ul>

        <p class="muted">
            Ce test est ajoute a l'historique de diffusion
            et clairement identifie par [TEST].
        </p>

        <a
            class="button secondary"
            href="/contracts/settings/recipients"
        >
            Retour aux parametres
        </a>
    </div>
    """

    return layout(
        "Test diffusion contrats",
        content,
    )


@app.post("/contracts/settings/recipients/add")
async def contract_recipient_add(
    request: Request,
    profile_id: int = Form(...),
    recipient_name: str = Form(""),
    email: str = Form(...),
    attach_ics: int = Form(1),
):
    login_response = require_login(request)
    if login_response:
        return login_response

    context = get_request_company_context(request)
    if not context:
        return company_context_required_page()

    role = str(context.get("role") or "").upper()
    if role not in ("OWNER", "SUPER_ADMIN", "COMPANY_ADMIN"):
        return admin_required_page()

    company_id = get_active_company_id_for_request(request)

    email = (email or "").strip().lower()
    recipient_name = (recipient_name or "").strip()

    if not email:
        return HTMLResponse(
            layout(
                "Email invalide",
                "<div class='card'>Une adresse email est obligatoire.</div>",
            ),
            status_code=400,
        )

    with get_connection() as conn:
        profile = conn.execute(
            """
            SELECT id
            FROM contract_delivery_profiles
            WHERE id = ?
              AND company_id = ?
            """,
            (profile_id, company_id),
        ).fetchone()

        if not profile:
            return HTMLResponse(
                layout(
                    "Profil invalide",
                    "<div class='card'>Profil destinataire introuvable.</div>",
                ),
                status_code=404,
            )

        conn.execute(
            """
            INSERT OR IGNORE INTO contract_delivery_recipients (
                profile_id,
                recipient_name,
                email,
                is_active,
                attach_ics
            )
            VALUES (?, ?, ?, 1, ?)
            """,
            (
                profile_id,
                recipient_name,
                email,
                1 if int(attach_ics) else 0,
            ),
        )

        conn.commit()

    return RedirectResponse(
        url="/contracts/settings/recipients",
        status_code=303,
    )


@app.post("/contracts/settings/recipients/{recipient_id}/toggle")
def contract_recipient_toggle(recipient_id: int, request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    context = get_request_company_context(request)
    if not context:
        return company_context_required_page()

    role = str(context.get("role") or "").upper()
    if role not in ("OWNER", "SUPER_ADMIN", "COMPANY_ADMIN"):
        return admin_required_page()

    company_id = get_active_company_id_for_request(request)

    with get_connection() as conn:
        recipient = conn.execute(
            """
            SELECT r.id, r.is_active
            FROM contract_delivery_recipients r
            JOIN contract_delivery_profiles p
              ON p.id = r.profile_id
            WHERE r.id = ?
              AND p.company_id = ?
            """,
            (recipient_id, company_id),
        ).fetchone()

        if not recipient:
            return HTMLResponse(
                layout(
                    "Destinataire introuvable",
                    "<div class='card'>Destinataire introuvable.</div>",
                ),
                status_code=404,
            )

        new_value = 0 if int(recipient["is_active"] or 0) else 1

        conn.execute(
            """
            UPDATE contract_delivery_recipients
            SET is_active = ?
            WHERE id = ?
            """,
            (new_value, recipient_id),
        )

        conn.commit()

    return RedirectResponse(
        url="/contracts/settings/recipients",
        status_code=303,
    )


@app.post("/contracts/settings/recipients/{recipient_id}/delete")
def contract_recipient_delete(recipient_id: int, request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    context = get_request_company_context(request)
    if not context:
        return company_context_required_page()

    role = str(context.get("role") or "").upper()
    if role not in ("OWNER", "SUPER_ADMIN", "COMPANY_ADMIN"):
        return admin_required_page()

    company_id = get_active_company_id_for_request(request)

    with get_connection() as conn:
        recipient = conn.execute(
            """
            SELECT r.id
            FROM contract_delivery_recipients r
            JOIN contract_delivery_profiles p
              ON p.id = r.profile_id
            WHERE r.id = ?
              AND p.company_id = ?
            """,
            (recipient_id, company_id),
        ).fetchone()

        if recipient:
            conn.execute(
                "DELETE FROM contract_delivery_recipients WHERE id = ?",
                (recipient_id,),
            )
            conn.commit()

    return RedirectResponse(
        url="/contracts/settings/recipients",
        status_code=303,
    )



@app.post("/contracts/settings/rules/add")
def contract_delivery_rule_add(
    request: Request,
    profile_id: int = Form(...),
    event_type: str = Form(...),
    trigger_type: str = Form(...),
    trigger_value: float = Form(...),
):
    login_response = require_login(request)
    if login_response:
        return login_response

    context = get_request_company_context(request)
    if not context:
        return company_context_required_page()

    role = str(context.get("role") or "").upper()
    if role not in ("OWNER", "SUPER_ADMIN", "COMPANY_ADMIN"):
        return admin_required_page()

    company_id = get_active_company_id_for_request(request)

    if trigger_value < 0:
        return HTMLResponse(
            layout(
                "Regle invalide",
                "<div class='card'>Le seuil ne peut pas etre negatif.</div>",
            ),
            status_code=400,
        )

    with get_connection() as conn:
        profile = conn.execute(
            """
            SELECT id, profile_key
            FROM contract_delivery_profiles
            WHERE id = ?
              AND company_id = ?
            """,
            (profile_id, company_id),
        ).fetchone()

        if not profile:
            return HTMLResponse(
                layout(
                    "Profil invalide",
                    "<div class='card'>Profil de diffusion introuvable.</div>",
                ),
                status_code=404,
            )

        profile_key = str(profile["profile_key"] or "")

        allowed = {
            "atelier": {
                ("intervention", "hours_before"),
                ("intervention", "days_before"),
            },
            "magasin": {
                ("intervention", "hours_before"),
                ("intervention", "days_before"),
            },
            "facturation": {
                ("billing", "days_before"),
            },
            "commerce": {
                ("contract_end", "days_before"),
            },
        }

        if (
            profile_key not in allowed
            or (event_type, trigger_type) not in allowed[profile_key]
        ):
            return HTMLResponse(
                layout(
                    "Regle invalide",
                    "<div class='card'>Cette regle n'est pas autorisee pour ce profil.</div>",
                ),
                status_code=400,
            )

        normalized_value = f"{float(trigger_value):g}"
        rule_key = f"{event_type}:{trigger_type}:{normalized_value}"

        conn.execute(
            """
            INSERT OR IGNORE INTO contract_delivery_rules (
                profile_id,
                rule_key,
                event_type,
                trigger_type,
                trigger_value,
                is_active
            )
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (
                profile_id,
                rule_key,
                event_type,
                trigger_type,
                float(trigger_value),
            ),
        )

        conn.commit()

    return RedirectResponse(
        url="/contracts/settings/recipients",
        status_code=303,
    )


@app.post("/contracts/settings/rules/{rule_id}/toggle")
def contract_delivery_rule_toggle(rule_id: int, request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    context = get_request_company_context(request)
    if not context:
        return company_context_required_page()

    role = str(context.get("role") or "").upper()
    if role not in ("OWNER", "SUPER_ADMIN", "COMPANY_ADMIN"):
        return admin_required_page()

    company_id = get_active_company_id_for_request(request)

    with get_connection() as conn:
        rule = conn.execute(
            """
            SELECT r.id, r.is_active
            FROM contract_delivery_rules r
            JOIN contract_delivery_profiles p
              ON p.id = r.profile_id
            WHERE r.id = ?
              AND p.company_id = ?
            """,
            (rule_id, company_id),
        ).fetchone()

        if not rule:
            return HTMLResponse(
                layout(
                    "Regle introuvable",
                    "<div class='card'>Regle introuvable.</div>",
                ),
                status_code=404,
            )

        new_value = 0 if int(rule["is_active"] or 0) else 1

        conn.execute(
            """
            UPDATE contract_delivery_rules
            SET is_active = ?
            WHERE id = ?
            """,
            (new_value, rule_id),
        )

        conn.commit()

    return RedirectResponse(
        url="/contracts/settings/recipients",
        status_code=303,
    )


@app.post("/contracts/settings/rules/{rule_id}/delete")
def contract_delivery_rule_delete(rule_id: int, request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    context = get_request_company_context(request)
    if not context:
        return company_context_required_page()

    role = str(context.get("role") or "").upper()
    if role not in ("OWNER", "SUPER_ADMIN", "COMPANY_ADMIN"):
        return admin_required_page()

    company_id = get_active_company_id_for_request(request)

    with get_connection() as conn:
        rule = conn.execute(
            """
            SELECT r.id
            FROM contract_delivery_rules r
            JOIN contract_delivery_profiles p
              ON p.id = r.profile_id
            WHERE r.id = ?
              AND p.company_id = ?
            """,
            (rule_id, company_id),
        ).fetchone()

        if rule:
            conn.execute(
                "DELETE FROM contract_delivery_rules WHERE id = ?",
                (rule_id,),
            )
            conn.commit()

    return RedirectResponse(
        url="/contracts/settings/recipients",
        status_code=303,
    )


@app.get(
    "/quote/{quote_id}/contract/create",
    response_class=HTMLResponse
)
def create_contract_page(quote_id: int, request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    init_db()

    quote = get_quote_for_current_company(request, quote_id)

    if not quote:
        return quote_access_denied_response(quote_id)

    company_id = get_active_company_id_for_request(request)

    with get_connection() as conn:
        existing = conn.execute(
            """
            SELECT id
            FROM contracts
            WHERE quote_id = ?
              AND company_id = ?
            """,
            (quote_id, company_id),
        ).fetchone()

    if existing:
        return RedirectResponse(
            url=f"/contract/{existing['id']}",
            status_code=303,
        )

    if str(quote["status"] or "") != "accepted":
        content = f"""
        <h2>Creation du contrat</h2>
        <div class="card">
            <h3>Devis non accepte</h3>
            <p>
                Le devis #{quote_id} doit avoir le statut
                <strong>accepted</strong>.
            </p>
            <a
                class="button secondary"
                href="/quote/{quote_id}/inputs"
            >
                Retour au devis
            </a>
        </div>
        """
        return layout("Creation contrat", content)

    from datetime import date, timedelta

    today = date.today()

    total_hours = float(quote["total_hours"] or 0)
    hours_per_year = float(quote["hours_per_year"] or 0)

    planned_end_date = ""

    if total_hours > 0 and hours_per_year > 0:
        contract_years = total_hours / hours_per_year

        planned_end_date = (
            today
            + timedelta(days=contract_years * 365.25)
        ).isoformat()

    customer = quote["customer_name"] or "-"

    engine = (
        quote["product_designation"]
        or quote["product_name"]
        or "-"
    )

    serial = quote["engine_serial_number"] or "-"

    package_name = (
        quote["package_name"]
        or quote["package_key"]
        or "-"
    )

    currency = quote["currency"] or "EUR"

    content = f"""
    <h2>Creer le contrat</h2>

    {contract_module_navigation()}

    <div class="card">
        <h3>Devis source #{quote_id}</h3>

        <div class="grid">
            <label>
                Client
                <input value="{customer}" readonly>
            </label>

            <label>
                Machine / moteur
                <input value="{engine}" readonly>
            </label>

            <label>
                Numero de serie
                <input value="{serial}" readonly>
            </label>

            <label>
                Package
                <input value="{package_name}" readonly>
            </label>

            <label>
                Montant contrat
                <input
                    value="{fmt_money(quote['selling_total'], currency)}"
                    readonly
                >
            </label>

            <label>
                Heures couvertes
                <input
                    id="contract_hours"
                    type="number"
                    value="{total_hours:g}"
                    readonly
                >
            </label>

            <label>
                Heures moteur / an
                <input
                    id="hours_per_year"
                    type="number"
                    value="{hours_per_year:g}"
                    readonly
                >
            </label>
        </div>
    </div>

    <form
        class="card"
        method="post"
        action="/quote/{quote_id}/contract/create"
    >
        <h3>Demarrage du contrat</h3>

        <div class="grid">
            <label>
                Date de debut
                <input
                    id="start_date"
                    type="date"
                    name="start_date"
                    value="{today.isoformat()}"
                    required
                    onchange="updateContractPreview()"
                >
            </label>

            <label>
                Compteur moteur au debut
                <input
                    id="start_engine_hours"
                    type="number"
                    step="0.1"
                    min="0"
                    name="start_engine_hours"
                    value="0"
                    required
                    oninput="updateContractPreview()"
                >
            </label>

            <label>
                Compteur fin contractuel
                <input
                    id="planned_end_engine_hours"
                    type="number"
                    step="0.1"
                    min="0"
                    name="planned_end_engine_hours"
                    value="{total_hours:g}"
                    required
                >
                <small class="muted">
                    Compteur debut + heures contrat.
                </small>
            </label>

            <label>
                Date de fin estimee
                <input
                    id="planned_end_date_preview"
                    type="date"
                    value="{planned_end_date}"
                    readonly
                >
            </label>
        </div>

        <h3>Facturation</h3>

        <div class="grid">
            <label>
                Mode de facturation
                <select
                    id="billing_mode"
                    name="billing_mode"
                    onchange="updateBillingDay()"
                >
                    <option value="monthly">
                        Mensuelle
                    </option>

                    <option value="per_intervention">
                        A l'intervention / a la tache
                    </option>
                </select>
            </label>

            <label id="billing_day_label">
                Jour de facturation
                <input
                    type="number"
                    min="1"
                    max="28"
                    name="billing_day"
                    value="1"
                >
            </label>
        </div>

        <div style="margin-top:20px;">
            <button
                class="button green"
                type="submit"
            >
                Valider et creer le contrat
            </button>

            <a
                class="button secondary"
                href="/quote/{quote_id}/inputs"
            >
                Annuler
            </a>
        </div>
    </form>

    <script>
    let endHoursEdited = false;

    const endHoursField =
        document.getElementById(
            "planned_end_engine_hours"
        );

    endHoursField.addEventListener(
        "input",
        function() {{
            endHoursEdited = true;
        }}
    );

    function updateContractPreview() {{
        const startHours =
            parseFloat(
                document.getElementById(
                    "start_engine_hours"
                ).value
            ) || 0;

        const contractHours =
            parseFloat(
                document.getElementById(
                    "contract_hours"
                ).value
            ) || 0;

        if (!endHoursEdited) {{
            endHoursField.value =
                (startHours + contractHours).toFixed(1);
        }}

        const startDateValue =
            document.getElementById(
                "start_date"
            ).value;

        const hoursPerYear =
            parseFloat(
                document.getElementById(
                    "hours_per_year"
                ).value
            ) || 0;

        if (
            startDateValue &&
            contractHours > 0 &&
            hoursPerYear > 0
        ) {{
            const years =
                contractHours / hoursPerYear;

            const days =
                Math.round(years * 365.25);

            const d =
                new Date(
                    startDateValue + "T12:00:00"
                );

            d.setDate(d.getDate() + days);

            document.getElementById(
                "planned_end_date_preview"
            ).value =
                d.toISOString().slice(0, 10);
        }}
    }}

    function updateBillingDay() {{
        const mode =
            document.getElementById(
                "billing_mode"
            ).value;

        document.getElementById(
            "billing_day_label"
        ).style.display =
            mode === "monthly"
            ? "block"
            : "none";
    }}

    updateContractPreview();
    updateBillingDay();
    </script>
    """

    return layout("Creer le contrat", content)


@app.post("/quote/{quote_id}/contract/create")
def create_contract_submit(
    quote_id: int,
    request: Request,
    start_date: str = Form(""),
    start_engine_hours: float = Form(0),
    planned_end_engine_hours: float = Form(0),
    billing_mode: str = Form("monthly"),
    billing_day: int = Form(1),
):
    login_response = require_login(request)
    if login_response:
        return login_response

    init_db()

    quote = get_quote_for_current_company(
        request,
        quote_id,
    )

    if not quote:
        return quote_access_denied_response(quote_id)

    if str(quote["status"] or "") != "accepted":
        return HTMLResponse(
            layout(
                "Creation contrat",
                """
                <div class="card">
                    <h3>Creation refusee</h3>
                    <p>
                        Le devis doit etre accepte.
                    </p>
                </div>
                """,
            ),
            status_code=400,
        )

    from datetime import date, timedelta

    company_id = get_active_company_id_for_request(
        request
    )

    start_date = (start_date or "").strip()

    try:
        start_date_obj = date.fromisoformat(
            start_date
        )
    except Exception:
        start_date_obj = date.today()
        start_date = start_date_obj.isoformat()

    start_engine_hours = max(
        0.0,
        float(start_engine_hours or 0),
    )

    contract_hours = max(
        0.0,
        float(quote["total_hours"] or 0),
    )

    hours_per_year = max(
        0.0,
        float(quote["hours_per_year"] or 0),
    )

    proposed_end_hours = (
        start_engine_hours + contract_hours
    )

    planned_end_engine_hours = float(
        planned_end_engine_hours or 0
    )

    if (
        planned_end_engine_hours
        <= start_engine_hours
    ):
        planned_end_engine_hours = (
            proposed_end_hours
        )

    planned_end_date = None

    if contract_hours > 0 and hours_per_year > 0:
        contract_years = (
            contract_hours / hours_per_year
        )

        planned_end_date = (
            start_date_obj
            + timedelta(
                days=contract_years * 365.25
            )
        ).isoformat()

    if billing_mode not in (
        "monthly",
        "per_intervention",
    ):
        billing_mode = "monthly"

    if billing_mode == "monthly":
        try:
            billing_day = int(billing_day)
        except Exception:
            billing_day = 1

        billing_day = min(
            28,
            max(1, billing_day),
        )
    else:
        billing_day = None

    with get_connection() as conn:
        existing = conn.execute(
            """
            SELECT id
            FROM contracts
            WHERE quote_id = ?
              AND company_id = ?
            """,
            (quote_id, company_id),
        ).fetchone()

        if existing:
            return RedirectResponse(
                url=f"/contract/{existing['id']}",
                status_code=303,
            )

        next_id = conn.execute(
            """
            SELECT COALESCE(MAX(id), 0) + 1
            FROM contracts
            """
        ).fetchone()[0]

        contract_number = (
            f"CTR-{start_date_obj.year}-"
            f"{int(next_id):04d}"
        )

        cursor = conn.execute(
            """
            INSERT INTO contracts (
                quote_id,
                contract_number,
                company_id,
                status,
                customer_name,
                engine_serial_number,
                product_name,
                product_designation,
                start_date,
                planned_end_date,
                start_engine_hours,
                current_engine_hours,
                planned_end_engine_hours,
                hours_per_year,
                package_key,
                currency,
                contract_total,
                billing_mode,
                billing_day
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                quote_id,
                contract_number,
                company_id,
                "draft",
                quote["customer_name"],
                quote["engine_serial_number"],
                quote["product_name"],
                quote["product_designation"],
                start_date,
                planned_end_date,
                start_engine_hours,
                start_engine_hours,
                planned_end_engine_hours,
                hours_per_year,
                quote["package_key"],
                quote["currency"] or "EUR",
                float(
                    quote["selling_total"] or 0
                ),
                billing_mode,
                billing_day,
            ),
        )

        contract_id = cursor.lastrowid

        conn.execute(
            """
            INSERT INTO contract_meter_readings (
                contract_id,
                reading_date,
                engine_hours,
                source,
                notes
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                contract_id,
                start_date,
                start_engine_hours,
                "contract_start",
                "Initial contract engine-hour reading",
            ),
        )

        # ----------------------------------------------------
        # Generate contract interventions from imported quote
        # ----------------------------------------------------

        imported_interventions = conn.execute(
            """
            SELECT *
            FROM interventions
            WHERE quote_id = ?
            ORDER BY engine_hours, intervention_date, id
            """,
            (quote_id,),
        ).fetchall()

        quote_parts = conn.execute(
            """
            SELECT *
            FROM quote_lines
            WHERE quote_id = ?
              AND part_number IS NOT NULL
              AND TRIM(part_number) <> ''
            ORDER BY id
            """,
            (quote_id,),
        ).fetchall()

        parts_by_component = {}

        for part in quote_parts:
            component = str(part["component"] or "").strip()

            if component not in parts_by_component:
                parts_by_component[component] = []

            parts_by_component[component].append(part)

        def components_for_relative_hours(relative_hours):
            value = float(relative_hours or 0)

            components = []

            # Standard maintenance
            if value > 0 and value % 500 == 0:
                components.extend(["A", "C"])

            # Additional 2000-hour maintenance
            if value > 0 and value % 2000 == 0:
                components.extend(["B", "D"])

            # Special 6000-hour operation
            if abs(value - 6000.0) < 0.01:
                components.append("E")

            # Special coolant operation
            if abs(value - 7600.0) < 0.01:
                components.append("F")

            return components

        for imported in imported_interventions:

            relative_hours = float(
                imported["engine_hours"] or 0
            )

            # Ignore imported maintenance milestones that
            # fall outside the signed contract coverage.
            if (
                contract_hours > 0
                and relative_hours > contract_hours
            ):
                continue

            absolute_hours = (
                start_engine_hours
                + relative_hours
            )

            # Planned dates belong to the actual contract,
            # not to the original Service Calculator calendar.
            intervention_date = imported[
                "intervention_date"
            ]

            if (
                hours_per_year > 0
                and relative_hours >= 0
            ):
                intervention_date = (
                    start_date_obj
                    + timedelta(
                        days=(
                            relative_hours
                            / hours_per_year
                            * 365.25
                        )
                    )
                ).isoformat()

            intervention_type = (
                f"Maintenance {relative_hours:g} h"
            )

            cursor_intervention = conn.execute(
                """
                INSERT INTO contract_interventions (
                    contract_id,
                    intervention_type,
                    reference_engine_hours,
                    planned_engine_hours,
                    planned_date,
                    status,
                    notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    contract_id,
                    intervention_type,
                    absolute_hours,
                    absolute_hours,
                    intervention_date,
                    "planned",
                    (
                        "Generated from quote intervention "
                        f"{relative_hours:g} h"
                    ),
                ),
            )

            contract_intervention_id = (
                cursor_intervention.lastrowid
            )

            components = components_for_relative_hours(
                relative_hours
            )

            for component in components:
                for part in parts_by_component.get(
                    component,
                    [],
                ):
                    total_quantity = float(
                        part["quantity"] or 0
                    )

                    # Imported quantities are totals across all
                    # occurrences of the component.
                    #
                    # A/C occur 19 times.
                    # B/D occur 4 times.
                    # E/F occur once.
                    divisor = 1.0

                    if component in ("A", "C"):
                        divisor = 19.0
                    elif component in ("B", "D"):
                        divisor = 4.0

                    planned_quantity = (
                        total_quantity / divisor
                        if divisor
                        else total_quantity
                    )

                    conn.execute(
                        """
                        INSERT INTO contract_intervention_parts (
                            contract_intervention_id,
                            part_number,
                            description,
                            planned_quantity,
                            actual_quantity,
                            source
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            contract_intervention_id,
                            part["part_number"],
                            part["description"],
                            planned_quantity,
                            0,
                            f"quote_component_{component}",
                        ),
                    )

        # ----------------------------------------------------
        # Generate contractual billing events
        # ----------------------------------------------------

        if billing_mode == "monthly":
            billing_day_value = int(billing_day or 1)
            billing_day_value = max(1, min(28, billing_day_value))

            billing_year = start_date_obj.year
            billing_month = start_date_obj.month

            candidate = date(
                billing_year,
                billing_month,
                billing_day_value,
            )

            if candidate < start_date_obj:
                if billing_month == 12:
                    billing_year += 1
                    billing_month = 1
                else:
                    billing_month += 1

                candidate = date(
                    billing_year,
                    billing_month,
                    billing_day_value,
                )

            billing_end_date = date.fromisoformat(
                planned_end_date
            )

            while candidate <= billing_end_date:
                event_key = (
                    f"monthly:{candidate.isoformat()}"
                )

                conn.execute(
                    """
                    INSERT OR IGNORE INTO contract_billing_events (
                        contract_id,
                        event_key,
                        billing_type,
                        due_date,
                        source_intervention_id,
                        status
                    )
                    VALUES (?, ?, 'monthly', ?, NULL, 'planned')
                    """,
                    (
                        contract_id,
                        event_key,
                        candidate.isoformat(),
                    ),
                )

                if candidate.month == 12:
                    next_year = candidate.year + 1
                    next_month = 1
                else:
                    next_year = candidate.year
                    next_month = candidate.month + 1

                candidate = date(
                    next_year,
                    next_month,
                    billing_day_value,
                )

        elif billing_mode == "per_intervention":
            billing_interventions = conn.execute(
                """
                SELECT
                    id,
                    planned_date
                FROM contract_interventions
                WHERE contract_id = ?
                  AND planned_date IS NOT NULL
                ORDER BY planned_engine_hours, id
                """,
                (contract_id,),
            ).fetchall()

            for billing_intervention in billing_interventions:
                source_intervention_id = int(
                    billing_intervention["id"]
                )

                due_date = str(
                    billing_intervention["planned_date"]
                )

                event_key = (
                    f"intervention:{source_intervention_id}"
                )

                conn.execute(
                    """
                    INSERT OR IGNORE INTO contract_billing_events (
                        contract_id,
                        event_key,
                        billing_type,
                        due_date,
                        source_intervention_id,
                        status
                    )
                    VALUES (?, ?, 'per_intervention', ?, ?, 'planned')
                    """,
                    (
                        contract_id,
                        event_key,
                        due_date,
                        source_intervention_id,
                    ),
                )

        conn.commit()

    return RedirectResponse(
        url=f"/contract/{contract_id}",
        status_code=303,
    )




@app.post("/contract/{contract_id}/meter-reading")
def contract_meter_reading_submit(
    contract_id: int,
    request: Request,
    reading_date: str = Form(""),
    engine_hours: float = Form(0),
    source: str = Form("manual"),
    notes: str = Form(""),
):
    login_response = require_login(request)
    if login_response:
        return login_response

    init_db()

    contract = get_contract_for_current_company(
        request,
        contract_id,
    )

    if not contract:
        return HTMLResponse(
            layout(
                "Contrat introuvable",
                """
                <div class="card">
                    <h3>Contrat introuvable ou non autorise.</h3>
                    <a class="button secondary" href="/contracts">
                        Retour contrats
                    </a>
                </div>
                """,
            ),
            status_code=404,
        )

    from datetime import date, datetime, timedelta

    reading_date = (reading_date or "").strip()

    try:
        reading_date_obj = date.fromisoformat(reading_date)
    except Exception:
        reading_date_obj = date.today()
        reading_date = reading_date_obj.isoformat()

    try:
        engine_hours = float(engine_hours or 0)
    except Exception:
        engine_hours = 0.0

    engine_hours = max(0.0, engine_hours)

    allowed_sources = {
        "manual",
        "intervention",
        "customer",
        "remote",
    }

    if source not in allowed_sources:
        source = "manual"

    notes = (notes or "").strip()

    start_engine_hours = float(
        contract["start_engine_hours"] or 0
    )

    planned_end_engine_hours = float(
        contract["planned_end_engine_hours"] or 0
    )

    fallback_hours_per_year = float(
        contract["hours_per_year"] or 0
    )

    with get_connection() as conn:

        previous = conn.execute(
            """
            SELECT *
            FROM contract_meter_readings
            WHERE contract_id = ?
            ORDER BY reading_date DESC, id DESC
            LIMIT 1
            """,
            (contract_id,),
        ).fetchone()

        if previous:
            previous_hours = float(
                previous["engine_hours"] or 0
            )

            if engine_hours < previous_hours:
                content = f"""
                <h2>Releve compteur refuse</h2>

                <div class="card">
                    <h3>Compteur inferieur au dernier releve</h3>

                    <p>
                        Dernier compteur :
                        <strong>{previous_hours:g} h</strong>
                    </p>

                    <p>
                        Nouveau compteur saisi :
                        <strong>{engine_hours:g} h</strong>
                    </p>

                    <p>
                        Le nouveau releve doit etre superieur
                        ou egal au dernier compteur connu.
                    </p>

                    <a
                        class="button secondary"
                        href="/contract/{contract_id}"
                    >
                        Retour au contrat
                    </a>
                </div>
                """

                return HTMLResponse(
                    layout(
                        "Releve compteur refuse",
                        content,
                    ),
                    status_code=400,
                )

        conn.execute(
            """
            INSERT INTO contract_meter_readings (
                contract_id,
                reading_date,
                engine_hours,
                source,
                notes
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                contract_id,
                reading_date,
                engine_hours,
                source,
                notes,
            ),
        )

        readings = conn.execute(
            """
            SELECT *
            FROM contract_meter_readings
            WHERE contract_id = ?
            ORDER BY reading_date ASC, id ASC
            """,
            (contract_id,),
        ).fetchall()

        calculated_hours_per_year = (
            fallback_hours_per_year
        )

        if len(readings) >= 2:
            first = readings[0]
            last = readings[-1]

            try:
                first_date = date.fromisoformat(
                    first["reading_date"]
                )

                last_date = date.fromisoformat(
                    last["reading_date"]
                )

                elapsed_days = (
                    last_date - first_date
                ).days

                used_hours = (
                    float(last["engine_hours"] or 0)
                    - float(first["engine_hours"] or 0)
                )

                if elapsed_days > 0 and used_hours > 0:
                    calculated_hours_per_year = (
                        used_hours
                        / elapsed_days
                        * 365.25
                    )
            except Exception:
                pass

        planned_end_date = contract[
            "planned_end_date"
        ]

        remaining_hours = max(
            0.0,
            planned_end_engine_hours
            - engine_hours,
        )

        if (
            calculated_hours_per_year > 0
            and remaining_hours > 0
        ):
            remaining_years = (
                remaining_hours
                / calculated_hours_per_year
            )

            planned_end_date = (
                reading_date_obj
                + timedelta(
                    days=remaining_years * 365.25
                )
            ).isoformat()

        elif remaining_hours <= 0:
            planned_end_date = reading_date

        # Recalculate forecast dates for all future planned
        # interventions from the latest real meter reading.
        if calculated_hours_per_year > 0:
            future_interventions = conn.execute(
                """
                SELECT id, planned_engine_hours
                FROM contract_interventions
                WHERE contract_id = ?
                  AND status = 'planned'
                  AND planned_engine_hours >= ?
                ORDER BY planned_engine_hours, id
                """,
                (
                    contract_id,
                    engine_hours,
                ),
            ).fetchall()

            for intervention in future_interventions:
                intervention_hours = float(
                    intervention["planned_engine_hours"] or 0
                )

                hours_until = max(
                    0.0,
                    intervention_hours - engine_hours,
                )

                intervention_date = (
                    reading_date_obj
                    + timedelta(
                        days=(
                            hours_until
                            / calculated_hours_per_year
                            * 365.25
                        )
                    )
                ).isoformat()

                conn.execute(
                    """
                    UPDATE contract_interventions
                    SET planned_date = ?
                    WHERE id = ?
                    """,
                    (
                        intervention_date,
                        intervention["id"],
                    ),
                )

                conn.execute(
                    """
                    UPDATE contract_billing_events
                    SET due_date = ?
                    WHERE billing_type = 'per_intervention'
                      AND source_intervention_id = ?
                    """,
                    (
                        intervention_date,
                        intervention["id"],
                    ),
                )

        conn.execute(
            """
            UPDATE contracts
            SET current_engine_hours = ?,
                planned_end_date = ?
            WHERE id = ?
            """,
            (
                engine_hours,
                planned_end_date,
                contract_id,
            ),
        )

        conn.commit()

    return RedirectResponse(
        url=f"/contract/{contract_id}",
        status_code=303,
    )




@app.post(
    "/contract/{contract_id}/intervention/{intervention_id}/complete"
)
def contract_intervention_complete(
    contract_id: int,
    intervention_id: int,
    request: Request,
    actual_date: str = Form(""),
    actual_engine_hours: float = Form(0),
):
    login_response = require_login(request)
    if login_response:
        return login_response

    init_db()

    contract = get_contract_for_current_company(
        request,
        contract_id,
    )

    if not contract:
        return HTMLResponse(
            layout(
                "Contrat introuvable",
                "<div class='card'>Contrat introuvable.</div>",
            ),
            status_code=404,
        )

    from datetime import date, timedelta

    try:
        actual_date_obj = date.fromisoformat(actual_date)
    except Exception:
        return HTMLResponse(
            layout(
                "Date invalide",
                "<div class='card'>Date intervention invalide.</div>",
            ),
            status_code=400,
        )

    actual_engine_hours = float(actual_engine_hours or 0)

    with get_connection() as conn:
        intervention = conn.execute(
            """
            SELECT *
            FROM contract_interventions
            WHERE id = ?
              AND contract_id = ?
            """,
            (
                intervention_id,
                contract_id,
            ),
        ).fetchone()

        if not intervention:
            return HTMLResponse(
                layout(
                    "Intervention introuvable",
                    "<div class='card'>Intervention introuvable.</div>",
                ),
                status_code=404,
            )

        if intervention["status"] != "planned":
            return RedirectResponse(
                url=f"/contract/{contract_id}",
                status_code=303,
            )

        planned_hours = float(
            intervention["planned_engine_hours"] or 0
        )

        if actual_engine_hours <= 0:
            return HTMLResponse(
                layout(
                    "Compteur invalide",
                    "<div class='card'>Compteur intervention invalide.</div>",
                ),
                status_code=400,
            )

        latest_before = conn.execute("SELECT reading_date, engine_hours FROM contract_meter_readings WHERE contract_id = ? ORDER BY reading_date DESC, id DESC LIMIT 1", (contract_id,)).fetchone()
        if latest_before and actual_engine_hours < float(latest_before[1] or 0):
            return HTMLResponse(layout("Compteur invalide", "<div class='card'>Le compteur reel ne peut pas etre inferieur au dernier compteur connu.</div>"), status_code=400)
        if latest_before and actual_date_obj < date.fromisoformat(latest_before[0]):
            return HTMLResponse(layout("Date invalide", "<div class='card'>La date reelle ne peut pas etre anterieure au dernier releve compteur.</div>"), status_code=400)

        # Preserve original reference for old test rows too.
        conn.execute(
            """
            UPDATE contract_interventions
            SET reference_engine_hours =
                COALESCE(
                    reference_engine_hours,
                    planned_engine_hours
                )
            WHERE contract_id = ?
            """,
            (contract_id,),
        )

        # Difference between current forecast and actual execution.
        delta_hours = (
            actual_engine_hours
            - planned_hours
        )

        conn.execute(
            """
            UPDATE contract_interventions
            SET status = 'completed',
                actual_engine_hours = ?,
                actual_date = ?
            WHERE id = ?
            """,
            (
                actual_engine_hours,
                actual_date,
                intervention_id,
            ),
        )

        conn.execute(
            """
            UPDATE contract_billing_events
            SET due_date = ?
            WHERE billing_type = 'per_intervention'
              AND source_intervention_id = ?
            """,
            (
                actual_date,
                intervention_id,
            ),
        )

        # By default, actual parts equal planned parts.
        conn.execute(
            """
            UPDATE contract_intervention_parts
            SET actual_quantity = planned_quantity
            WHERE contract_intervention_id = ?
            """,
            (intervention_id,),
        )

        # Store the real meter reading if it is newer/higher.
        latest = conn.execute(
            """
            SELECT *
            FROM contract_meter_readings
            WHERE contract_id = ?
            ORDER BY reading_date DESC, id DESC
            LIMIT 1
            """,
            (contract_id,),
        ).fetchone()

        latest_hours = (
            float(latest["engine_hours"] or 0)
            if latest
            else 0.0
        )

        if actual_engine_hours >= latest_hours:
            conn.execute(
                """
                INSERT INTO contract_meter_readings (
                    contract_id,
                    reading_date,
                    engine_hours,
                    source,
                    contract_intervention_id,
                    notes
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    contract_id,
                    actual_date,
                    actual_engine_hours,
                    "intervention",
                    intervention_id,
                    "Intervention completed",
                ),
            )

            conn.execute(
                """
                UPDATE contracts
                SET current_engine_hours = ?
                WHERE id = ?
                """,
                (
                    actual_engine_hours,
                    contract_id,
                ),
            )

        # Shift every future milestone by the actual delay/advance.
        # This preserves the imported Volvo sequence, including
        # exceptional gaps such as 7500 -> 7600 h.
        if abs(delta_hours) > 0.0001:
            conn.execute(
                """
                UPDATE contract_interventions
                SET planned_engine_hours =
                    planned_engine_hours + ?
                WHERE contract_id = ?
                  AND status = 'planned'
                  AND planned_engine_hours > ?
                """,
                (
                    delta_hours,
                    contract_id,
                    planned_hours,
                ),
            )

        # Recalculate future dates from observed machine use.
        readings = conn.execute(
            """
            SELECT *
            FROM contract_meter_readings
            WHERE contract_id = ?
            ORDER BY reading_date ASC, id ASC
            """,
            (contract_id,),
        ).fetchall()

        calculated_hours_per_year = float(
            contract["hours_per_year"] or 0
        )

        if len(readings) >= 2:
            first = readings[0]
            last = readings[-1]

            try:
                first_date = date.fromisoformat(
                    first["reading_date"]
                )
                last_date = date.fromisoformat(
                    last["reading_date"]
                )

                elapsed_days = (
                    last_date - first_date
                ).days

                used_hours = (
                    float(last["engine_hours"] or 0)
                    - float(first["engine_hours"] or 0)
                )

                if elapsed_days > 0 and used_hours > 0:
                    calculated_hours_per_year = (
                        used_hours
                        / elapsed_days
                        * 365.25
                    )
            except Exception:
                pass

        if calculated_hours_per_year > 0:
            future = conn.execute(
                """
                SELECT id, planned_engine_hours
                FROM contract_interventions
                WHERE contract_id = ?
                  AND status = 'planned'
                  AND planned_engine_hours > ?
                ORDER BY planned_engine_hours, id
                """,
                (
                    contract_id,
                    actual_engine_hours,
                ),
            ).fetchall()

            for future_row in future:
                hours_until = (
                    float(
                        future_row["planned_engine_hours"]
                        or 0
                    )
                    - actual_engine_hours
                )

                forecast_date = (
                    actual_date_obj
                    + timedelta(
                        days=(
                            hours_until
                            / calculated_hours_per_year
                            * 365.25
                        )
                    )
                ).isoformat()

                conn.execute(
                    """
                    UPDATE contract_interventions
                    SET planned_date = ?
                    WHERE id = ?
                    """,
                    (
                        forecast_date,
                        future_row["id"],
                    ),
                )

                conn.execute(
                    """
                    UPDATE contract_billing_events
                    SET due_date = ?
                    WHERE billing_type = 'per_intervention'
                      AND source_intervention_id = ?
                    """,
                    (
                        forecast_date,
                        future_row["id"],
                    ),
                )

        conn.commit()

    return RedirectResponse(
        url=f"/contract/{contract_id}",
        status_code=303,
    )



@app.post("/contract/{contract_id}/status/{new_status}")
def contract_status_change(
    contract_id: int,
    new_status: str,
    request: Request,
):
    login_response = require_login(request)
    if login_response:
        return login_response

    init_db()

    contract = get_contract_for_current_company(
        request,
        contract_id,
    )

    if not contract:
        return HTMLResponse(
            layout(
                "Contrat introuvable",
                "<div class='card'>Contrat introuvable ou non autorise.</div>",
            ),
            status_code=404,
        )

    allowed_statuses = {
        "active",
        "suspended",
        "archived",
    }

    if new_status not in allowed_statuses:
        return HTMLResponse(
            layout(
                "Statut invalide",
                "<div class='card'>Statut de contrat invalide.</div>",
            ),
            status_code=400,
        )

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE contracts
            SET status = ?
            WHERE id = ?
              AND company_id = ?
            """,
            (
                new_status,
                contract_id,
                contract["company_id"],
            ),
        )
        conn.commit()

    return RedirectResponse(
        url=f"/contract/{contract_id}",
        status_code=303,
    )


@app.post("/contract/{contract_id}/delete")
def contract_delete(
    contract_id: int,
    request: Request,
):
    login_response = require_login(request)
    if login_response:
        return login_response

    init_db()

    contract = get_contract_for_current_company(
        request,
        contract_id,
    )

    if not contract:
        return HTMLResponse(
            layout(
                "Contrat introuvable",
                "<div class='card'>Contrat introuvable ou non autorise.</div>",
            ),
            status_code=404,
        )

    company_id = int(contract["company_id"])

    with get_connection() as conn:
        intervention_rows = conn.execute(
            """
            SELECT id
            FROM contract_interventions
            WHERE contract_id = ?
            """,
            (contract_id,),
        ).fetchall()

        intervention_ids = [
            int(row["id"])
            for row in intervention_rows
        ]

        billing_rows = conn.execute(
            """
            SELECT id
            FROM contract_billing_events
            WHERE contract_id = ?
            """,
            (contract_id,),
        ).fetchall()

        billing_ids = [
            int(row["id"])
            for row in billing_rows
        ]

        event_keys = [
            f"contract_end:{contract_id}"
        ]

        event_keys.extend(
            f"intervention:{item_id}"
            for item_id in intervention_ids
        )

        event_keys.extend(
            f"billing:{item_id}"
            for item_id in billing_ids
        )

        if event_keys:
            placeholders = ",".join(
                "?" for _ in event_keys
            )

            conn.execute(
                f"""
                DELETE FROM contract_delivery_log
                WHERE company_id = ?
                  AND event_key IN ({placeholders})
                """,
                [company_id, *event_keys],
            )

        if intervention_ids:
            placeholders = ",".join(
                "?" for _ in intervention_ids
            )

            conn.execute(
                f"""
                DELETE FROM contract_intervention_parts
                WHERE contract_intervention_id
                IN ({placeholders})
                """,
                intervention_ids,
            )

        conn.execute(
            """
            DELETE FROM contract_meter_readings
            WHERE contract_id = ?
            """,
            (contract_id,),
        )

        conn.execute(
            """
            DELETE FROM contract_billing_events
            WHERE contract_id = ?
            """,
            (contract_id,),
        )

        conn.execute(
            """
            DELETE FROM contract_interventions
            WHERE contract_id = ?
            """,
            (contract_id,),
        )

        conn.execute(
            """
            DELETE FROM contracts
            WHERE id = ?
              AND company_id = ?
            """,
            (
                contract_id,
                company_id,
            ),
        )

        conn.commit()

    return RedirectResponse(
        url="/contracts",
        status_code=303,
    )


@app.get(
    "/contract/{contract_id}",
    response_class=HTMLResponse
)
def contract_detail_page(
    contract_id: int,
    request: Request,
):
    login_response = require_login(request)
    if login_response:
        return login_response

    init_db()

    contract = get_contract_for_current_company(
        request,
        contract_id,
    )

    if not contract:
        return HTMLResponse(
            layout(
                "Contrat introuvable",
                """
                <div class="card">
                    <h3>
                        Contrat introuvable
                        ou non autorise.
                    </h3>
                    <a
                        class="button secondary"
                        href="/contracts"
                    >
                        Retour contrats
                    </a>
                </div>
                """,
            ),
            status_code=404,
        )

    with get_connection() as conn:
        readings = conn.execute(
            """
            SELECT *
            FROM contract_meter_readings
            WHERE contract_id = ?
            ORDER BY reading_date DESC, id DESC
            """,
            (contract_id,),
        ).fetchall()

    with get_connection() as conn:
        next_intervention = conn.execute(
            """
            SELECT *
            FROM contract_interventions
            WHERE contract_id = ?
              AND status = 'planned'
              AND planned_engine_hours >= ?
            ORDER BY planned_engine_hours, id
            LIMIT 1
            """,
            (
                contract_id,
                float(contract["current_engine_hours"] or 0),
            ),
        ).fetchone()

        next_parts = []

        if next_intervention:
            next_parts = conn.execute(
                """
                SELECT *
                FROM contract_intervention_parts
                WHERE contract_intervention_id = ?
                ORDER BY part_number
                """,
                (next_intervention["id"],),
            ).fetchall()

    readings_html = ""

    for reading in readings:
        readings_html += f"""
        <tr>
            <td>{reading["reading_date"]}</td>
            <td>
                {fmt_number(reading["engine_hours"])} h
            </td>
            <td>{reading["source"] or "-"}</td>
            <td>{reading["notes"] or "-"}</td>
        </tr>
        """

    if not readings_html:
        readings_html = """
        <tr>
            <td colspan="4">
                Aucun releve compteur.
            </td>
        </tr>
        """

    remaining_hours = max(
        0,
        float(
            contract["planned_end_engine_hours"]
            or 0
        )
        - float(
            contract["current_engine_hours"]
            or 0
        ),
    )

    billing_text = (
        "Mensuelle"
        if contract["billing_mode"] == "monthly"
        else "A l'intervention / a la tache"
    )

    next_intervention_html = """
    <div class="card">
        <h3>Prochaine intervention</h3>
        <p>Aucune intervention planifiee.</p>
    </div>
    """

    if next_intervention:
        current_hours = float(
            contract["current_engine_hours"] or 0
        )

        next_hours = float(
            next_intervention["planned_engine_hours"] or 0
        )

        hours_before = max(
            0,
            next_hours - current_hours,
        )

        parts_html = ""

        for part in next_parts:
            parts_html += f"""
            <tr>
                <td>{part["part_number"] or "-"}</td>
                <td>{part["description"] or "-"}</td>
                <td>{fmt_number(part["planned_quantity"])}</td>
            </tr>
            """

        if not parts_html:
            parts_html = """
            <tr>
                <td colspan="3">
                    Aucune piece referencee.
                </td>
            </tr>
            """

        next_intervention_html = f"""
        <div class="card">
            <h3>Prochaine intervention</h3>

            <div class="grid">
                <label>
                    Intervention
                    <input
                        value="{next_intervention['intervention_type']}"
                        readonly
                    >
                </label>

                <label>
                    Compteur prevu
                    <input
                        value="{fmt_number(next_hours)} h"
                        readonly
                    >
                </label>

                <label>
                    Heures restantes
                    <input
                        value="{fmt_number(hours_before)} h"
                        readonly
                    >
                </label>

                <label>
                    Date estimee
                    <input
                        value="{next_intervention['planned_date'] or '-'}"
                        readonly
                    >
                </label>
            </div>

            <div style="margin-top:18px;">
                <h4>Realiser cette intervention</h4>

                <form
                    method="post"
                    action="/contract/{contract_id}/intervention/{next_intervention['id']}/complete"
                >
                    <div class="grid">
                        <label>
                            Date reelle
                            <input
                                type="date"
                                name="actual_date"
                                value="{__import__('datetime').date.today().isoformat()}"
                                required
                            >
                        </label>

                        <label>
                            Compteur reel
                            <input
                                type="number"
                                step="0.1"
                                min="0"
                                name="actual_engine_hours"
                                value="{fmt_number(next_hours)}"
                                required
                            >
                        </label>
                    </div>

                    <div style="margin-top:12px;">
                        <button
                            class="button green"
                            type="submit"
                        >
                            Marquer comme realisee
                        </button>
                    </div>
                </form>
            </div>

            <h4>Pieces a preparer</h4>

            <table>
                <thead>
                    <tr>
                        <th>Reference</th>
                        <th>Description</th>
                        <th>Quantite</th>
                    </tr>
                </thead>
                <tbody>
                    {parts_html}
                </tbody>
            </table>
        </div>
        """

    content = f"""
    <h2>Contrat {contract["contract_number"]}</h2>

    {contract_module_navigation()}

    <div class="card">
        <h3>Informations principales</h3>

        <div class="grid">
            <label>
                Statut
                <input
                    value="{contract['status'] or '-'}"
                    readonly
                >
            </label>

            <label>
                Client
                <input
                    value="{contract['customer_name'] or '-'}"
                    readonly
                >
            </label>

            <label>
                Machine / moteur
                <input
                    value="{contract['product_designation'] or contract['product_name'] or '-'}"
                    readonly
                >
            </label>

            <label>
                Numero de serie
                <input
                    value="{contract['engine_serial_number'] or '-'}"
                    readonly
                >
            </label>

            <label>
                Date debut
                <input
                    value="{contract['start_date'] or '-'}"
                    readonly
                >
            </label>

            <label>
                Date fin estimee
                <input
                    value="{contract['planned_end_date'] or '-'}"
                    readonly
                >
            </label>

            <label>
                Compteur debut
                <input
                    value="{fmt_number(contract['start_engine_hours'])} h"
                    readonly
                >
            </label>

            <label>
                Compteur actuel
                <input
                    value="{fmt_number(contract['current_engine_hours'])} h"
                    readonly
                >
            </label>

            <label>
                Compteur fin contractuel
                <input
                    value="{fmt_number(contract['planned_end_engine_hours'])} h"
                    readonly
                >
            </label>

            <label>
                Heures restantes
                <input
                    value="{fmt_number(remaining_hours)} h"
                    readonly
                >
            </label>

            <label>
                Heures / an
                <input
                    value="{fmt_number(contract['hours_per_year'])} h"
                    readonly
                >
            </label>

            <label>
                Facturation
                <input
                    value="{billing_text}"
                    readonly
                >
            </label>
        </div>

        <p>
            <a
                class="button secondary"
                href="/quote/{contract['quote_id']}/inputs"
            >
                Voir le devis source
            </a>
        </p>
    </div>

    <div class="card">
        <h3>Gestion du contrat</h3>

        <p>
            Un contrat suspendu ou archive ne genere plus
            aucune diffusion automatique.
        </p>

        <form
            method="post"
            action="/contract/{contract_id}/status/active"
            style="display:inline;"
        >
            <button class="button green" type="submit">
                Reactiver
            </button>
        </form>

        <form
            method="post"
            action="/contract/{contract_id}/status/suspended"
            style="display:inline;"
            onsubmit="return confirm('Suspendre ce contrat ? Les diffusions automatiques seront arretees.');"
        >
            <button class="button secondary" type="submit">
                Suspendre
            </button>
        </form>

        <form
            method="post"
            action="/contract/{contract_id}/status/archived"
            style="display:inline;"
            onsubmit="return confirm('Archiver ce contrat ?');"
        >
            <button class="button secondary" type="submit">
                Archiver
            </button>
        </form>

        <form
            method="post"
            action="/contract/{contract_id}/delete"
            style="display:inline;"
            onsubmit="return confirm('ATTENTION : suppression definitive du contrat et de toutes ses donnees de suivi. Continuer ?');"
        >
            <button type="submit">
                Supprimer definitivement
            </button>
        </form>
    </div>

    {next_intervention_html}

    <div class="card">
        <h3>Mettre a jour le compteur</h3>

        <form method="post" action="/contract/{contract_id}/meter-reading">
            <div class="grid">
                <label>
                    Date du releve
                    <input
                        type="date"
                        name="reading_date"
                        value="{__import__('datetime').date.today().isoformat()}"
                        required
                    >
                </label>

                <label>
                    Compteur moteur
                    <input
                        type="number"
                        step="0.1"
                        min="0"
                        name="engine_hours"
                        value="{fmt_number(contract['current_engine_hours'])}"
                        required
                    >
                </label>

                <label>
                    Origine
                    <select name="source">
                        <option value="manual">Releve manuel</option>
                        <option value="intervention">Intervention</option>
                        <option value="customer">Information client</option>
                        <option value="remote">Telemetrie / distance</option>
                    </select>
                </label>

                <label>
                    Note
                    <input
                        type="text"
                        name="notes"
                        placeholder="Optionnel"
                    >
                </label>
            </div>

            <div style="margin-top:16px;">
                <button class="button green" type="submit">
                    Enregistrer le nouveau compteur
                </button>
            </div>
        </form>
    </div>

    <div class="card">
        <h3>Historique compteur</h3>

        <table>
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Compteur</th>
                    <th>Origine</th>
                    <th>Note</th>
                </tr>
            </thead>

            <tbody>
                {readings_html}
            </tbody>
        </table>
    </div>

    <div class="card">
        <h3>Prochaine etape V1.1</h3>
        <p>
            Ajout d'un releve compteur,
            interventions et recalcul
            automatique des echeances.
        </p>
    </div>

    <a
        class="button secondary"
        href="/contracts"
    >
        Retour Mes contrats
    </a>
    """

    return layout(
        f"Contrat {contract['contract_number']}",
        content,
    )



@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    ensure_default_settings()
    ensure_yearly_indexation_settings()
    settings = get_settings_dict()
    yearly_indexation_html = build_yearly_indexation_settings_html(settings)
    fields = [
        ("labour_margin_percent", "Marge main-d’œuvre (%)", "Marge appliquée sur la main-d’œuvre."),
        ("admin_fee_percent", "Frais administratifs (%)", "Frais de gestion, facturation et mise en place du contrat."),
        ("logistics_fee_percent", "Frais logistiques (%)", "Frais liés à l’expédition, préparation ou gestion des pièces."),
        ("travel_fee_fixed", "Frais déplacement fixes", "Montant fixe ajouté pour le déplacement si utilisé dans le calcul."),
    ]

    inputs = ""
    for key, label, help_text in fields:
        inputs += f"""
        <div class="card">
            <label>
                <strong>{label}</strong><br>
                <input type="number" step="0.01" name="{key}" value="{settings.get(key, 0)}">
            </label>
            <p class="muted">{help_text}</p>
        </div>
        """

    content = f"""
    <h2>Paramètres de calcul dealer</h2>

    <div class="card">
        <p>
            Ces paramètres servent au calcul de l’offre de contrat :
            marges, frais administratifs, frais logistiques, déplacement et indexation.
        </p>
        <p>
            Page réservée aux administrateurs de la société.
        </p>
    </div>

    <form action="/settings" method="post">
        {inputs}
        {yearly_indexation_html}

        <button type="submit">Enregistrer les paramètres de calcul</button>
        <a class="button secondary" href="/">Retour offres contrats</a>
    </form>
    """
    return layout("Paramètres de calcul dealer", content)

@app.post("/settings")
async def save_settings(
    request: Request,
    labour_margin_percent: float = Form(...),
    admin_fee_percent: float = Form(...),
    logistics_fee_percent: float = Form(...),
    travel_fee_fixed: float = Form(...),
):
    ensure_default_settings()
    set_setting("labour_margin_percent", labour_margin_percent)
    set_setting("admin_fee_percent", admin_fee_percent)
    set_setting("logistics_fee_percent", logistics_fee_percent)
    set_setting("travel_fee_fixed", travel_fee_fixed)
    request_form = await request.form()

    for year_number in range(1, 11):
        parts_raw = request_form.get(f"indexation_parts_year_{year_number}") or 0
        labour_raw = request_form.get(f"indexation_labour_year_{year_number}") or 0

        try:
            parts_value = float(parts_raw)
        except Exception:
            parts_value = 0

        try:
            labour_value = float(labour_raw)
        except Exception:
            labour_value = 0

        set_setting(f"indexation_parts_year_{year_number}", parts_value)
        set_setting(f"indexation_labour_year_{year_number}", labour_value)

    return RedirectResponse(url="/settings", status_code=303)

@app.get("/quote/{quote_id}/export")
def export_quote(quote_id: int, request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    init_db()

    with get_connection() as conn:
        quote = get_quote_for_active_company_request(conn, quote_id, request)
        if quote is None:
            return quote_access_denied_response(quote_id)

    regenerate_quote(quote_id)
    return RedirectResponse(url="/", status_code=303)

@app.get("/exports/{filename}")
def get_export(filename: str, request: Request):
    import re

    match = re.match(r"^quote_(\d+)(?:_dealer)?\.(pdf|html)$", filename or "")
    if match:
        quote_id = int(match.group(1))
        is_dealer_export = "_dealer." in filename

        if is_dealer_export:
            dealer_response = require_dealer_export_access(request)
            if dealer_response:
                return dealer_response

        with get_connection() as conn:
            quote = get_quote_for_active_company_request(conn, quote_id, request)
            if quote is None:
                return quote_access_denied_response(quote_id)
    else:
        return HTMLResponse(
            layout("Accès refusé", "<div class='error'>Fichier export non autorisé.</div>"),
            status_code=403,
        )

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
            Base Care, Comfort Care et Advanced Care sont les trois packages disponibles.
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
def quote_package_apply_permanent(quote_id: int, package_key: str, request: Request):
    init_db()
    with get_connection() as conn:
        quote = get_quote_for_active_company_request(conn, quote_id, request)
        if quote is None:
            return quote_access_denied_response(quote_id)

    _pkg_apply_package_to_quote(quote_id, package_key)
    return _PkgRedirectResponse(url=f"/quote/{quote_id}/services", status_code=303)

@app.get("/quote/{quote_id}/packages", response_class=_PkgHTMLResponse)
def quote_packages_permanent_page(quote_id: int, request: Request):
    init_db()
    with get_connection() as conn:
        quote = get_quote_for_active_company_request(conn, quote_id, request)
        if quote is None:
            return quote_access_denied_response(quote_id)

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
        <title>Choix du contrat - Devis {quote_id}</title>
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
            <h1>Choix du contrat permanents - Devis {quote_id}</h1>
            <div><a href="/quote/{quote_id}/services">Prestations incluses au contrat & temps</a> | <a href="/">Offres contrats</a></div>
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
def dealer_discounts_page(request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

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
        <title>Codes remises dealer</title>
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
            <h1>Codes remises dealer</h1>
            <div>
                <a href="/">Offres contrats</a>
            </div>
        </div>

        <div class="panel help">
            <b>Source constructeur :</b> onglet Internal Master Data, colonnes
            <b>Example products</b> et <b>Dealer discount</b>.
            <br>
            Cette page sert à vérifier et ajuster les codes remises par famille de pièces.
            <br>
            Les remises sont saisies en pourcentage : <b>49</b> = 49%.
            Elles sont stockées dans la base et peuvent être ajustées selon la société dealer.
        </div>

        <form method="post" action="/dealer-discounts">
            <table>
                <thead>
                    <tr>
                        <th>Code remise</th>
                        <th>Famille pièces</th>
                        <th>Exemples produits</th>
                        <th>Remise dealer %</th>
                        <th>Remise type client %</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(table_rows)}
                </tbody>
            </table>

            <div class="actions">
                <button type="submit">Enregistrer les codes remises</button>
                <a class="button danger" href="/dealer-discounts/reset/confirm">Réinitialiser les valeurs constructeur</a>
            </div>

            <div class="note">
                Cette page permet de contrôler les codes remises utilisés pour les pièces.
                Les valeurs sont conservées pour préparer le recalcul détaillé des pièces par code DC.
            </div>
        </form>
    </body>
    </html>
    """

@app.post("/dealer-discounts")
async def dealer_discounts_save(request: _DealerDiscountRequest):
    login_response = require_login(request)
    if login_response:
        return login_response

    form = await request.form()
    _dd_update_codes(form)
    return _DealerDiscountRedirectResponse(url="/dealer-discounts", status_code=303)

@app.get("/dealer-discounts/reset/confirm", response_class=_DealerDiscountHTMLResponse)
def dealer_discounts_reset_confirm(request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    return """
    <!doctype html>
    <html lang="fr">
    <head>
        <meta charset="utf-8">
        <title>Confirmer réinitialisation remises</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 28px; background: #f6f3ea; color: #172033; }
            .panel { background: white; border: 1px solid #d9c98b; border-radius: 16px; padding: 22px; max-width: 760px; }
            .warning { padding: 14px; background: #fffaeb; border: 1px solid #fedf89; border-radius: 12px; margin: 16px 0; }
            button, .button { border: 0; border-radius: 10px; padding: 10px 14px; font-weight: 700; cursor: pointer; text-decoration: none; display: inline-block; }
            .danger { background: #b42318; color: white; }
            .secondary { background: #102033; color: white; }
        </style>
    </head>
    <body>
        <div class="panel">
            <h1>Confirmer la réinitialisation</h1>

            <div class="warning">
                Cette action va remplacer les codes remises actuels par les valeurs constructeur.
                Les modifications dealer saisies sur cette page seront écrasées.
            </div>

            <form method="post" action="/dealer-discounts/reset">
                <button class="danger" type="submit">Oui, réinitialiser les valeurs constructeur</button>
                <a class="button secondary" href="/dealer-discounts">Annuler</a>
            </form>
        </div>
    </body>
    </html>
    """


@app.post("/dealer-discounts/reset")
def dealer_discounts_reset(request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    _dd_reset_codes()
    return _DealerDiscountRedirectResponse(url="/dealer-discounts", status_code=303)
# --- End dealer discount settings routes ---

# --- Quote options by DSP price - added by install_options_by_dsp_price.py ---
from pathlib import Path as _OptionPath
import shutil as _option_shutil

from fastapi import Request as _OptionRequest, UploadFile as _OptionUploadFile, File as _OptionFile
from fastapi.responses import HTMLResponse as _OptionHTMLResponse, RedirectResponse as _OptionRedirectResponse

from option_model import (
    add_option_line as _opt_add_line,
    delete_option_line as _opt_delete_line,
    format_money as _opt_format_money,
    get_quote_options as _opt_get_options,
    update_options_from_form as _opt_update_from_form,
)
from price_catalog_model import (
    get_catalog_count as _price_catalog_count,
    import_dsp_price_file as _price_catalog_import,
    search_catalog as _price_catalog_search,
)

@app.get("/price-catalog", response_class=_OptionHTMLResponse)
def price_catalog_page(request: Request, q: str = ""):
    login_response = require_login(request)
    if login_response:
        return login_response

    status = _price_catalog_count()
    results = _price_catalog_search(q, 40) if q else []

    result_rows = ""
    for row in results:
        result_rows += f"""
        <tr>
            <td>{row['part_no']}</td>
            <td>{row['description']}</td>
            <td class="right">{_opt_format_money(row['price_excl_vat'])}</td>
            <td>{row['discount_code'] or ''}</td>
        </tr>
        """

    if q and not result_rows:
        result_rows = '<tr><td colspan="4" class="empty">Aucun résultat.</td></tr>'

    return f"""
    <!doctype html>
    <html lang="fr">
    <head>
        <meta charset="utf-8">
        <title>Catalogue prix pièces</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 26px; background: #f6f3ea; color: #172033; }}
            a {{ color: #102033; font-weight: 700; text-decoration: none; }}
            .panel {{ background: white; border: 1px solid #d9c98b; border-radius: 16px; padding: 18px; margin-bottom: 18px; }}
            input {{ padding: 9px; border: 1px solid #d9d2b5; border-radius: 8px; }}
            button, .button {{ border: 0; border-radius: 10px; padding: 10px 14px; background: #102033; color: white !important; font-weight: 700; cursor: pointer; text-decoration: none; }}
            table {{ width: 100%; border-collapse: collapse; background: white; }}
            th {{ background: #102033; color: white; text-align: left; padding: 8px; }}
            td {{ border-bottom: 1px solid #e6e0c8; padding: 8px; }}
            .right {{ text-align: right; }}
            .empty {{ text-align: center; color: #667085; }}
        </style>
    </head>
    <body>
        <h1>Catalogue prix pièces</h1>
        <p><a href="/">Offres contrats</a></p>

        <div class="panel">
            <b>Catalogue pièces actuel :</b> {status['count']} références<br>
            <b>Dernier fichier importé :</b> {status['source_file'] or '-'}<br>
            <b>Dernière mise à jour :</b> {status['updated_at'] or '-'}
            <p>
                Ce catalogue sert à retrouver une référence pièce, sa désignation,
                son prix HT et son code remise pour les lignes Options / Customizations.
            </p>
        </div>

        <div class="panel">
            <h2>Importer le fichier DSP price</h2>
            <div style="padding:12px; background:#fffaeb; border:1px solid #fedf89; border-radius:12px; margin-bottom:12px;">
                L’import d’un nouveau fichier DSP price remplace ou actualise le catalogue pièces utilisé
                pour les recherches de références et les lignes Options / Customizations.
            </div>

            <form method="post" action="/price-catalog/upload" enctype="multipart/form-data">
                <input type="file" name="file" accept=".xlsx,.xlsm,.xls" required>

                <label style="display:block; margin:12px 0;">
                    <input type="checkbox" name="confirm_import" value="yes" required>
                    Je confirme vouloir importer ce catalogue pièces.
                </label>

                <button type="submit">Importer le catalogue pièces</button>
            </form>
            <p>Colonnes attendues : Part No, Description, Price excl VAT, Discount Code.</p>
        </div>

        <div class="panel">
            <h2>Rechercher une référence pièce</h2>
            <form method="get" action="/price-catalog">
                <input name="q" value="{q}" placeholder="Référence pièce ou désignation">
                <button type="submit">Rechercher</button>
            </form>
        </div>

        <table>
            <thead>
                <tr>
                    <th>Part No</th>
                    <th>Désignation</th>
                    <th>Prix HT</th>
                    <th>Code remise</th>
                </tr>
            </thead>
            <tbody>{result_rows}</tbody>
        </table>
    </body>
    </html>
    """

@app.post("/price-catalog/upload")
async def price_catalog_upload(
    request: Request,
    file: _OptionUploadFile = _OptionFile(...),
    confirm_import: str = Form(""),
):
    login_response = require_login(request)
    if login_response:
        return login_response

    if confirm_import != "yes":
        return _OptionHTMLResponse("""
        <!doctype html>
        <html lang="fr">
        <head><meta charset="utf-8"><title>Import non confirmé</title></head>
        <body style="font-family:Arial;margin:28px;">
            <h1>Import non confirmé</h1>
            <p>Le catalogue pièces n’a pas été importé.</p>
            <p>La case de confirmation est obligatoire avant import.</p>
            <p><a href="/price-catalog">Retour catalogue pièces</a></p>
        </body>
        </html>
        """, status_code=400)

    upload_dir = BASE_DIR / "data" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    target = _safe_uploaded_excel_path(upload_dir, file.filename, "price_catalog")

    with target.open("wb") as buffer:
        _option_shutil.copyfileobj(file.file, buffer)

    result = _price_catalog_import(target)

    return _OptionHTMLResponse(f"""
    <!doctype html>
    <html lang="fr">
    <head><meta charset="utf-8"><title>Catalogue importé</title></head>
    <body style="font-family:Arial;margin:28px;">
        <h1>Catalogue prix importé</h1>
        <p>Fichier : <b>{result['source_file']}</b></p>
        <p>Références importées : <b>{result['imported']}</b></p>
        <p>Lignes ignorées : <b>{result['skipped']}</b></p>
        <p><a href="/price-catalog">Retour catalogue pièces</a></p>
        <p><a href="/">Offres contrats</a></p>
    </body>
    </html>
    """)

def _options_section_html(quote_id: int):
    rows = _opt_get_options(quote_id)
    catalog = _price_catalog_count()

    if rows:
        option_rows = []
        for row in rows:
            checked = "checked" if row["included"] else ""
            travel_yes = "selected" if str(row["extra_travel"]).lower() in ("yes", "oui", "include", "included") else ""
            travel_exclude = "" if travel_yes else "selected"
            option_id = row["id"]
            reference = row["option_reference"] or ""

            found_badge = ""
            if reference and row["service_name"]:
                found_badge = "<div class='ok'>trouvé</div>"
            elif reference:
                found_badge = "<div class='bad'>non trouvé</div>"

            option_rows.append(f"""
                <tr>
                    <td class="center">
                        <input type="checkbox" name="included_{option_id}" {checked}>
                    </td>
                    <td>
                        <input name="option_reference_{option_id}" value="{reference}" placeholder="Part No">
                        {found_badge}
                    </td>
                    <td>
                        <input name="service_name_{option_id}" value="{row['service_name'] or ''}" placeholder="Désignation récupérée">
                    </td>
                    <td>
                        <input class="small" name="option_discount_code_{option_id}" value="{row['option_discount_code'] or ''}" placeholder="DC">
                    </td>
                    <td>
                        <input class="num" name="unit_price_{option_id}" value="{row['unit_price'] or 0}" readonly>
                    </td>
                    <td>
                        <input class="num" name="quantity_{option_id}" value="{row['quantity'] or 1}">
                    </td>
                    <td>
                        <input class="num" name="work_time_hours_{option_id}" value="{row['work_time_hours'] or 0}">
                    </td>
                    <td>
                        <input class="num" name="fixed_price_{option_id}" value="{row['fixed_price'] or 0}">
                    </td>
                    <td>
                        <select name="extra_travel_{option_id}">
                            <option value="Exclude" {travel_exclude}>Exclude</option>
                            <option value="Yes" {travel_yes}>Yes</option>
                        </select>
                    </td>
                    <td class="right"><b>{_opt_format_money(row['calculated_price'] or 0)}</b></td>
                    <td>
                        <input name="notes_{option_id}" value="{row['notes'] or ''}" placeholder="Commentaire">
                    </td>
                    <td class="center">
                        <a class="delete" href="/quote/{quote_id}/options/delete/{option_id}">Supprimer</a>
                    </td>
                </tr>
            """)
        body = "".join(option_rows)
    else:
        body = """
            <tr>
                <td colspan="12" class="empty">
                    Aucune option ajoutée. Clique sur + Ajouter une ligne.
                </td>
            </tr>
        """

    return f"""
    <div class="options-panel">
        <div class="options-title">
            <div>
                <h2>Options / Customizations</h2>
                <p>
                    La colonne <b>Service</b> appelle une référence du fichier DSP price :
                    Part No → Désignation → Prix HT → Code remise.
                </p>
                <p class="catalog-status">
                    Catalogue pièces : <b>{catalog['count']}</b> références
                    {f" / {catalog['source_file']}" if catalog['source_file'] else ""}
                    — <a href="/price-catalog">Importer / rechercher catalogue pièces</a>
                </p>
            </div>
            <a class="add-option" href="/quote/{quote_id}/options/add">+ Ajouter une ligne</a>
        </div>

        <form method="post" action="/quote/{quote_id}/options/save">
            <table class="options-table">
                <thead>
                    <tr>
                        <th>Inclure</th>
                        <th>Service / Référence</th>
                        <th>ID source / Désignation</th>
                        <th>Code remise</th>
                        <th>Prix Excel</th>
                        <th>Qté</th>
                        <th>Temps h</th>
                        <th>Prix fixe</th>
                        <th>Travel</th>
                        <th>Calculé</th>
                        <th>Notes</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody>{body}</tbody>
            </table>

            <div class="options-actions">
                <button type="submit">Actualiser et recalculer</button>
            </div>
        </form>
    </div>

    <style>
        .options-panel {{
            margin: 28px 0 18px 0;
            padding: 18px;
            border-radius: 16px;
            border: 1px solid #d9c98b;
            background: #fffaf0;
            box-shadow: 0 5px 18px rgba(16, 32, 51, 0.08);
            font-family: Arial, sans-serif;
        }}
        .options-title {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 16px;
            margin-bottom: 12px;
        }}
        .options-title h2 {{
            margin: 0;
            color: #102033;
        }}
        .options-title p {{
            margin: 5px 0 0 0;
            color: #667085;
            font-size: 13px;
        }}
        .catalog-status a {{
            color: #102033;
            font-weight: 700;
        }}
        .add-option {{
            display: inline-block;
            padding: 10px 14px;
            border-radius: 999px;
            background: #102033;
            color: white !important;
            text-decoration: none;
            font-weight: 700;
            white-space: nowrap;
        }}
        .options-table {{
            width: 100%;
            border-collapse: collapse;
            background: white;
            border-radius: 12px;
            overflow: hidden;
            font-size: 12px;
        }}
        .options-table th {{
            background: #102033;
            color: white;
            text-align: left;
            padding: 8px;
        }}
        .options-table td {{
            border-bottom: 1px solid #e6e0c8;
            padding: 6px;
            vertical-align: top;
        }}
        .options-table input,
        .options-table select {{
            width: 100%;
            box-sizing: border-box;
            border: 1px solid #d9d2b5;
            border-radius: 7px;
            padding: 7px;
            font-size: 12px;
            background: #fffdf7;
        }}
        .options-table .num {{
            text-align: right;
            min-width: 70px;
        }}
        .options-table .small {{
            max-width: 65px;
        }}
        .center {{ text-align: center; }}
        .right {{ text-align: right; }}
        .delete {{
            color: #7a1f1f;
            font-weight: 700;
            text-decoration: none;
            font-size: 12px;
        }}
        .empty {{
            text-align: center;
            color: #667085;
            padding: 16px !important;
        }}
        .ok {{ color: #067647; font-size: 11px; margin-top: 3px; font-weight: 700; }}
        .bad {{ color: #B42318; font-size: 11px; margin-top: 3px; font-weight: 700; }}
        .options-actions {{
            margin-top: 14px;
            display: flex;
            justify-content: flex-end;
        }}
        .options-actions button {{
            border: 0;
            border-radius: 10px;
            padding: 11px 15px;
            background: #102033;
            color: white;
            font-weight: 700;
            cursor: pointer;
        }}
    </style>
    """

@app.get("/quote/{quote_id}/options/add")
def quote_options_add(quote_id: int, request: Request):
    init_db()
    with get_connection() as conn:
        quote = get_quote_for_active_company_request(conn, quote_id, request)
        if quote is None:
            return quote_access_denied_response(quote_id)

    _opt_add_line(quote_id)
    return _OptionRedirectResponse(url=f"/quote/{quote_id}/services", status_code=303)

@app.get("/quote/{quote_id}/options/delete/{option_id}")
def quote_options_delete(quote_id: int, option_id: int, request: Request):
    init_db()
    with get_connection() as conn:
        quote = get_quote_for_active_company_request(conn, quote_id, request)
        if quote is None:
            return quote_access_denied_response(quote_id)

    _opt_delete_line(quote_id, option_id)
    return _OptionRedirectResponse(url=f"/quote/{quote_id}/services", status_code=303)

@app.post("/quote/{quote_id}/options/save")
async def quote_options_save(quote_id: int, request: _OptionRequest):
    init_db()
    with get_connection() as conn:
        quote = get_quote_for_active_company_request(conn, quote_id, request)
        if quote is None:
            return quote_access_denied_response(quote_id)

    form = await request.form()
    _opt_update_from_form(quote_id, form)
    return _OptionRedirectResponse(url=f"/quote/{quote_id}/services", status_code=303)

@app.middleware("http")
async def _options_section_middleware(request, call_next):
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

    section = _options_section_html(quote_id)

    if "</body>" in html:
        html = html.replace("</body>", section + "</body>", 1)
    else:
        html = html + section

    headers = dict(response.headers)
    headers.pop("content-length", None)

    return _OptionHTMLResponse(
        content=html,
        status_code=response.status_code,
        headers=headers,
    )
# --- End quote options by DSP price ---

if __name__ == "__main__":
    import uvicorn
    init_db()
    ensure_default_settings()
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)



def require_roles(request: Request, allowed_roles):
    login_response = require_login(request)
    if login_response:
        return login_response

    email = get_logged_user_email(request)
    if not email:
        return RedirectResponse(url="/login", status_code=303)

    import server_user_model as identity

    if not identity.user_has_any_role(email, allowed_roles):
        return HTMLResponse(
            layout(
                "Accès refusé",
                f"""
                <div class="error">
                    Accès refusé. Rôle requis : {', '.join(allowed_roles)}
                </div>
                <p><a class="button secondary" href="/">Retour accueil</a></p>
                """
            ),
            status_code=403,
        )

    return None


DEALER_EXPORT_ROLES = ["OWNER", "SUPER_ADMIN", "COMPANY_ADMIN"]


def can_access_dealer_exports(request: Request) -> bool:
    email = get_logged_user_email(request)
    if not email:
        return False

    import server_user_model as identity

    return identity.user_has_any_role(email, DEALER_EXPORT_ROLES)


def require_dealer_export_access(request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    if not can_access_dealer_exports(request):
        return HTMLResponse(
            layout(
                "Accès refusé",
                """
                <div class="error">
                    Accès refusé. Les exports dealer internes sont réservés aux rôles OWNER, SUPER_ADMIN et COMPANY_ADMIN.
                </div>
                <p><a class="button secondary" href="/">Retour accueil</a></p>
                """
            ),
            status_code=403,
        )

    return None



def _company_slug_from_name(name: str) -> str:
    import re
    import unicodedata

    value = unicodedata.normalize("NFKD", name or "")
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return value or "societe"


@app.get("/server/companies", response_class=HTMLResponse)
def server_companies_page(request: Request):
    admin_response = require_owner_or_super_admin(request)
    if admin_response:
        return admin_response

    import html
    import server_user_model as identity

    identity.init_server_identity_tables()
    companies = identity.list_companies()

    rows = ""
    for company in companies:
        raw_company_id = int(company["id"])
        raw_status = str(company["status"] or "")
        company_id = html.escape(str(raw_company_id))
        name = html.escape(str(company["name"] or ""))
        slug = html.escape(str(company["slug"] or ""))
        status = html.escape(raw_status)

        next_status = "inactive" if raw_status == "active" else "active"
        button_label = "Désactiver" if raw_status == "active" else "Réactiver"

        rows += f"""
        <tr>
            <td>{company_id}</td>
            <td><strong>{name}</strong></td>
            <td>{slug}</td>
            <td>{status}</td>
            <td>
                <p style="margin:0 0 8px 0;">
                    <a class="button secondary" href="/server/companies/{raw_company_id}/edit">Modifier société</a>
                </p>

                <form method="post" action="/server/companies/{raw_company_id}/select-branding" style="margin:0 0 8px 0;">
                    <button type="submit">Modifier identité</button>
                </form>

                <form method="post" action="/server/companies/{raw_company_id}/status/{next_status}" style="margin:0;">
                    <button type="submit">{button_label}</button>
                </form>
            </td>
        </tr>
        """

    if not rows:
        rows = """
        <tr>
            <td colspan="4"><em>Aucune société créée.</em></td>
        </tr>
        """

    content = f"""
    <h2>Gestion des sociétés</h2>

    <div class="card">
        <p>
            Cette page permet de créer les entreprises disponibles dans le logiciel.
            Les utilisateurs pourront ensuite être rattachés à ces sociétés depuis la page utilisateurs.
        </p>
        <p>
            Administration réservée aux rôles <strong>OWNER</strong> et <strong>SUPER_ADMIN</strong>.
        </p>
        <p>
            <a class="button" href="/server/companies/new">Créer une société</a>
            <a class="button secondary" href="/server/users">Gérer les utilisateurs</a>
        </p>
    </div>

    <div class="card">
        <h3>Sociétés existantes</h3>
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Nom</th>
                    <th>Slug</th>
                    <th>Statut</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
    </div>
    """

    return layout("Gestion des sociétés", content)




@app.post("/server/companies/{company_id}/select-branding")
def server_company_select_branding(company_id: int, request: Request):
    admin_response = require_owner_or_super_admin(request)
    if admin_response:
        return admin_response

    import server_user_model as identity

    email = get_logged_user_email(request)
    if not email:
        return RedirectResponse(url="/login", status_code=303)

    try:
        company = identity.get_company_by_id(company_id)
        if company is None:
            raise ValueError(f"Société introuvable : {company_id}")

        current_user = identity.get_user_by_email(email)
        if current_user is None:
            raise ValueError("Utilisateur introuvable")

        if not identity.user_has_company_access(email, company_id):
            identity.grant_company_access(
                company_id,
                int(current_user["id"]),
                "SUPER_ADMIN",
            )

        identity.set_active_company_id_for_user(email, company_id)

    except Exception as exc:
        return HTMLResponse(
            layout(
                "Erreur identité société",
                f"""
                <h2>Identité société</h2>
                <div class="error">Impossible d'ouvrir l'identité de cette société : {exc}</div>
                <p><a class="button secondary" href="/server/companies">Retour sociétés</a></p>
                """
            ),
            status_code=400,
        )

    return RedirectResponse(url="/server/company-branding", status_code=303)



@app.post("/server/companies/{company_id}/status/{status}")
def server_company_status_change(company_id: int, status: str, request: Request):
    admin_response = require_owner_or_super_admin(request)
    if admin_response:
        return admin_response

    import server_user_model as identity

    try:
        companies = identity.list_companies()
        active_companies = [
            company for company in companies
            if str(company["status"] or "") == "active"
        ]

        if status == "inactive":
            current_company = next(
                (company for company in companies if int(company["id"]) == int(company_id)),
                None,
            )

            if (
                current_company
                and str(current_company["status"] or "") == "active"
                and len(active_companies) <= 1
            ):
                return HTMLResponse(
                    layout(
                        "Action refusée",
                        """
                        <h2>Gestion des sociétés</h2>
                        <div class="error">
                            Impossible de désactiver la dernière société active.
                        </div>
                        <p><a class="button secondary" href="/server/companies">Retour sociétés</a></p>
                        """
                    ),
                    status_code=400,
                )

        identity.set_company_status(company_id, status)

    except Exception as exc:
        return HTMLResponse(
            layout(
                "Erreur société",
                f"""
                <h2>Gestion des sociétés</h2>
                <div class="error">Impossible de modifier le statut société : {exc}</div>
                <p><a class="button secondary" href="/server/companies">Retour sociétés</a></p>
                """
            ),
            status_code=400,
        )

    return RedirectResponse(url="/server/companies", status_code=303)



@app.get("/server/companies/{company_id}/edit", response_class=HTMLResponse)
def server_company_edit_page(company_id: int, request: Request):
    admin_response = require_owner_or_super_admin(request)
    if admin_response:
        return admin_response

    import html
    import server_user_model as identity

    company = identity.get_company_by_id(company_id)
    if company is None:
        return HTMLResponse(
            layout(
                "Société introuvable",
                """
                <h2>Modifier société</h2>
                <div class="error">Société introuvable.</div>
                <p><a class="button secondary" href="/server/companies">Retour sociétés</a></p>
                """
            ),
            status_code=404,
        )

    name = html.escape(str(company["name"] or ""))
    slug = html.escape(str(company["slug"] or ""))
    status = str(company["status"] or "active")

    content = f"""
    <h2>Modifier société</h2>

    <form method="post" action="/server/companies/{company_id}/edit" class="card">
        <label>Nom de la société
            <input type="text" name="company_name" value="{name}" required>
        </label>

        <label>Slug technique
            <input type="text" name="company_slug" value="{slug}" required>
        </label>

        <label>Statut
            <select name="status">
                <option value="active" {"selected" if status == "active" else ""}>active</option>
                <option value="inactive" {"selected" if status == "inactive" else ""}>inactive</option>
            </select>
        </label>

        <button type="submit">Enregistrer</button>
        <a class="button secondary" href="/server/companies">Retour</a>
    </form>
    """

    return layout("Modifier société", content)


@app.post("/server/companies/{company_id}/edit", response_class=HTMLResponse)
def server_company_edit_submit(
    company_id: int,
    request: Request,
    company_name: str = Form(...),
    company_slug: str = Form(...),
    status: str = Form(...),
):
    admin_response = require_owner_or_super_admin(request)
    if admin_response:
        return admin_response

    import html
    import server_user_model as identity

    try:
        slug = _company_slug_from_name(company_slug)
        identity.update_company_basic(company_id, company_name, slug, status)

    except Exception as exc:
        safe_error = html.escape(str(exc))
        return HTMLResponse(
            layout(
                "Erreur modification société",
                f"""
                <h2>Modifier société</h2>
                <div class="error">Impossible de modifier la société : {safe_error}</div>
                <p><a class="button secondary" href="/server/companies/{company_id}/edit">Retour</a></p>
                """
            ),
            status_code=400,
        )

    return RedirectResponse(url="/server/companies", status_code=303)



@app.get("/server/companies/new", response_class=HTMLResponse)
def server_company_new_page(request: Request):
    admin_response = require_owner_or_super_admin(request)
    if admin_response:
        return admin_response

    content = """
    <h2>Créer une société</h2>

    <div class="card">
        <p>
            Crée une nouvelle entreprise dans Dealer Quote Manager.
            Le slug peut être généré automatiquement si tu le laisses vide.
        </p>
    </div>

    <form method="post" action="/server/companies/new" class="card">
        <label>Nom de la société
            <input type="text" name="company_name" placeholder="Ex : Volvo Penta Atlantique" required>
        </label>

        <label>Slug technique optionnel
            <input type="text" name="company_slug" placeholder="Ex : volvo-penta-atlantique">
        </label>

        <button type="submit">Créer la société</button>
        <a class="button secondary" href="/server/companies">Retour</a>
    </form>
    """

    return layout("Créer une société", content)


@app.post("/server/companies/new", response_class=HTMLResponse)
def server_company_create_page(
    request: Request,
    company_name: str = Form(...),
    company_slug: str = Form(""),
):
    admin_response = require_owner_or_super_admin(request)
    if admin_response:
        return admin_response

    import html
    import server_user_model as identity

    identity.init_server_identity_tables()

    name = (company_name or "").strip()
    slug = (company_slug or "").strip().lower()

    if not name:
        return HTMLResponse(
            layout(
                "Erreur création société",
                """
                <h2>Créer une société</h2>
                <div class="error">Le nom de la société est obligatoire.</div>
                <p><a class="button secondary" href="/server/companies/new">Retour</a></p>
                """
            ),
            status_code=400,
        )

    if not slug:
        slug = _company_slug_from_name(name)
    else:
        slug = _company_slug_from_name(slug)

    try:
        identity.create_company(name, slug)
    except Exception as exc:
        safe_error = html.escape(str(exc))
        return HTMLResponse(
            layout(
                "Erreur création société",
                f"""
                <h2>Créer une société</h2>
                <div class="error">Impossible de créer la société : {safe_error}</div>
                <p><a class="button secondary" href="/server/companies/new">Retour</a></p>
                """
            ),
            status_code=400,
        )

    return RedirectResponse(url="/server/companies", status_code=303)



def require_owner_or_super_admin(request: Request):
    return require_roles(request, ["OWNER", "SUPER_ADMIN"])


def require_super_admin(request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    email = get_logged_user_email(request)
    if not email:
        return RedirectResponse(url="/login", status_code=303)

    import server_user_model as identity

    if not identity.user_has_any_role(email, ["OWNER", "SUPER_ADMIN"]):
        return HTMLResponse(
            layout(
                "Accès refusé",
                """
                <div class="error">
                    Accès réservé au propriétaire ou au super administrateur.
                </div>
                <p><a class="button secondary" href="/">Retour accueil</a></p>
                """
            ),
            status_code=403,
        )

    return None




@app.post("/server/users/{user_id}/status/{status}")
def server_user_status_change(user_id: int, status: str, request: Request):
    admin_response = require_owner_or_super_admin(request)
    if admin_response:
        return admin_response

    import server_user_model as identity

    current_email = get_logged_user_email(request)
    current_user = identity.get_user_by_email(current_email) if current_email else None

    if current_user and current_user["id"] == user_id and status != "active":
        return HTMLResponse(
            layout(
                "Action refusée",
                """
                <div class="error">
                    Tu ne peux pas désactiver ton propre compte administrateur.
                </div>
                <p><a class="button secondary" href="/server/users">Retour gestion utilisateurs</a></p>
                """
            ),
            status_code=400,
        )

    try:
        identity.set_user_status(user_id, status)
    except Exception as exc:
        return HTMLResponse(
            layout(
                "Erreur utilisateur",
                f"""
                <div class="error">
                    Impossible de modifier le statut utilisateur : {exc}
                </div>
                <p><a class="button secondary" href="/server/users">Retour gestion utilisateurs</a></p>
                """
            ),
            status_code=400,
        )

    return RedirectResponse(url="/server/users", status_code=303)




@app.post("/server/users/{user_id}/company/{company_id}/status/{status}")
def server_company_access_status_change(user_id: int, company_id: int, status: str, request: Request):
    admin_response = require_owner_or_super_admin(request)
    if admin_response:
        return admin_response

    import server_user_model as identity

    current_email = get_logged_user_email(request)
    current_user = identity.get_user_by_email(current_email) if current_email else None

    if current_user and current_user["id"] == user_id and status != "active":
        return HTMLResponse(
            layout(
                "Action refusée",
                """
                <div class="error">
                    Tu ne peux pas désactiver ton propre accès société depuis cette page.
                </div>
                <p><a class="button secondary" href="/server/users">Retour gestion utilisateurs</a></p>
                """
            ),
            status_code=400,
        )

    try:
        identity.set_company_access_status(user_id, company_id, status)
    except Exception as exc:
        return HTMLResponse(
            layout(
                "Erreur accès société",
                f"""
                <div class="error">
                    Impossible de modifier l’accès société : {exc}
                </div>
                <p><a class="button secondary" href="/server/users">Retour gestion utilisateurs</a></p>
                """
            ),
            status_code=400,
        )

    return RedirectResponse(url="/server/users", status_code=303)




@app.post("/server/users/{user_id}/company/{company_id}/role")
async def server_company_access_role_change(user_id: int, company_id: int, request: Request):
    admin_response = require_owner_or_super_admin(request)
    if admin_response:
        return admin_response

    import server_user_model as identity

    form = await request.form()
    role = str(form.get("role") or "").strip()

    current_email = get_logged_user_email(request)
    current_user = identity.get_user_by_email(current_email) if current_email else None

    if current_user and current_user["id"] == user_id and role not in ["OWNER", "SUPER_ADMIN"]:
        return HTMLResponse(
            layout(
                "Action refusée",
                """
                <div class="error">
                    Tu ne peux pas retirer ton propre rôle administrateur depuis cette page.
                </div>
                <p><a class="button secondary" href="/server/users">Retour gestion utilisateurs</a></p>
                """
            ),
            status_code=400,
        )

    try:
        identity.set_company_access_role(user_id, company_id, role)
    except Exception as exc:
        return HTMLResponse(
            layout(
                "Erreur rôle société",
                f"""
                <div class="error">
                    Impossible de modifier le rôle société : {exc}
                </div>
                <p><a class="button secondary" href="/server/users">Retour gestion utilisateurs</a></p>
                """
            ),
            status_code=400,
        )

    return RedirectResponse(url="/server/users", status_code=303)




@app.post("/server/users/access/create")
async def server_users_create_company_access(request: Request):
    admin_response = require_owner_or_super_admin(request)
    if admin_response:
        return admin_response

    import server_user_model as identity

    form = await request.form()

    try:
        user_id = int(form.get("user_id") or 0)
        company_id = int(form.get("company_id") or 0)
        role = str(form.get("role") or "").strip()

        if user_id <= 0 or company_id <= 0:
            raise ValueError("Utilisateur ou société invalide")

        if role not in ["OWNER", "SUPER_ADMIN", "COMPANY_ADMIN", "CONTRACT_MANAGER", "TESTER"]:
            raise ValueError("Rôle invalide")

        identity.grant_company_access(company_id, user_id, role)

    except Exception as exc:
        return HTMLResponse(
            layout(
                "Erreur création accès",
                f"""
                <div class="error">
                    Impossible de créer l’accès société : {exc}
                </div>
                <p><a class="button secondary" href="/server/users">Retour gestion utilisateurs</a></p>
                """
            ),
            status_code=400,
        )

    return RedirectResponse(url="/server/users", status_code=303)




@app.post("/server/users/create")
async def server_users_create_user(request: Request):
    admin_response = require_owner_or_super_admin(request)
    if admin_response:
        return admin_response

    import server_user_model as identity

    form = await request.form()

    email = str(form.get("email") or "").strip().lower()
    full_name = str(form.get("full_name") or "").strip()
    temporary_password = str(form.get("temporary_password") or "").strip()
    status = str(form.get("status") or "inactive").strip()
    company_id = int(form.get("company_id") or 0)
    role = str(form.get("role") or "TESTER").strip()

    try:
        identity.create_user_with_temporary_password(
            email=email,
            full_name=full_name,
            temporary_password=temporary_password,
            status=status,
        )

        if company_id > 0:
            created_user = identity.get_user_by_email(email)
            if created_user is None:
                raise ValueError("Utilisateur créé mais introuvable pour rattachement société")

            if role not in ["OWNER", "SUPER_ADMIN", "COMPANY_ADMIN", "CONTRACT_MANAGER", "TESTER"]:
                raise ValueError("Rôle invalide")

            identity.grant_company_access(
                company_id,
                int(created_user["id"]),
                role,
            )

    except Exception as exc:
        return HTMLResponse(
            layout(
                "Erreur création utilisateur",
                f"""
                <div class="error">
                    Impossible de créer l’utilisateur : {exc}
                </div>
                <p><a class="button secondary" href="/server/users">Retour gestion utilisateurs</a></p>
                """
            ),
            status_code=400,
        )

    return RedirectResponse(url="/server/users", status_code=303)


@app.post("/server/users/{user_id}/password")
async def server_user_password_change(user_id: int, request: Request):
    admin_response = require_owner_or_super_admin(request)
    if admin_response:
        return admin_response

    import server_user_model as identity

    form = await request.form()
    temporary_password = str(form.get("temporary_password") or "").strip()

    try:
        identity.set_user_password_by_id(user_id, temporary_password)
    except Exception as exc:
        return HTMLResponse(
            layout(
                "Erreur mot de passe",
                f"""
                <div class="error">
                    Impossible de modifier le mot de passe : {exc}
                </div>
                <p><a class="button secondary" href="/server/users">Retour gestion utilisateurs</a></p>
                """
            ),
            status_code=400,
        )

    return RedirectResponse(url="/server/users", status_code=303)




def generate_temporary_password(length: int = 16):
    import secrets

    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!?#@"
    return "".join(secrets.choice(alphabet) for _ in range(length))


@app.get("/server/users", response_class=HTMLResponse)
def server_users_settings_page(request: Request):
    admin_response = require_owner_or_super_admin(request)
    if admin_response:
        return admin_response

    import server_user_model as identity

    rows = identity.list_user_settings_rows()
    users = identity.list_users()
    companies = identity.list_companies()
    suggested_password = generate_temporary_password()

    user_options = ""
    for user_item in users:
        user_options += f"<option value=\"{user_item['id']}\">{user_item['email']} — {user_item['full_name'] or ''}</option>"

    company_options = ""
    for company_item in companies:
        company_options += f"<option value=\"{company_item['id']}\">{company_item['name']}</option>"

    grouped = {}
    for row in rows:
        email = row["email"] or ""
        if email not in grouped:
            grouped[email] = {
                "user_id": row["user_id"],
                "email": email,
                "full_name": row["full_name"] or "",
                "user_status": row["user_status"] or "",
                "created_at": row["created_at"] or "",
                "access": [],
            }

        if row["company_name"]:
            next_access_status = "inactive" if row["access_status"] == "active" else "active"
            access_button_label = "Désactiver accès société" if row["access_status"] == "active" else "Activer accès société"

            grouped[email]["access"].append(
                f"""
                <div style="margin-bottom:12px;">
                    <strong>{row['company_name']}</strong> — {row['role']} — {row['access_status']}

                    <form method="post" action="/server/users/{row['user_id']}/company/{row['company_id']}/status/{next_access_status}" style="display:inline; margin-left:8px;">
                        <button type="submit">{access_button_label}</button>
                    </form>

                    <form method="post" action="/server/users/{row['user_id']}/company/{row['company_id']}/role" style="display:inline; margin-left:8px;">
                        <select name="role">
                            <option value="OWNER" {"selected" if row['role'] == "OWNER" else ""}>OWNER</option>
                            <option value="SUPER_ADMIN" {"selected" if row['role'] == "SUPER_ADMIN" else ""}>SUPER_ADMIN</option>
                            <option value="COMPANY_ADMIN" {"selected" if row['role'] == "COMPANY_ADMIN" else ""}>COMPANY_ADMIN</option>
                            <option value="CONTRACT_MANAGER" {"selected" if row['role'] == "CONTRACT_MANAGER" else ""}>CONTRACT_MANAGER</option>
                            <option value="TESTER" {"selected" if row['role'] == "TESTER" else ""}>TESTER</option>
                        </select>
                        <button type="submit">Enregistrer rôle</button>
                    </form>
                </div>
                """
            )

    user_rows = ""
    for user in grouped.values():
        access_html = "<br>".join(user["access"]) if user["access"] else "<em>Aucun accès société actif</em>"
        next_status = "inactive" if user["user_status"] == "active" else "active"
        button_label = "Désactiver" if user["user_status"] == "active" else "Activer"

        user_rows += f"""
        <tr>
            <td>{user['user_id']}</td>
            <td>{user['email']}</td>
            <td>{user['full_name']}</td>
            <td>{user['user_status']}</td>
            <td>{access_html}</td>
            <td>{user['created_at']}</td>
            <td>
                <form method="post" action="/server/users/{user['user_id']}/status/{next_status}" style="margin:0 0 8px 0;">
                    <button type="submit">{button_label}</button>
                </form>

                <form method="post" action="/server/users/{user['user_id']}/password" style="margin:0;">
                    <input type="password" name="temporary_password" autocomplete="new-password" placeholder="Nouveau mot de passe temporaire" required>
                    <button type="submit">Changer mot de passe</button>
                </form>
            </td>
        </tr>
        """

    content = f"""
    <h2>Gestion des utilisateurs</h2>
    <div class="card">
        <p>
            Cette page sert à créer les comptes, attribuer les accès société,
            gérer les rôles et réinitialiser les mots de passe temporaires.
        </p>
        <p>
            Un utilisateur doit avoir un compte actif ET un accès société actif pour se connecter.
        </p>
    </div>

    <div class="card">
        <h3>Mot de passe temporaire suggéré</h3>
        <p>
            Copier ce mot de passe pour créer un utilisateur ou réinitialiser un accès.
        </p>
        <p style="font-size:20px; font-weight:700; letter-spacing:1px;">
            {suggested_password}
        </p>
        <p>
            Recharger la page pour générer une nouvelle suggestion.
        </p>
    </div>

    <div class="card">
        <p>
            Administration réservée aux rôles <strong>OWNER</strong> et <strong>SUPER_ADMIN</strong>.
        </p>
    </div>

    <div class="card">
        <h3>Créer un nouvel utilisateur</h3>
        <p>
            Par défaut, créer l’utilisateur en statut <strong>inactif</strong>.
            Il ne pourra pas se connecter tant que son compte et son accès société ne sont pas actifs.
        </p>

        <form method="post" action="/server/users/create">
            <label>Email
                <input type="email" name="email" autocomplete="username" required>
            </label>

            <label>Nom
                <input type="text" name="full_name">
            </label>

            <label>Mot de passe temporaire
                <input type="password" name="temporary_password" autocomplete="new-password" required>
            </label>

            <label>Statut
                <select name="status">
                    <option value="inactive">inactive — à valider</option>
                    <option value="active">active — validé directement</option>
                </select>
            </label>

            <label>Société à rattacher
                <select name="company_id">
                    <option value="0">Aucune pour le moment</option>
                    {company_options}
                </select>
            </label>

            <label>Rôle dans cette société
                <select name="role">
                    <option value="TESTER">TESTER</option>
                    <option value="CONTRACT_MANAGER">CONTRACT_MANAGER</option>
                    <option value="COMPANY_ADMIN">COMPANY_ADMIN</option>
                    <option value="SUPER_ADMIN">SUPER_ADMIN</option>
                    <option value="OWNER">OWNER</option>
                </select>
            </label>

            <button type="submit">Créer l’utilisateur et l’accès</button>
        </form>
    </div>

    <div class="card">
        <h3>Ajouter un accès à une société</h3>
        <form method="post" action="/server/users/access/create">
            <label>Utilisateur
                <select name="user_id">
                    {user_options}
                </select>
            </label>

            <label>Société
                <select name="company_id">
                    {company_options}
                </select>
            </label>

            <label>Rôle
                <select name="role">
                    <option value="TESTER">TESTER</option>
                    <option value="CONTRACT_MANAGER">CONTRACT_MANAGER</option>
                    <option value="COMPANY_ADMIN">COMPANY_ADMIN</option>
                    <option value="SUPER_ADMIN">SUPER_ADMIN</option>
                    <option value="OWNER">OWNER</option>
                </select>
            </label>

            <button type="submit">Créer accès</button>
        </form>
    </div>

    <table>
        <thead>
            <tr>
                <th>ID</th>
                <th>Email</th>
                <th>Nom</th>
                <th>Statut utilisateur</th>
                <th>Accès sociétés / rôles</th>
                <th>Créé le</th>
                <th>Action</th>
            </tr>
        </thead>
        <tbody>
            {user_rows}
        </tbody>
    </table>
    """

    return layout("Gestion des utilisateurs", content)

@app.middleware("http")
async def hide_admin_menu_links_for_non_admin(request: Request, call_next):
    response = await call_next(request)

    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type.lower():
        return response

    token = request.cookies.get("dealer_quote_session")
    email = None

    if token:
        import session_security
        email = session_security.verify_session_token(token)

    roles = []
    if email:
        import server_user_model as identity
        context = identity.get_active_company_context(email)
        if context and context.get("role"):
            roles.append(str(context.get("role")).upper())

    is_owner_or_super_admin = any(role in ("OWNER", "SUPER_ADMIN") for role in roles)
    is_global_settings_admin = any(role in ("OWNER", "SUPER_ADMIN", "COMPANY_ADMIN") for role in roles)

    body = b""
    async for chunk in response.body_iterator:
        body += chunk

    html = body.decode("utf-8", errors="replace")

    owner_only_links = [
        '        <a href="/server/users">Utilisateurs</a>\n',
    ]

    global_settings_links = [
        '        <a href="/settings">Paramètres calcul</a>\n',
        '        <a href="/dealer-discounts">Codes remises</a>\n',
        '        <a href="/price-catalog">Catalogue pièces</a>\n',
        '        <a href="/server/company-branding">Identité société</a>\n',
    ]

    if not is_owner_or_super_admin:
        for link in owner_only_links:
            html = html.replace(link, "")

    if not is_global_settings_admin:
        for link in global_settings_links:
            html = html.replace(link, "")

    from fastapi.responses import HTMLResponse

    clean_headers = dict(response.headers)
    clean_headers.pop("content-length", None)
    clean_headers.pop("Content-Length", None)

    return HTMLResponse(
        content=html,
        status_code=response.status_code,
        headers=clean_headers,
    )


from zoneinfo import ZoneInfo

PARIS_TIMEZONE = ZoneInfo("Europe/Paris")


def format_paris_datetime(value):
    if not value:
        return "-"

    from datetime import datetime, timezone

    text = str(value).strip()

    try:
        dt = datetime.fromisoformat(
            text.replace("Z", "+00:00")
        )
    except ValueError:
        return text

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    dt = dt.astimezone(PARIS_TIMEZONE)

    return dt.strftime("%d/%m/%Y %H:%M")

@app.get("/server/context")
def server_context_page(request: Request):
    from fastapi.responses import HTMLResponse
    import server_user_model as identity

    email = get_logged_user_email(request)
    context = identity.get_active_company_context(email) if email else None

    if not context:
        return HTMLResponse(
            """
            <html>
            <head><title>Contexte société</title></head>
            <body style="font-family:Arial;padding:30px;">
                <h1>Contexte société</h1>
                <p>Aucun contexte société actif trouvé.</p>
                <p><a href="/server/users">Retour gestion utilisateurs</a></p>
            </body>
            </html>
            """,
            status_code=403,
        )

    return HTMLResponse(
        f"""
        <html>
        <head>
            <title>Contexte société</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    background: #f3f4f6;
                    padding: 30px;
                }}
                .card {{
                    background: white;
                    border-radius: 14px;
                    padding: 24px;
                    max-width: 760px;
                    box-shadow: 0 10px 30px rgba(0,0,0,.08);
                }}
                table {{
                    border-collapse: collapse;
                    width: 100%;
                }}
                td {{
                    border-bottom: 1px solid #e5e7eb;
                    padding: 10px;
                }}
                td:first-child {{
                    font-weight: 700;
                    width: 260px;
                }}
                a {{
                    display: inline-block;
                    margin-top: 18px;
                }}
            </style>
        </head>
        <body>
            <div class="card">
                <h1>Contexte société actif</h1>
                <table>
                    <tr><td>Email utilisateur</td><td>{context["email"]}</td></tr>
                    <tr><td>Nom utilisateur</td><td>{context["full_name"]}</td></tr>
                    <tr><td>Statut utilisateur</td><td>{context["user_status"]}</td></tr>
                    <tr><td>ID société</td><td>{context["company_id"]}</td></tr>
                    <tr><td>Société active</td><td>{context["company_name"]}</td></tr>
                    <tr><td>Rôle actif</td><td>{context["role"]}</td></tr>
                    <tr><td>Statut accès société</td><td>{context["access_status"]}</td></tr>
                    <tr><td>Table accès détectée</td><td>{context["access_table"]}</td></tr>
                </table>
                <a href="/">Retour accueil</a>
            </div>
        </body>
        </html>
        """
    )


def get_request_company_context(request: Request):
    import server_user_model as identity

    email = get_logged_user_email(request)
    if not email:
        return None

    return identity.get_active_company_context(email)


def company_context_required_page():
    from fastapi.responses import HTMLResponse

    return HTMLResponse(
        """
        <html>
        <head>
            <title>Accès société requis</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    background: #f3f4f6;
                    padding: 40px;
                }
                .card {
                    max-width: 620px;
                    margin: 80px auto;
                    background: white;
                    padding: 28px;
                    border-radius: 14px;
                    box-shadow: 0 10px 30px rgba(0,0,0,.08);
                }
                h1 {
                    margin-top: 0;
                    color: #991b1b;
                }
                p {
                    line-height: 1.5;
                }
                a {
                    display: inline-block;
                    margin-top: 18px;
                }
            </style>
        </head>
        <body>
            <div class="card">
                <h1>Accès société requis</h1>
                <p>Aucun contexte société actif n’est disponible pour votre compte.</p>
                <p>Contactez votre administrateur ou reconnectez-vous.</p>
                <a href="/logout">Retour connexion</a>
            </div>
        </body>
        </html>
        """,
        status_code=403,
    )


@app.middleware("http")
async def require_company_context_for_sensitive_routes(request: Request, call_next):
    sensitive_prefixes = (
        "/import",
        "/quotes",
        "/quote",
        "/export",
        "/settings",
        "/dealer-discounts",
        "/price-catalog",
    )

    path = request.url.path

    if path.startswith(sensitive_prefixes):
        context = get_request_company_context(request)
        if not context:
            return company_context_required_page()

    return await call_next(request)


def quote_access_denied_page():
    from fastapi.responses import HTMLResponse

    return HTMLResponse(
        """
        <html>
        <head>
            <title>Accès devis refusé</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    background: #f3f4f6;
                    padding: 40px;
                }
                .card {
                    max-width: 620px;
                    margin: 80px auto;
                    background: white;
                    padding: 28px;
                    border-radius: 14px;
                    box-shadow: 0 10px 30px rgba(0,0,0,.08);
                }
                h1 {
                    margin-top: 0;
                    color: #991b1b;
                }
                a {
                    display: inline-block;
                    margin-top: 18px;
                }
            </style>
        </head>
        <body>
            <div class="card">
                <h1>Accès devis refusé</h1>
                <p>Ce devis n’appartient pas à votre société active.</p>
                <p>Vous ne pouvez pas consulter, modifier ou exporter les données d’une autre société.</p>
                <a href="/">Retour accueil</a>
            </div>
        </body>
        </html>
        """,
        status_code=403,
    )


@app.middleware("http")
async def guard_quote_company_access(request: Request, call_next):
    import re
    import server_user_model as identity

    path = request.url.path

    match = re.match(r"^/quote/(\d+)(/|$)", path)
    if match:
        quote_id = int(match.group(1))

        context = get_request_company_context(request)
        if not context:
            return company_context_required_page()

        company_id = context["company_id"]

        if not identity.quote_belongs_to_company(quote_id, company_id):
            return quote_access_denied_page()

    return await call_next(request)


def admin_required_page():
    from fastapi.responses import HTMLResponse

    return HTMLResponse(
        """
        <html>
        <head>
            <title>Accès admin requis</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    background: #f3f4f6;
                    padding: 40px;
                }
                .card {
                    max-width: 620px;
                    margin: 80px auto;
                    background: white;
                    padding: 28px;
                    border-radius: 14px;
                    box-shadow: 0 10px 30px rgba(0,0,0,.08);
                }
                h1 {
                    margin-top: 0;
                    color: #991b1b;
                }
                a {
                    display: inline-block;
                    margin-top: 18px;
                }
            </style>
        </head>
        <body>
            <div class="card">
                <h1>Accès admin requis</h1>
                <p>Cette page modifie des réglages globaux du serveur.</p>
                <p>Elle est réservée aux administrateurs.</p>
                <a href="/">Retour accueil</a>
            </div>
        </body>
        </html>
        """,
        status_code=403,
    )


@app.middleware("http")
async def require_admin_for_global_settings_routes(request: Request, call_next):
    admin_prefixes = (
        "/settings",
        "/dealer-discounts",
        "/price-catalog",
        "/server/company-branding",
    )

    path = request.url.path

    if path.startswith(admin_prefixes):
        context = get_request_company_context(request)
        if not context:
            return company_context_required_page()

        role = str(context.get("role") or "").upper()
        if role not in ("OWNER", "SUPER_ADMIN", "COMPANY_ADMIN"):
            return admin_required_page()

    return await call_next(request)


@app.middleware("http")
async def require_owner_for_server_identity_routes(request: Request, call_next):
    path = request.url.path

    protected_paths = (
        "/server/identity",
        "/server/identity/new",
        "/server/companies",
        "/server/companies/new",
    )

    if path in protected_paths:
        admin_response = require_owner_or_super_admin(request)
        if admin_response:
            return admin_response

    return await call_next(request)

