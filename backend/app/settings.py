import sys

from database import get_connection, init_db


DEFAULT_SETTINGS = {
    "labour_margin_percent": {
        "value": 10,
        "description": "Marge appliquee sur la main d'oeuvre en pourcentage",
    },
    "admin_fee_percent": {
        "value": 3,
        "description": "Frais administratifs en pourcentage",
    },
    "logistics_fee_percent": {
        "value": 1,
        "description": "Frais logistiques en pourcentage",
    },
    "travel_price_per_km": {
        "value": 0,
        "description": "Tarif deplacement par kilometre",
    },
    "travel_hourly_rate": {
        "value": 0,
        "description": "Taux horaire temps de trajet",
    },
    "equipment_moved_percent": {
        "value": 0,
        "description": "Majoration si materiel deplace en pourcentage",
    },
    "indexation_parts_year_1": {
        "value": 0,
        "description": "Indexation pieces annee 1 en pourcentage",
    },
    "indexation_labour_year_1": {
        "value": 0,
        "description": "Indexation main d'oeuvre annee 1 en pourcentage",
    },
    "indexation_parts_year_2": {
        "value": 0,
        "description": "Indexation pieces annee 2 en pourcentage",
    },
    "indexation_labour_year_2": {
        "value": 0,
        "description": "Indexation main d'oeuvre annee 2 en pourcentage",
    },
    "indexation_parts_year_3": {
        "value": 0,
        "description": "Indexation pieces annee 3 en pourcentage",
    },
    "indexation_labour_year_3": {
        "value": 0,
        "description": "Indexation main d'oeuvre annee 3 en pourcentage",
    },
    "indexation_parts_year_4": {
        "value": 0,
        "description": "Indexation pieces annee 4 en pourcentage",
    },
    "indexation_labour_year_4": {
        "value": 0,
        "description": "Indexation main d'oeuvre annee 4 en pourcentage",
    },
    "indexation_parts_year_5": {
        "value": 0,
        "description": "Indexation pieces annee 5 en pourcentage",
    },
    "indexation_labour_year_5": {
        "value": 0,
        "description": "Indexation main d'oeuvre annee 5 en pourcentage",
    },
    "indexation_parts_year_6": {
        "value": 0,
        "description": "Indexation pieces annee 6 en pourcentage",
    },
    "indexation_labour_year_6": {
        "value": 0,
        "description": "Indexation main d'oeuvre annee 6 en pourcentage",
    },
    "indexation_parts_year_7": {
        "value": 0,
        "description": "Indexation pieces annee 7 en pourcentage",
    },
    "indexation_labour_year_7": {
        "value": 0,
        "description": "Indexation main d'oeuvre annee 7 en pourcentage",
    },
    "indexation_parts_year_8": {
        "value": 0,
        "description": "Indexation pieces annee 8 en pourcentage",
    },
    "indexation_labour_year_8": {
        "value": 0,
        "description": "Indexation main d'oeuvre annee 8 en pourcentage",
    },
    "indexation_parts_year_9": {
        "value": 0,
        "description": "Indexation pieces annee 9 en pourcentage",
    },
    "indexation_labour_year_9": {
        "value": 0,
        "description": "Indexation main d'oeuvre annee 9 en pourcentage",
    },
    "indexation_parts_year_10": {
        "value": 0,
        "description": "Indexation pieces annee 10 en pourcentage",
    },
    "indexation_labour_year_10": {
        "value": 0,
        "description": "Indexation main d'oeuvre annee 10 en pourcentage",
    },
}


def _ensure_company_settings_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS company_dealer_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value REAL NOT NULL,
            description TEXT,
            UNIQUE(company_id, key)
        )
        """
    )


def ensure_default_settings(company_id=None):
    init_db()

    with get_connection() as conn:
        if company_id is None:
            for key, item in DEFAULT_SETTINGS.items():
                conn.execute(
                    """
                    INSERT OR IGNORE INTO dealer_settings (
                        key,
                        value,
                        description
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        key,
                        item["value"],
                        item["description"],
                    ),
                )
        else:
            company_id = int(company_id)
            _ensure_company_settings_table(conn)

            for key, item in DEFAULT_SETTINGS.items():
                conn.execute(
                    """
                    INSERT OR IGNORE INTO company_dealer_settings (
                        company_id,
                        key,
                        value,
                        description
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        company_id,
                        key,
                        item["value"],
                        item["description"],
                    ),
                )

        conn.commit()



def list_settings(company_id=None):
    ensure_default_settings(company_id)

    with get_connection() as conn:
        if company_id is None:
            rows = conn.execute(
                """
                SELECT key, value, description
                FROM dealer_settings
                ORDER BY key
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT key, value, description
                FROM company_dealer_settings
                WHERE company_id = ?
                ORDER BY key
                """,
                (int(company_id),),
            ).fetchall()

    print("Parametres dealer")
    print("-" * 80)

    for row in rows:
        print(f"{row['key']} = {row['value']} | {row['description']}")



def set_setting(key: str, value: float, company_id=None):
    ensure_default_settings(company_id)

    with get_connection() as conn:
        if company_id is None:
            existing = conn.execute(
                """
                SELECT key
                FROM dealer_settings
                WHERE key = ?
                """,
                (key,),
            ).fetchone()

            if existing is None:
                print(f"Parametre inconnu : {key}")
                return

            conn.execute(
                """
                UPDATE dealer_settings
                SET value = ?
                WHERE key = ?
                """,
                (value, key),
            )
        else:
            company_id = int(company_id)

            existing = conn.execute(
                """
                SELECT key
                FROM company_dealer_settings
                WHERE company_id = ?
                  AND key = ?
                """,
                (company_id, key),
            ).fetchone()

            if existing is None:
                print(f"Parametre inconnu pour la societe {company_id} : {key}")
                return

            conn.execute(
                """
                UPDATE company_dealer_settings
                SET value = ?
                WHERE company_id = ?
                  AND key = ?
                """,
                (value, company_id, key),
            )

        conn.commit()

    print(f"Parametre modifie : {key} = {value}")



def get_settings_dict(company_id=None):
    ensure_default_settings(company_id)

    with get_connection() as conn:
        if company_id is None:
            rows = conn.execute(
                """
                SELECT key, value
                FROM dealer_settings
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT key, value
                FROM company_dealer_settings
                WHERE company_id = ?
                """,
                (int(company_id),),
            ).fetchall()

    return {row["key"]: row["value"] for row in rows}



if __name__ == "__main__":
    if len(sys.argv) == 1:
        list_settings()
    elif len(sys.argv) == 4 and sys.argv[1] == "set":
        set_setting(sys.argv[2], float(sys.argv[3]))
    else:
        print("Usage :")
        print("  python backend/app/settings.py")
        print("  python backend/app/settings.py set parts_margin_percent 12")
