import sys
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DB = BASE_DIR / "data" / "dealer_quote_manager.sqlite"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from database import init_db
import server_user_model as users


def ensure_quote_company_column(conn):
    tables = [
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    ]

    if "quotes" not in tables:
        print("Table quotes absente : rien à migrer pour company_id.")
        return

    columns = [
        row["name"]
        for row in conn.execute("PRAGMA table_info(quotes)")
    ]

    if "company_id" not in columns:
        conn.execute("ALTER TABLE quotes ADD COLUMN company_id INTEGER")
        print("Colonne quotes.company_id ajoutée.")
    else:
        print("Colonne quotes.company_id déjà présente.")


def ensure_test_admin():
    email = "admin@test.local"
    password = "admin1234"
    company_name = "Société Test Serveur"
    company_slug = "test-serveur"

    users.init_server_identity_tables()

    company_id = users.create_company(company_name, company_slug)
    user_id = users.create_user(email, "Admin Test")

    users.set_user_password_by_id(user_id, password)
    users.grant_company_access(company_id, user_id, "SUPER_ADMIN")
    users.set_active_company_id_for_user(email, company_id)

    return email, password, company_id, user_id


def main():
    print("Initialisation base serveur test")
    print("DB :", DB)

    init_db()
    email, password, company_id, user_id = ensure_test_admin()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    ensure_quote_company_column(conn)

    if "quotes" in [
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    ]:
        conn.execute(
            "UPDATE quotes SET company_id = ? WHERE company_id IS NULL",
            (company_id,),
        )

    conn.commit()

    print("")
    print("UTILISATEURS")
    for row in conn.execute("SELECT id, email, full_name, status FROM users"):
        print(dict(row))

    print("")
    print("SOCIETES")
    for row in conn.execute("SELECT id, name, slug, status FROM companies"):
        print(dict(row))

    print("")
    print("ACCES")
    for row in conn.execute("SELECT id, company_id, user_id, role, status FROM company_access"):
        print(dict(row))

    conn.close()

    print("")
    print("Compte test prêt")
    print("Email    :", email)
    print("Mot passe:", password)
    print("")
    print("Initialisation terminée.")


if __name__ == "__main__":
    main()
