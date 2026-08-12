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
from service_2_2_detail_calculation import apply_service_2_2_detail_calculation

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
        <a href="/settings">Paramètres dealer</a>
        <a href="/dealer-discounts">Remise dealer</a>
        <a href="/price-catalog">Import price list</a>
        <a href="/server/company-switch">Changer société</a>
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




@app.get("/server/company-switch", response_class=HTMLResponse)
def server_company_switch_page(request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    import server_user_model as identity

    email = get_logged_user_email(request)
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

    rows_html = ""
    for row in rows:
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
        pdf_link = f'<a class="button gold" href="/exports/quote_{quote_id}.pdf" target="_blank">PDF</a>' if pdf_path.exists() else ""
        html_link = f'<a class="button secondary" href="/exports/quote_{quote_id}.html" target="_blank">HTML</a>' if html_path.exists() else ""

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
                <a class="button secondary" href="/quote/{quote_id}/export">Générer offre client</a>
                {html_link}{pdf_link}
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
                            <option>Paramètres dealer</option>
                            <option>Remise dealer</option>
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
            service_2_2_detail = apply_service_2_2_detail_calculation(quote_id, upload_path)
            print(f"Overview C -> service 2.2 : {overview_totals}")
        except Exception as exc:
            print(f"Attention : impossible de remonter Overview C vers 2.2 : {exc}")

        run_command([sys.executable, "backend/app/apply_pricing.py", str(quote_id)])
        run_command([sys.executable, "backend/app/export_quote_html.py", str(quote_id)])
        run_command([sys.executable, "backend/app/export_quote_pdf.py", str(quote_id)])

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


@app.get("/quote/{quote_id}/inputs", response_class=HTMLResponse)
def quote_inputs_page(quote_id: int, request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

    init_db()
    ensure_quote_services(quote_id)
    with get_connection() as conn:
        quote = get_quote_for_active_company_request(conn, quote_id, request)

    if quote is None:
        return quote_access_denied_response(quote_id)

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
            </select></label>
        </div>
        <h3>Contrat & coûts importés</h3>
        <div class="card grid">
            <label>Contract length calculée<input type="number" step="0.01" value="{fmt_number(contract_years)}" disabled></label>
            <label>Total calculation hours<input type="number" step="0.01" name="total_hours" value="{fmt_number(quote['total_hours'])}"></label>
            <label>Op hours per year<input type="number" step="0.01" name="hours_per_year" value="{fmt_number(quote['hours_per_year'])}"></label>
            <label>Taux horaire main-d’œuvre input<input type="number" step="0.01" name="labour_rate" value="{fmt_number(quote['labour_rate'])}"></label>
            <label>Coût total pièces<input type="number" step="0.01" name="total_parts" value="{fmt_number(quote['total_parts'])}"></label>
            <label>Coût total main-d’œuvre<input type="number" step="0.01" name="total_labour" value="{fmt_number(quote['total_labour'])}"></label>
            <label>Coût divers<input type="number" step="0.01" name="total_misc" value="{fmt_number(quote['total_misc'])}"></label>
            <label>Devise<input type="text" name="currency" value="{quote['currency'] or 'EUR'}"></label>
        </div>
        <button type="submit">Enregistrer données contrat + recalculer</button>
        <a class="button" href="/quote/{quote_id}/services">Construction de l’offre</a>
        <a class="button secondary" href="/">Retour offres contrats</a>
    </form>"""
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
    currency: str = Form("EUR"),
):
    login_response = require_login(request)
    if login_response:
        return login_response

    init_db()

    with get_connection() as conn:
        quote = get_quote_for_active_company_request(conn, quote_id, request)
        if quote is None:
            return quote_access_denied_response(quote_id)

    total_cost = (total_parts or 0) + (total_labour or 0) + (total_misc or 0)
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE quotes
            SET customer_name=?, product_designation=?, engine_serial_number=?, product_name=?, country=?, status=?,
                total_hours=?, hours_per_year=?, labour_rate=?, total_parts=?, total_labour=?, total_misc=?, total_cost=?, currency=?
            WHERE id=? AND company_id=?
            """,
            (customer_name.strip(), product_designation.strip(), engine_serial_number.strip(), product_name.strip(), country.strip(), status,
             total_hours, hours_per_year, labour_rate, total_parts, total_labour, total_misc, total_cost, currency.strip() or "EUR", quote_id, get_active_company_id_for_request(request)),
        )
        conn.commit()

    regenerate_quote(quote_id)
    return RedirectResponse(url=f"/quote/{quote_id}/inputs", status_code=303)

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

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    login_response = require_login(request)
    if login_response:
        return login_response

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
    request: Request,
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

    match = re.match(r"^quote_(\d+)\.(pdf|html)$", filename or "")
    if match:
        quote_id = int(match.group(1))
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
            <div><a href="/quote/{quote_id}/services">Prestations incluses au contrat & temps</a> | <a href="/">Accueil</a></div>
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
    login_response = require_login(request)
    if login_response:
        return login_response

    form = await request.form()
    _dd_update_codes(form)
    return _DealerDiscountRedirectResponse(url="/dealer-discounts", status_code=303)

@app.get("/dealer-discounts/reset")
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
        <title>Import price list</title>
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
        <h1>Import price list</h1>
        <p><a href="/">Accueil</a></p>

        <div class="panel">
            <b>Catalogue actuel :</b> {status['count']} références<br>
            <b>Dernier fichier :</b> {status['source_file'] or '-'}<br>
            <b>Dernière mise à jour :</b> {status['updated_at'] or '-'}
        </div>

        <div class="panel">
            <h2>Importer le fichier prix DSP</h2>
            <form method="post" action="/price-catalog/upload" enctype="multipart/form-data">
                <input type="file" name="file" accept=".xlsx,.xlsm,.xls">
                <button type="submit">Importer le catalogue prix</button>
            </form>
            <p>Colonnes attendues : Part No, Description, Price excl VAT, Discount Code.</p>
        </div>

        <div class="panel">
            <h2>Rechercher une référence</h2>
            <form method="get" action="/price-catalog">
                <input name="q" value="{q}" placeholder="Référence ou désignation">
                <button type="submit">Rechercher</button>
            </form>
        </div>

        <table>
            <thead>
                <tr>
                    <th>Part No</th>
                    <th>Désignation</th>
                    <th>Prix excl VAT</th>
                    <th>DC</th>
                </tr>
            </thead>
            <tbody>{result_rows}</tbody>
        </table>
    </body>
    </html>
    """

@app.post("/price-catalog/upload")
async def price_catalog_upload(request: Request, file: _OptionUploadFile = _OptionFile(...)):
    login_response = require_login(request)
    if login_response:
        return login_response

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
        <p><a href="/price-catalog">Retour catalogue</a></p>
        <p><a href="/">Accueil</a></p>
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
                    Part No → Désignation → Prix excl VAT → DC.
                </p>
                <p class="catalog-status">
                    Catalogue prix : <b>{catalog['count']}</b> références
                    {f" / {catalog['source_file']}" if catalog['source_file'] else ""}
                    — <a href="/price-catalog">Importer / rechercher catalogue</a>
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
                        <th>DC</th>
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

    try:
        identity.create_user_with_temporary_password(
            email=email,
            full_name=full_name,
            temporary_password=temporary_password,
            status=status,
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

            <button type="submit">Créer l’utilisateur</button>
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
        '        <a href="/settings">Paramètres dealer</a>\n',
        '        <a href="/dealer-discounts">Remise dealer</a>\n',
        '        <a href="/price-catalog">Import price list</a>\n',
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
    )

    if path in protected_paths:
        admin_response = require_owner_or_super_admin(request)
        if admin_response:
            return admin_response

    return await call_next(request)

