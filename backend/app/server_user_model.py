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
            "SELECT password_hash FROM users WHERE email = ?",
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


def get_user_by_email(email: str):
    init_server_identity_tables()

    email = (email or "").strip().lower()

    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                id,
                email,
                full_name,
                status,
                created_at,
                updated_at
            FROM users
            WHERE lower(email) = lower(?)
            """,
            (email,),
        ).fetchone()


def list_companies_for_user(email: str):
    email = email.lower().strip()

    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                c.id,
                c.name,
                c.slug,
                ca.role,
                ca.status
            FROM users u
            JOIN company_access ca ON ca.user_id = u.id
            JOIN companies c ON c.id = ca.company_id
            WHERE u.email = ?
              AND u.status = 'active'
              AND ca.status = 'active'
            ORDER BY c.name
            """,
            (email,),
        ).fetchall()


def user_has_company_access(email: str, company_id: int) -> bool:
    companies = list_companies_for_user(email)
    return any(int(company["id"]) == int(company_id) for company in companies)


def get_user_active_company_file(email: str) -> Path:
    import hashlib

    email = email.lower().strip()
    user_key = hashlib.sha256(email.encode("utf-8")).hexdigest()[:16]
    return config.BASE_DIR / "data" / f"server_active_company_{user_key}.txt"


def set_active_company_id_for_user(email: str, company_id: int) -> int:
    email = email.lower().strip()
    company_id = int(company_id)

    if not user_has_company_access(email, company_id):
        raise ValueError(f"Utilisateur sans accès à la société {company_id}")

    active_file = get_user_active_company_file(email)
    active_file.parent.mkdir(parents=True, exist_ok=True)
    active_file.write_text(str(company_id), encoding="utf-8")

    return company_id


def get_active_company_id_for_user(email: str) -> int:
    email = email.lower().strip()
    companies = list_companies_for_user(email)

    if not companies:
        return get_default_company_id()

    active_file = get_user_active_company_file(email)

    if active_file.exists():
        try:
            company_id = int(active_file.read_text(encoding="utf-8").strip())
            if user_has_company_access(email, company_id):
                return company_id
        except Exception:
            pass

    first_company_id = int(companies[0]["id"])
    set_active_company_id_for_user(email, first_company_id)
    return first_company_id


def get_active_company_name_for_user(email: str) -> str:
    company_id = get_active_company_id_for_user(email)
    company = get_company_by_id(company_id)

    if company is None:
        return f"Société ID {company_id}"

    return company["name"]

def get_active_roles_for_user(email: str):
    init_server_identity_tables()
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                ca.role,
                ca.status,
                c.id AS company_id,
                c.name AS company_name
            FROM company_access ca
            JOIN users u ON u.id = ca.user_id
            JOIN companies c ON c.id = ca.company_id
            WHERE u.email = ?
            ORDER BY c.name, ca.role
            """,
            (email,),
        ).fetchall()


def user_has_any_role(email: str, allowed_roles):
    rows = get_active_roles_for_user(email)
    allowed = set(allowed_roles)
    for row in rows:
        if row["status"] == "active" and row["role"] in allowed:
            return True
    return False


def list_user_settings_rows():
    init_server_identity_tables()
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                u.id AS user_id,
                u.email,
                u.full_name,
                u.status AS user_status,
                u.created_at,
                c.id AS company_id,
                c.name AS company_name,
                ca.role,
                ca.status AS access_status
            FROM users u
            LEFT JOIN company_access ca ON ca.user_id = u.id
            LEFT JOIN companies c ON c.id = ca.company_id
            ORDER BY u.email, c.name, ca.role
            """
        ).fetchall()

def set_user_status(user_id: int, status: str):
    init_server_identity_tables()

    allowed = {"active", "inactive"}
    if status not in allowed:
        raise ValueError("Statut utilisateur invalide")

    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

        if row is None:
            raise ValueError("Utilisateur introuvable")

        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")

        conn.execute(
            """
            UPDATE users
            SET status = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, now, user_id),
        )
        conn.commit()

def set_company_access_status(user_id: int, company_id: int, status: str):
    init_server_identity_tables()

    allowed = {"active", "inactive"}
    if status not in allowed:
        raise ValueError("Statut accès société invalide")

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id
            FROM company_access
            WHERE user_id = ? AND company_id = ?
            """,
            (user_id, company_id),
        ).fetchone()

        if row is None:
            raise ValueError("Accès société introuvable")

        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")

        conn.execute(
            """
            UPDATE company_access
            SET status = ?, updated_at = ?
            WHERE user_id = ? AND company_id = ?
            """,
            (status, now, user_id, company_id),
        )
        conn.commit()

