from datetime import datetime
import sqlite3
from pathlib import Path

import app_config as config
from server_identity import ServerRole


def get_sqlite_db_path() -> Path:
    if not config.DATABASE_URL.startswith("sqlite:///"):
        raise RuntimeError("server_user_model utilise SQLite uniquement pour la préparation locale")

    db_relative = config.DATABASE_URL.replace("sqlite:///", "", 1)
    return config.BASE_DIR / db_relative


def get_connection():
    db_path = get_sqlite_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_server_identity_tables():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                full_name TEXT,
                password_hash TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS company_access (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(company_id, user_id, role),
                FOREIGN KEY(company_id) REFERENCES companies(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        conn.commit()


def create_company(name: str, slug: str) -> int:
    now = datetime.now().isoformat(timespec="seconds")

    with get_connection() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO companies (name, slug, status, created_at, updated_at)
            VALUES (?, ?, 'active', ?, ?)
        """, (name, slug, now, now))

        row = conn.execute(
            "SELECT id FROM companies WHERE slug = ?",
            (slug,),
        ).fetchone()

        conn.commit()
        return int(row["id"])



def get_default_company_id() -> int:
    """
    Société active temporaire pour le développement local.
    Plus tard, cette valeur viendra de l'utilisateur connecté.
    """
    init_server_identity_tables()
    return create_company("Gwen Service", "gwen-service")



def get_company_by_id(company_id: int):
    with get_connection() as conn:
        return conn.execute(
            "SELECT id, name, slug, status FROM companies WHERE id = ?",
            (company_id,),
        ).fetchone()


def get_active_company_file() -> Path:
    return config.BASE_DIR / "data" / "server_active_company_id.txt"


def set_active_company_id(company_id: int) -> int:
    init_server_identity_tables()

    company = get_company_by_id(company_id)
    if company is None:
        raise ValueError(f"Société introuvable : {company_id}")

    active_file = get_active_company_file()
    active_file.parent.mkdir(parents=True, exist_ok=True)
    active_file.write_text(str(company_id), encoding="utf-8")

    return company_id


def get_active_company_id() -> int:
    """
    Société active temporaire en développement.
    Plus tard, cette valeur viendra du login utilisateur.
    """
    init_server_identity_tables()

    active_file = get_active_company_file()

    if active_file.exists():
        try:
            company_id = int(active_file.read_text(encoding="utf-8").strip())
            if get_company_by_id(company_id) is not None:
                return company_id
        except ValueError:
            pass

    default_company_id = get_default_company_id()
    set_active_company_id(default_company_id)
    return default_company_id


def get_active_company_name() -> str:
    company_id = get_active_company_id()
    company = get_company_by_id(company_id)
    return company["name"] if company else f"Société ID {company_id}"


def create_user(email: str, full_name: str = "") -> int:
    now = datetime.now().isoformat(timespec="seconds")

    with get_connection() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO users (email, full_name, status, created_at, updated_at)
            VALUES (?, ?, 'active', ?, ?)
        """, (email.lower().strip(), full_name, now, now))

        row = conn.execute(
            "SELECT id FROM users WHERE email = ?",
            (email.lower().strip(),),
        ).fetchone()

        conn.commit()
        return int(row["id"])



def set_user_password(email: str, password: str) -> bool:
    from password_security import hash_password

    email = email.lower().strip()
    password_hash = hash_password(password)
    now = datetime.now().isoformat(timespec="seconds")

    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE email = ?",
            (email,),
        ).fetchone()

        if row is None:
            return False

        conn.execute(
            """
            UPDATE users
            SET password_hash = ?, updated_at = ?
            WHERE email = ?
            """,
            (password_hash, now, email),
        )

        conn.commit()
        return True


def verify_user_password(email: str, password: str) -> bool:
    from password_security import verify_password

    email = email.lower().strip()

    with get_connection() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE email = ? AND status = 'active'",
            (email,),
        ).fetchone()

        if row is None or not row["password_hash"]:
            return False

        return verify_password(password, row["password_hash"])


def grant_company_access(company_id: int, user_id: int, role: str) -> int:
    ServerRole(role)
    now = datetime.now().isoformat(timespec="seconds")

    with get_connection() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO company_access
            (company_id, user_id, role, status, created_at, updated_at)
            VALUES (?, ?, ?, 'active', ?, ?)
        """, (company_id, user_id, role, now, now))

        row = conn.execute("""
            SELECT id FROM company_access
            WHERE company_id = ? AND user_id = ? AND role = ?
        """, (company_id, user_id, role)).fetchone()

        conn.commit()
        return int(row["id"])


def list_companies():
    with get_connection() as conn:
        return conn.execute("""
            SELECT id, name, slug, status, created_at
            FROM companies
            ORDER BY id
        """).fetchall()


def list_users():
    with get_connection() as conn:
        return conn.execute("""
            SELECT id, email, full_name, status, created_at
            FROM users
            ORDER BY id
        """).fetchall()


def list_company_access():
    with get_connection() as conn:
        return conn.execute("""
            SELECT
                ca.id,
                c.name AS company_name,
                u.email AS user_email,
                ca.role,
                ca.status
            FROM company_access ca
            JOIN companies c ON c.id = ca.company_id
            JOIN users u ON u.id = ca.user_id
            ORDER BY ca.id
        """).fetchall()


if __name__ == "__main__":
    init_server_identity_tables()

    company_id = create_company("Gwen Service", "gwen-service")
    user_id = create_user("gregoire.philippon@gmail.com", "Greg")

    grant_company_access(company_id, user_id, ServerRole.OWNER.value)

    print("Companies:")
    for row in list_companies():
        print(dict(row))

    print("Users:")
    for row in list_users():
        print(dict(row))

    print("Access:")
    for row in list_company_access():
        print(dict(row))
