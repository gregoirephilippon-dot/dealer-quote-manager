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

    conn = get_connection()
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
    conn = get_connection()

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
