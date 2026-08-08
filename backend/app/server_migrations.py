import sqlite3
from pathlib import Path

import app_config as config
import server_user_model as identity


def get_db_path() -> Path:
    if not config.DATABASE_URL.startswith("sqlite:///"):
        raise RuntimeError("Migration locale SQLite uniquement pour le moment")

    db_relative = config.DATABASE_URL.replace("sqlite:///", "", 1)
    return config.BASE_DIR / db_relative


def column_exists(conn, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row[1] == column_name for row in rows)


def table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def migrate_quotes_company_id():
    identity.init_server_identity_tables()

    company_id = identity.create_company("Gwen Service", "gwen-service")

    db_path = get_db_path()

    with sqlite3.connect(db_path) as conn:
        if not table_exists(conn, "quotes"):
            print("Table quotes introuvable : rien à migrer pour le moment")
            return

        if not column_exists(conn, "quotes", "company_id"):
            conn.execute("ALTER TABLE quotes ADD COLUMN company_id INTEGER")
            print("Colonne quotes.company_id ajoutée")
        else:
            print("Colonne quotes.company_id déjà présente")

        conn.execute(
            "UPDATE quotes SET company_id = ? WHERE company_id IS NULL",
            (company_id,),
        )

        total_quotes = conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0]
        linked_quotes = conn.execute(
            "SELECT COUNT(*) FROM quotes WHERE company_id IS NOT NULL"
        ).fetchone()[0]

        conn.commit()

    print("Société par défaut :", company_id)
    print("Devis total :", total_quotes)
    print("Devis rattachés :", linked_quotes)


if __name__ == "__main__":
    migrate_quotes_company_id()
