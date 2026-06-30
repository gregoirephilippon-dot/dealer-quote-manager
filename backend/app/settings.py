import sys

from database import get_connection, init_db


DEFAULT_SETTINGS = {
    "parts_margin_percent": {
        "value": 15,
        "description": "Marge appliquee sur les pieces en pourcentage",
    },
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
    "travel_fee_fixed": {
        "value": 0,
        "description": "Frais de deplacement fixes",
    },
    "indexation_percent": {
        "value": 0,
        "description": "Indexation annuelle en pourcentage",
    },
}


def ensure_default_settings():
    init_db()

    with get_connection() as conn:
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

        conn.commit()


def list_settings():
    ensure_default_settings()

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT key, value, description
            FROM dealer_settings
            ORDER BY key
            """
        ).fetchall()

    print("Parametres dealer")
    print("-" * 80)

    for row in rows:
        print(f"{row['key']} = {row['value']} | {row['description']}")


def set_setting(key: str, value: float):
    ensure_default_settings()

    with get_connection() as conn:
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
            print("Utilise d'abord : python backend/app/settings.py")
            return

        conn.execute(
            """
            UPDATE dealer_settings
            SET value = ?
            WHERE key = ?
            """,
            (value, key),
        )

        conn.commit()

    print(f"Parametre modifie : {key} = {value}")


def get_settings_dict():
    ensure_default_settings()

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT key, value
            FROM dealer_settings
            """
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
