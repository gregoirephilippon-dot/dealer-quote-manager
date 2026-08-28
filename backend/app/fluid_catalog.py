from database import get_connection


def guess_packaging_liters_from_weight(weight):
    """
    Déduit un conditionnement probable à partir du poids price list.
    La valeur reste modifiable manuellement dans le devis.
    """
    try:
        weight = float(weight or 0)
    except (TypeError, ValueError):
        return 0

    if weight <= 0:
        return 0

    # Bidon ~5 L
    if 3.5 <= weight <= 6.5:
        return 5

    # Bidon ~20 L
    if 15 <= weight <= 22:
        return 20

    # Fût ~208 L
    if 160 <= weight <= 190:
        return 208

    return 0


def get_price_catalog_item(part_no):
    if not part_no:
        return None

    with get_connection() as conn:
        row = conn.execute("""
            SELECT part_no, description, price_excl_vat, discount_code, unit,
                   product_group, function_group, weight
            FROM price_catalog
            WHERE part_no = ?
        """, (str(part_no).strip(),)).fetchone()

    if not row:
        return None

    item = dict(row)
    item["suggested_packaging_liters"] = guess_packaging_liters_from_weight(item.get("weight"))
    return item


def search_engine_oil_catalog_items():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT part_no, description, price_excl_vat, discount_code, unit,
                   product_group, function_group, weight
            FROM price_catalog
            WHERE lower(description) = 'engine oil'
            ORDER BY weight, price_excl_vat, part_no
        """).fetchall()

    results = []
    for row in rows:
        item = dict(row)
        item["suggested_packaging_liters"] = guess_packaging_liters_from_weight(item.get("weight"))
        results.append(item)

    return results



COOLANT_PACKAGING_LITERS = {
    "22567233": 5,
    "22567259": 20,
    "22567215": 20,
    "24712786": 5,
    "22575148": 5,
    "24712788": 20,
    "24712790": 210,
    "24712783": 210,
    "22567261": 210,
    "22567217": 210,
}


COOLANT_TYPE_LABELS = {
    "22567233": "Vert - ready mixed",
    "22567259": "Vert - ready mixed",
    "22567215": "Vert - concentre",
    "22567261": "Vert - ready mixed",
    "22567217": "Vert - concentre",
    "24712786": "VCS-2 orange - ready mixed",
    "24712788": "VCS-2 orange - ready mixed",
    "24712790": "VCS-2 orange - ready mixed",
}


def get_coolant_type_label(part_no):
    return COOLANT_TYPE_LABELS.get(str(part_no or "").strip(), "")


def get_coolant_packaging_liters(part_no, weight=0):
    part_no = str(part_no or "").strip()

    if part_no in COOLANT_PACKAGING_LITERS:
        return COOLANT_PACKAGING_LITERS[part_no]

    try:
        weight = float(weight or 0)
    except (TypeError, ValueError):
        return 0

    if 4.5 <= weight <= 6.5:
        return 5

    if 20 <= weight <= 25:
        return 20

    if 220 <= weight <= 260:
        return 210

    if 1050 <= weight <= 1200:
        return 1000

    return 0


def search_engine_coolant_catalog_items():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT part_no, description, price_excl_vat, discount_code, unit,
                   product_group, function_group, weight
            FROM price_catalog
            WHERE product_group = '1900'
              AND function_group = '1841'
              AND upper(description) = 'LIQUIDE REFROIDISSEMENT'
            ORDER BY weight, price_excl_vat, part_no
        """).fetchall()

    results = []
    for row in rows:
        item = dict(row)
        item["suggested_packaging_liters"] = get_coolant_packaging_liters(
            item.get("part_no"), item.get("weight")
        )
        item["coolant_type_label"] = get_coolant_type_label(
            item.get("part_no")
        )
        results.append(item)

    return results
