from database import get_connection


DEFAULT_DEALER_DISCOUNT_CODES = [
    {"dc": 11, "group_name": "Service Parts", "example_products": "Filters Oil/Air/Fuel, Zinc, Belts, Spark Plug", "dealer_discount": 0.49, "customer_type_discount": 0.0},
    {"dc": 12, "group_name": "Repair Parts", "example_products": "Standard Parts, Bearings, Gasket, Overhaul Kits/Gaskets, Fuel Pumps, Injectors, Exhaust Parts, Water Pumps", "dealer_discount": 0.41, "customer_type_discount": 0.0},
    {"dc": 13, "group_name": "Acc", "example_products": "Non EVC Accessories and Oil, Coolant, Paint etc.", "dealer_discount": 0.43, "customer_type_discount": 0.0},
    {"dc": 14, "group_name": "Acc VP", "example_products": "EVC accessories", "dealer_discount": 0.36, "customer_type_discount": 0.0},
    {"dc": 15, "group_name": "Parts", "example_products": "Parts other, medium value", "dealer_discount": 0.37, "customer_type_discount": 0.0},
    {"dc": 16, "group_name": "Propp SP", "example_products": "Single prop", "dealer_discount": 0.0, "customer_type_discount": 0.0},
    {"dc": 17, "group_name": "Propp DP", "example_products": "Duo prop", "dealer_discount": 0.0, "customer_type_discount": 0.0},
    {"dc": 18, "group_name": "Parts / SW", "example_products": "SW, Parts other, high value", "dealer_discount": 0.29, "customer_type_discount": 0.0},
    {"dc": 19, "group_name": "Exchange", "example_products": "All Exchange excluding below", "dealer_discount": 0.28, "customer_type_discount": 0.0},
    {"dc": 20, "group_name": "Tools / Exchange", "example_products": "Tools, Long block, Engine, IPS", "dealer_discount": 0.19, "customer_type_discount": 0.0},
    {"dc": 21, "group_name": "Misc.", "example_products": "Instructions, packaging material", "dealer_discount": 0.10, "customer_type_discount": 0.0},
    {"dc": 22, "group_name": "Cores", "example_products": "All cores", "dealer_discount": 0.0, "customer_type_discount": 0.0},
]


def _to_decimal_percent(value):
    """
    Accepte :
    - 49  -> 0.49
    - 49% -> 0.49
    - 0.49 -> 0.49
    - vide -> 0
    """
    if value is None:
        return 0.0

    text = str(value).strip().replace("%", "").replace(",", ".")
    if not text:
        return 0.0

    number = float(text)
    if number > 1:
        return number / 100
    return number


def _percent_display(value):
    try:
        return round(float(value) * 100, 2)
    except Exception:
        return 0.0


def ensure_dealer_discount_schema():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dealer_discount_codes (
                dc INTEGER PRIMARY KEY,
                group_name TEXT,
                example_products TEXT,
                dealer_discount REAL DEFAULT 0,
                customer_type_discount REAL DEFAULT 0,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        for row in DEFAULT_DEALER_DISCOUNT_CODES:
            conn.execute(
                """
                INSERT OR IGNORE INTO dealer_discount_codes (
                    dc,
                    group_name,
                    example_products,
                    dealer_discount,
                    customer_type_discount
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    row["dc"],
                    row["group_name"],
                    row["example_products"],
                    row["dealer_discount"],
                    row["customer_type_discount"],
                ),
            )

        conn.commit()


def get_dealer_discount_codes():
    ensure_dealer_discount_schema()

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                dc,
                group_name,
                example_products,
                dealer_discount,
                customer_type_discount,
                updated_at
            FROM dealer_discount_codes
            ORDER BY dc
            """
        ).fetchall()

    result = []
    for row in rows:
        result.append(
            {
                "dc": row["dc"],
                "group_name": row["group_name"] or "",
                "example_products": row["example_products"] or "",
                "dealer_discount": row["dealer_discount"] or 0.0,
                "dealer_discount_percent": _percent_display(row["dealer_discount"] or 0.0),
                "customer_type_discount": row["customer_type_discount"] or 0.0,
                "customer_type_discount_percent": _percent_display(row["customer_type_discount"] or 0.0),
                "updated_at": row["updated_at"] or "",
            }
        )

    return result


def update_dealer_discount_codes(form_data):
    """
    form_data : dict compatible request.form()
    champs attendus :
    group_name_<dc>
    example_products_<dc>
    dealer_discount_<dc>
    customer_type_discount_<dc>
    """
    ensure_dealer_discount_schema()

    codes = get_dealer_discount_codes()

    with get_connection() as conn:
        for code in codes:
            dc = code["dc"]
            group_name = str(form_data.get(f"group_name_{dc}", "")).strip()
            example_products = str(form_data.get(f"example_products_{dc}", "")).strip()
            dealer_discount = _to_decimal_percent(form_data.get(f"dealer_discount_{dc}", 0))
            customer_type_discount = _to_decimal_percent(form_data.get(f"customer_type_discount_{dc}", 0))

            conn.execute(
                """
                UPDATE dealer_discount_codes
                SET
                    group_name = ?,
                    example_products = ?,
                    dealer_discount = ?,
                    customer_type_discount = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE dc = ?
                """,
                (
                    group_name,
                    example_products,
                    dealer_discount,
                    customer_type_discount,
                    dc,
                ),
            )

        conn.commit()


def reset_dealer_discount_codes():
    ensure_dealer_discount_schema()

    with get_connection() as conn:
        for row in DEFAULT_DEALER_DISCOUNT_CODES:
            conn.execute(
                """
                UPDATE dealer_discount_codes
                SET
                    group_name = ?,
                    example_products = ?,
                    dealer_discount = ?,
                    customer_type_discount = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE dc = ?
                """,
                (
                    row["group_name"],
                    row["example_products"],
                    row["dealer_discount"],
                    row["customer_type_discount"],
                    row["dc"],
                ),
            )
        conn.commit()
