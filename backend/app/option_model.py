from database import get_connection
from price_catalog_model import lookup_part


def _to_float(value, default=0.0):
    if value is None:
        return default

    text = str(value).strip().replace(" ", "").replace(",", ".")
    if not text:
        return default

    try:
        return float(text)
    except ValueError:
        return default


def _norm(value):
    if value is None:
        return ""
    return str(value).strip()


def ensure_option_schema():
    with get_connection() as conn:
        for sql in [
            "ALTER TABLE quote_services ADD COLUMN option_reference TEXT",
            "ALTER TABLE quote_services ADD COLUMN option_discount_code TEXT",
            "ALTER TABLE quote_services ADD COLUMN option_catalog_source TEXT",
        ]:
            try:
                conn.execute(sql)
            except Exception:
                pass

        conn.commit()


def _get_quote_labour_rate(conn, quote_id):
    row = conn.execute(
        "SELECT labour_rate FROM quotes WHERE id = ?",
        (quote_id,),
    ).fetchone()

    if not row:
        return 0.0

    return _to_float(row["labour_rate"], 0.0)


def _get_travel_fee(conn):
    row = conn.execute(
        "SELECT value FROM dealer_settings WHERE key = 'travel_fee_fixed'",
    ).fetchone()

    if not row:
        return 0.0

    return _to_float(row["value"], 0.0)


def calculate_option_price(labour_rate, travel_fee, work_time_hours, quantity, unit_price, fixed_price, extra_travel):
    qty = _to_float(quantity, 1.0)
    if qty == 0:
        qty = 1.0

    total = 0.0
    total += _to_float(work_time_hours) * _to_float(labour_rate)
    total += qty * _to_float(unit_price)
    total += _to_float(fixed_price)

    if str(extra_travel).strip().lower() in ("yes", "oui", "include", "included", "1", "true"):
        total += _to_float(travel_fee)

    return round(total, 2)


def get_quote_options(quote_id):
    ensure_option_schema()

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM quote_services
            WHERE quote_id = ?
              AND service_group = 'Options'
            ORDER BY id
            """,
            (quote_id,),
        ).fetchall()

    return rows


def add_option_line(quote_id):
    ensure_option_schema()

    with get_connection() as conn:
        count = conn.execute(
            """
            SELECT COUNT(*)
            FROM quote_services
            WHERE quote_id = ?
              AND service_group = 'Options'
            """,
            (quote_id,),
        ).fetchone()[0]

        technical_id = f"OPT-{count + 1:03d}"

        conn.execute(
            """
            INSERT INTO quote_services (
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
                notes,
                option_reference,
                option_discount_code,
                option_catalog_source
            )
            VALUES (?, ?, 'Options', '', 'DSP price', 1, 0, 1, 0, 0, 'Exclude', 0, '', '', '', '')
            """,
            (quote_id, technical_id),
        )

        conn.commit()


def delete_option_line(quote_id, option_id):
    ensure_option_schema()

    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM quote_services
            WHERE quote_id = ?
              AND id = ?
              AND service_group = 'Options'
            """,
            (quote_id, option_id),
        )
        conn.commit()

    recalculate_quote_outputs(quote_id)


def update_options_from_form(quote_id, form_data):
    ensure_option_schema()

    with get_connection() as conn:
        labour_rate = _get_quote_labour_rate(conn, quote_id)
        travel_fee = _get_travel_fee(conn)

        rows = conn.execute(
            """
            SELECT id, service_id
            FROM quote_services
            WHERE quote_id = ?
              AND service_group = 'Options'
            ORDER BY id
            """,
            (quote_id,),
        ).fetchall()

        for row in rows:
            option_id = row["id"]
            technical_service_id = row["service_id"]

            included = 1 if str(form_data.get(f"included_{option_id}", "")).lower() in ("on", "1", "true", "yes") else 0

            reference = _norm(form_data.get(f"option_reference_{option_id}", ""))
            quantity = _to_float(form_data.get(f"quantity_{option_id}", 1), 1.0)
            if quantity == 0:
                quantity = 1.0

            work_time_hours = _to_float(form_data.get(f"work_time_hours_{option_id}", 0), 0.0)
            extra_travel = _norm(form_data.get(f"extra_travel_{option_id}", "Exclude")) or "Exclude"
            notes = _norm(form_data.get(f"notes_{option_id}", ""))

            catalog_row = lookup_part(reference)

            if catalog_row:
                designation = catalog_row["description"] or ""
                unit_price = _to_float(catalog_row["price_excl_vat"], 0.0)
                discount_code = catalog_row["discount_code"] or ""
                catalog_source = catalog_row["source_file"] or "DSP price"
                source_excel = ""
            else:
                designation = _norm(form_data.get(f"service_name_{option_id}", ""))
                unit_price = _to_float(form_data.get(f"unit_price_{option_id}", 0), 0.0)
                discount_code = _norm(form_data.get(f"option_discount_code_{option_id}", ""))
                catalog_source = ""
                source_excel = "Manuel"

            fixed_price = _to_float(form_data.get(f"fixed_price_{option_id}", 0), 0.0)

            calculated_price = calculate_option_price(
                labour_rate=labour_rate,
                travel_fee=travel_fee,
                work_time_hours=work_time_hours,
                quantity=quantity,
                unit_price=unit_price,
                fixed_price=fixed_price,
                extra_travel=extra_travel,
            )

            # Ce qui doit apparaître dans la colonne Service de la liste.
            # OPT-xxx reste seulement provisoire avant actualisation.
            display_service_id = reference or technical_service_id

            # On garde service_id technique OPT-xxx pour éviter les conflits UNIQUE.
            # La vraie référence pièce/service est option_reference.
            conn.execute(
                """
                UPDATE quote_services
                SET
                    service_id = ?,
                    included = ?,
                    service_name = ?,
                    source_excel = ?,
                    option_reference = ?,
                    option_discount_code = ?,
                    option_catalog_source = ?,
                    work_time_hours = ?,
                    quantity = ?,
                    unit_price = ?,
                    fixed_price = ?,
                    extra_travel = ?,
                    calculated_price = ?,
                    notes = ?
                WHERE id = ?
                  AND quote_id = ?
                  AND service_group = 'Options'
                """,
                (
                    display_service_id,
                    included,
                    designation,
                    source_excel,
                    reference,
                    discount_code,
                    catalog_source,
                    work_time_hours,
                    quantity,
                    unit_price,
                    fixed_price,
                    extra_travel,
                    calculated_price,
                    notes,
                    option_id,
                    quote_id,
                ),
            )

        conn.commit()

    recalculate_quote_outputs(quote_id)


def recalculate_quote_outputs(quote_id):
    from apply_pricing import apply_pricing
    from export_quote_html import export_quote_html
    from export_quote_pdf import export_quote_pdf

    apply_pricing(quote_id)
    export_quote_html(quote_id)
    export_quote_pdf(quote_id)


def format_money(value):
    try:
        return f"{float(value):,.2f}".replace(",", " ").replace(".", ",")
    except Exception:
        return "0,00"