def set_company_access_role(user_id: int, company_id: int, role: str):
    init_server_identity_tables()

    allowed = {
        "OWNER",
        "SUPER_ADMIN",
        "COMPANY_ADMIN",
        "CONTRACT_MANAGER",
        "TESTER",
    }

    if role not in allowed:
        raise ValueError("Rôle accès société invalide")

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id
            FROM company_access
            WHERE user_id = ? AND company_id = ?
            """,
            (user_id, company_id),
        ).fetchone()

        if row is None:
            raise ValueError("Accès société introuvable")

        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")

        conn.execute(
            """
            UPDATE company_access
            SET role = ?, updated_at = ?
            WHERE user_id = ? AND company_id = ?
            """,
            (role, now, user_id, company_id),
        )
        conn.commit()

def create_user_with_temporary_password(email: str, full_name: str, temporary_password: str, status: str = "inactive"):
    init_server_identity_tables()

    email = (email or "").strip().lower()
    full_name = (full_name or "").strip()
    temporary_password = temporary_password or ""

    if not email:
        raise ValueError("Email obligatoire")

    if not temporary_password:
        raise ValueError("Mot de passe temporaire obligatoire")

    if status not in {"active", "inactive"}:
        raise ValueError("Statut utilisateur invalide")

    from datetime import datetime
    from password_security import hash_password

    now = datetime.now().isoformat(timespec="seconds")
    password_hash = hash_password(temporary_password)

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE email = ?",
            (email,),
        ).fetchone()

        if existing:
            raise ValueError("Un utilisateur existe déjà avec cet email")

        conn.execute(
            """
            INSERT INTO users (
                email,
                full_name,
                password_hash,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (email, full_name, password_hash, status, now, now),
        )
        conn.commit()


def set_user_password_by_id(user_id: int, new_password: str):
    init_server_identity_tables()

    if not new_password:
        raise ValueError("Nouveau mot de passe obligatoire")

    from datetime import datetime
    from password_security import hash_password

    now = datetime.now().isoformat(timespec="seconds")
    password_hash = hash_password(new_password)

    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

        if row is None:
            raise ValueError("Utilisateur introuvable")

        conn.execute(
            """
            UPDATE users
            SET password_hash = ?, updated_at = ?
            WHERE id = ?
            """,
            (password_hash, now, user_id),
        )
        conn.commit()


def user_has_active_company_access(email: str) -> bool:
    init_server_identity_tables()

    user = get_user_by_email(email)
    if not user:
        return False

    user_id = user["id"]

    with get_connection() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()

        for table_row in tables:
            table_name = table_row["name"] if "name" in table_row.keys() else table_row[0]

            columns_info = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            columns = []
            for col in columns_info:
                try:
                    columns.append(col["name"])
                except Exception:
                    columns.append(col[1])

            if "user_id" in columns and "company_id" in columns and "status" in columns:
                count = conn.execute(
                    f"""
                    SELECT COUNT(*) AS count
                    FROM {table_name}
                    WHERE user_id = ?
                      AND status = 'active'
                    """,
                    (user_id,),
                ).fetchone()

                value = count["count"] if "count" in count.keys() else count[0]
                if value > 0:
                    return True

    return False


def get_active_company_context(email: str):
    init_server_identity_tables()

    user = get_user_by_email(email)
    if not user:
        return None

    user_id = user["id"]

    with get_connection() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()

        access_table = None

        for table_row in tables:
            table_name = table_row["name"] if "name" in table_row.keys() else table_row[0]

            columns_info = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            columns = []
            for col in columns_info:
                try:
                    columns.append(col["name"])
                except Exception:
                    columns.append(col[1])

            if (
                "user_id" in columns
                and "company_id" in columns
                and "status" in columns
                and "role" in columns
            ):
                access_table = table_name
                break

        if not access_table:
            return None

        access = conn.execute(
            f"""
            SELECT
                user_id,
                company_id,
                role,
                status
            FROM {access_table}
            WHERE user_id = ?
              AND status = 'active'
            ORDER BY company_id ASC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()

        if not access:
            return None

        company_id = access["company_id"]

        company = None
        for candidate in ["companies", "company", "dealer_companies", "server_companies"]:
            table_exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                (candidate,),
            ).fetchone()

            if not table_exists:
                continue

            company = conn.execute(
                f"SELECT * FROM {candidate} WHERE id = ?",
                (company_id,),
            ).fetchone()

            if company:
                break

        company_name = f"Société #{company_id}"
        if company:
            keys = company.keys()
            for field in ["name", "company_name", "display_name", "label"]:
                if field in keys and company[field]:
                    company_name = company[field]
                    break

        return {
            "user_id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"] if "full_name" in user.keys() else "",
            "user_status": user["status"],
            "company_id": company_id,
            "company_name": company_name,
            "role": access["role"],
            "access_status": access["status"],
            "access_table": access_table,
        }

