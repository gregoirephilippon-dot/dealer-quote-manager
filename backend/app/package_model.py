from database import get_connection
from service_catalog import SERVICE_CATALOG


PACKAGE_PRESETS = {
    "basic": {
        "label": "Basic",
        "description": "Commissioning + contrôle visuel initial.",
        "services": ["1,1", "1,2"],
    },
    "base_care": {
        "label": "Base Care",
        "description": "Basic + campagne + maintenance parts & labour.",
        "services": ["1,1", "1,2", "1,3", "2,2"],
    },
    "comfort_care": {
        "label": "Comfort Care",
        "description": "Base Care + diagnostics + analyses fluides.",
        "services": ["1,1", "1,2", "1,3", "2,2", "3,1", "3,2", "3,3_1", "3,3_2", "3,3_3"],
    },
    "advanced_care": {
        "label": "Advanced Care",
        "description": "Comfort Care + monitoring + préventif + extension.",
        "services": [
            "1,1", "1,2", "1,3", "1,4",
            "2,2", "2,3",
            "3,1", "3,2", "3,3_1", "3,3_2", "3,3_3",
            "4,1", "4,2",
            "6,1",
        ],
    },
}


def ensure_package_schema():
    with get_connection() as conn:
        try:
            conn.execute("ALTER TABLE quotes ADD COLUMN package_key TEXT")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE quotes ADD COLUMN package_name TEXT")
        except Exception:
            pass
        conn.commit()


def ensure_quote_services(quote_id: int):
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
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, 0, '')
                """,
                (
                    quote_id,
                    item.get("id"),
                    item.get("group"),
                    item.get("name"),
                    item.get("source"),
                    item.get("default_time", 0),
                    item.get("default_qty", 0),
                    item.get("default_unit", 0),
                    item.get("default_fixed", 0),
                    item.get("travel", "Exclude"),
                ),
            )
        conn.commit()


def get_quote_package(quote_id: int):
    ensure_package_schema()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT package_key, package_name FROM quotes WHERE id = ?",
            (quote_id,),
        ).fetchone()

    if not row:
        return None, None

    key = row["package_key"] if "package_key" in row.keys() else None
    name = row["package_name"] if "package_name" in row.keys() else None
    return key, name


def detect_package_from_services(quote_id: int):
    ensure_quote_services(quote_id)

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT service_id FROM quote_services WHERE quote_id = ? AND included = 1",
            (quote_id,),
        ).fetchall()

    included = {row["service_id"] for row in rows}

    for key, preset in PACKAGE_PRESETS.items():
        if included == set(preset["services"]):
            return key, preset["label"]

    return None, "Personnalisé"


def apply_package_to_quote(quote_id: int, package_key: str):
    ensure_package_schema()
    ensure_quote_services(quote_id)

    if package_key not in PACKAGE_PRESETS:
        raise ValueError(f"Package inconnu : {package_key}")

    preset = PACKAGE_PRESETS[package_key]
    selected_services = set(preset["services"])

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT service_id FROM quote_services WHERE quote_id = ?",
            (quote_id,),
        ).fetchall()

        for row in rows:
            included = 1 if row["service_id"] in selected_services else 0
            conn.execute(
                """
                UPDATE quote_services
                SET included = ?
                WHERE quote_id = ? AND service_id = ?
                """,
                (included, quote_id, row["service_id"]),
            )

        conn.execute(
            """
            UPDATE quotes
            SET package_key = ?, package_name = ?
            WHERE id = ?
            """,
            (package_key, preset["label"], quote_id),
        )
        conn.commit()

    recalculate_quote(quote_id)


def recalculate_quote(quote_id: int):
    try:
        from apply_pricing import apply_pricing
        apply_pricing(quote_id)
    except Exception as exc:
        print("Recalcul impossible apres changement package :", exc)


def get_package_status(quote_id: int):
    ensure_package_schema()
    ensure_quote_services(quote_id)

    stored_key, stored_name = get_quote_package(quote_id)
    detected_key, detected_name = detect_package_from_services(quote_id)

    current_key = stored_key or detected_key
    current_name = stored_name or detected_name

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT service_id FROM quote_services WHERE quote_id = ? AND included = 1",
            (quote_id,),
        ).fetchall()

    included = {row["service_id"] for row in rows}

    packages = []
    for key, preset in PACKAGE_PRESETS.items():
        preset_services = set(preset["services"])
        packages.append(
            {
                "key": key,
                "label": preset["label"],
                "description": preset["description"],
                "services": preset["services"],
                "matching": len(included.intersection(preset_services)),
                "total": len(preset_services),
                "active": key == current_key,
            }
        )

    return current_key, current_name, packages
