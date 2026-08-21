import sys
from database import get_connection, init_db
from settings import get_settings_dict
from dealer_discount_settings import ensure_dealer_discount_schema


def apply_margin(amount, percent):
    if amount is None:
        amount = 0
    return amount * (1 + percent / 100)



def get_contract_year_count(total_hours, hours_per_year):
    try:
        total_hours = float(total_hours or 0)
        hours_per_year = float(hours_per_year or 0)
    except Exception:
        return 1

    if total_hours <= 0 or hours_per_year <= 0:
        return 1

    years = round(total_hours / hours_per_year)

    if years < 1:
        years = 1

    if years > 10:
        years = 10

    return int(years)


def get_setting_float(settings, key, default=0):
    try:
        return float(settings.get(key, default) or 0)
    except Exception:
        return default


def is_overview_imported_service(service):
    source = str(service["source_excel"] or "").lower()
    return (
        "overview column c total" in source
        or "overview" in source
        or "summary services" in source
    )


def calculate_service_price(service, labour_rate, travel_fee):
    work_time = service["work_time_hours"] or 0
    quantity = service["quantity"] or 0
    unit_price = service["unit_price"] or 0
    fixed_price = service["fixed_price"] or 0
    extra_travel = service["extra_travel"] or "Exclude"

    labour_part = work_time * labour_rate
    quantity_part = quantity * unit_price
    travel_part = travel_fee if str(extra_travel).lower() == "yes" else 0

    return fixed_price + labour_part + quantity_part + travel_part




def ensure_quote_lines_discount_columns(conn):
    columns = [
        ("discount_code", "TEXT"),
        ("dealer_net_total", "REAL DEFAULT 0"),
        ("customer_price_total", "REAL DEFAULT 0"),
    ]

    for column_name, column_type in columns:
        try:
            conn.execute(f"ALTER TABLE quote_lines ADD COLUMN {column_name} {column_type}")
            conn.commit()
        except Exception:
            pass


def to_float(value, default=0.0):
    try:
        return float(value or 0)
    except Exception:
        return default


def normalize_discount_code(value):
    if value is None:
        return None

    text = str(value).strip().replace(",", ".")
    if not text:
        return None

    try:
        return int(float(text))
    except Exception:
        return None


def enrich_quote_lines_discount_codes_from_catalog(conn, quote_id: int):
    """
    Remplit quote_lines.discount_code depuis price_catalog.discount_code
    avec correspondance quote_lines.part_number = price_catalog.part_no.
    """
    ensure_quote_lines_discount_columns(conn)

    try:
        conn.execute(
            """
            UPDATE quote_lines
            SET discount_code = (
                SELECT pc.discount_code
                FROM price_catalog pc
                WHERE TRIM(pc.part_no) = TRIM(quote_lines.part_number)
                  AND pc.discount_code IS NOT NULL
                  AND TRIM(pc.discount_code) <> ''
                LIMIT 1
            )
            WHERE quote_id = ?
              AND (discount_code IS NULL OR TRIM(discount_code) = '')
              AND part_number IS NOT NULL
              AND TRIM(part_number) <> ''
              AND EXISTS (
                SELECT 1
                FROM price_catalog pc
                WHERE TRIM(pc.part_no) = TRIM(quote_lines.part_number)
                  AND pc.discount_code IS NOT NULL
                  AND TRIM(pc.discount_code) <> ''
              )
            """,
            (quote_id,),
        )
        conn.commit()
    except Exception as exc:
        print(f"Enrichissement DC depuis catalogue impossible : {exc}")


def calculate_parts_totals_with_dc(conn, quote_id: int, fallback_total_parts: float):
    """
    Logique DC :
    - prix catalogue ligne = total_price ou quantity x unit_price
    - prix achat dealer = prix catalogue x (1 - dealer_discount)
    - prix vente client = prix catalogue x (1 - customer_type_discount)

    Si aucune ligne exploitable avec DC :
    - achat dealer = fallback_total_parts
    - vente client = fallback_total_parts
    """
    ensure_dealer_discount_schema()
    ensure_quote_lines_discount_columns(conn)
    enrich_quote_lines_discount_codes_from_catalog(conn, quote_id)

    discounts = conn.execute(
        """
        SELECT dc, dealer_discount, customer_type_discount
        FROM dealer_discount_codes
        """
    ).fetchall()

    discount_map = {}
    for row in discounts:
        dc = normalize_discount_code(row["dc"])
        if dc is None:
            continue

        discount_map[dc] = {
            "dealer_discount": to_float(row["dealer_discount"]),
            "customer_type_discount": to_float(row["customer_type_discount"]),
        }

    lines = conn.execute(
        """
        SELECT id, quantity, unit_price, total_price, discount_code
        FROM quote_lines
        WHERE quote_id = ?
        """,
        (quote_id,),
    ).fetchall()

    dealer_total = 0
    customer_total = 0
    used_lines = 0

    for line in lines:
        quantity = to_float(line["quantity"])
        unit_price = to_float(line["unit_price"])
        total_price = to_float(line["total_price"])

        catalog_total = total_price
        if catalog_total <= 0 and quantity > 0 and unit_price > 0:
            catalog_total = quantity * unit_price

        if catalog_total <= 0:
            continue

        dc = normalize_discount_code(line["discount_code"])

        if dc is not None and dc in discount_map:
            dealer_discount = discount_map[dc]["dealer_discount"]
            customer_discount = discount_map[dc]["customer_type_discount"]

            dealer_net = catalog_total * (1 - dealer_discount)
            customer_price = catalog_total * (1 - customer_discount)
            used_lines += 1
        else:
            # Sécurité : une ligne sans DC ne doit jamais disparaître du calcul.
            # On la conserve au montant catalogue, sans remise.
            dealer_net = catalog_total
            customer_price = catalog_total

        dealer_total += dealer_net
        customer_total += customer_price

        conn.execute(
            """
            UPDATE quote_lines
            SET dealer_net_total = ?,
                customer_price_total = ?
            WHERE id = ?
            """,
            (dealer_net, customer_price, line["id"]),
        )

    conn.commit()

    if used_lines == 0:
        return fallback_total_parts, fallback_total_parts, 0

    return dealer_total, customer_total, used_lines



def ensure_quote_fluid_columns(conn):
    columns = [
        ("oil_price_per_liter", "REAL DEFAULT 0"),
        ("oil_service_count", "REAL DEFAULT 0"),
        ("oil_quantity_per_service", "REAL DEFAULT 0"),
        ("coolant_price_per_liter", "REAL DEFAULT 0"),
        ("coolant_service_count", "REAL DEFAULT 0"),
        ("coolant_quantity_per_service", "REAL DEFAULT 0"),
        ("fluid_total", "REAL DEFAULT 0"),
        ("replace_overview_fluids", "INTEGER DEFAULT 0"),
    ]

    for column_name, column_type in columns:
        try:
            conn.execute(f"ALTER TABLE quotes ADD COLUMN {column_name} {column_type}")
            conn.commit()
        except Exception:
            pass


def quote_value(row, key, default=0):
    try:
        if key in row.keys():
            return row[key]
    except Exception:
        pass
    return default


def calculate_fluid_total_from_quote(quote):
    return (
        to_float(quote_value(quote, "oil_price_per_liter", 0))
        * to_float(quote_value(quote, "oil_service_count", 0))
        * to_float(quote_value(quote, "oil_quantity_per_service", 0))
        + to_float(quote_value(quote, "coolant_price_per_liter", 0))
        * to_float(quote_value(quote, "coolant_service_count", 0))
        * to_float(quote_value(quote, "coolant_quantity_per_service", 0))
    )


def apply_pricing(quote_id: int):
    init_db()

    with get_connection() as conn:
        ensure_quote_fluid_columns(conn)
        quote = conn.execute(
            """
            SELECT
                id,
                currency,
                total_parts,
                total_labour,
                total_misc,
                total_cost,
                total_hours,
                hours_per_year,
                labour_rate,
                oil_price_per_liter,
                oil_service_count,
                oil_quantity_per_service,
                coolant_price_per_liter,
                coolant_service_count,
                coolant_quantity_per_service,
                fluid_total,
                replace_overview_fluids
            FROM quotes
            WHERE id = ?
            """,
            (quote_id,),
        ).fetchone()

        if quote is None:
            print(f"Devis introuvable : ID {quote_id}")
            return

        settings = get_settings_dict()

        currency = quote["currency"] or "EUR"

        total_parts = quote["total_parts"] or 0
        total_labour = quote["total_labour"] or 0
        total_misc = quote["total_misc"] or 0
        total_hours = quote["total_hours"] or 0
        hours_per_year = quote["hours_per_year"] or 0
        labour_rate_input = quote["labour_rate"] or 0
        fluid_total = calculate_fluid_total_from_quote(quote)
        replace_overview_fluids = bool(quote_value(quote, "replace_overview_fluids", 0))

        labour_margin = settings.get("labour_margin_percent", 0)
        admin_fee = settings.get("admin_fee_percent", 0)
        logistics_fee = settings.get("logistics_fee_percent", 0)
        travel_fee_fixed = settings.get("travel_fee_fixed", 0)
        contract_years = get_contract_year_count(total_hours, hours_per_year)

        dealer_parts_total, selling_parts, dc_lines_used = calculate_parts_totals_with_dc(
            conn,
            quote_id,
            total_parts,
        )

        # Si des lignes pièces avec DC existent, total_parts de référence devient le coût achat dealer.
        # Sinon, on conserve le total pièces importé.
        total_parts = dealer_parts_total

        selling_labour = apply_margin(total_labour, labour_margin)
        selling_misc = total_misc

        included_services = conn.execute(
            """
            SELECT *
            FROM quote_services
            WHERE quote_id = ? AND included = 1
            ORDER BY service_id
            """,
            (quote_id,),
        ).fetchall()

        additional_services_total = 0

        included_service_ids = {
            str(row["service_id"] or "")
            for row in conn.execute(
                """
                SELECT service_id
                FROM quote_services
                WHERE quote_id = ?
                  AND included = 1
                """,
                (quote_id,),
            ).fetchall()
        }

        imported_overview_2_2_present = any(
            str(row["service_id"] or "") == "2,2"
            and is_overview_imported_service(row)
            for row in included_services
        )

        for service in included_services:
            fluid_service_id = None

            if fluid_total > 0:
                if "2,2" in included_service_ids:
                    fluid_service_id = "2,2"
                elif "2,1" in included_service_ids:
                    fluid_service_id = "2,1"

            if is_overview_imported_service(service):
                # Montant déjà calculé dans l'Overview importé.
                # Ne pas recalculer avec work_time_hours x labour_rate.
                service_price = service["fixed_price"] or service["calculated_price"] or 0
            else:
                service_price = calculate_service_price(service, labour_rate_input, travel_fee_fixed)

            if fluid_service_id and str(service["service_id"] or "") == fluid_service_id:
                if is_overview_imported_service(service):
                    # L'Overview est déjà un total calculé.
                    # Si l'option est cochée, on trace que l'huile/coolant est remplacé
                    # par le calcul logiciel, sans ajouter une deuxième fois le montant.
                    if replace_overview_fluids and fluid_total > 0:
                        service_price = max(service_price - fluid_total, 0) + fluid_total
                else:
                    service_price += fluid_total

            # Anti-doublon import Volvo / Overview :
            # un service importé sert à afficher le périmètre inclus,
            # mais son montant est déjà repris dans total_parts / total_labour / total_misc.
            # On continue donc à appliquer DC, marge, indexation et frais sur la base importée,
            # sans ajouter le service importé une deuxième fois comme service additionnel.
            service_price_for_total = service_price

            if is_overview_imported_service(service):
                service_price_for_total = 0

            # Anti-doublon 2.1 / 2.2 :
            # si le 2.2 importe Volvo/Overview est deja present,
            # le 2.1 peut rester visible dans Base Care mais ne doit pas
            # ajouter une seconde fois les memes pieces de maintenance.
            if (
                imported_overview_2_2_present
                and str(service["service_id"] or "") == "2,1"
            ):
                service_price_for_total = 0

            additional_services_total += service_price_for_total

            conn.execute(
                """
                UPDATE quote_services
                SET calculated_price = ?
                WHERE id = ?
                """,
                (service_price, service["id"]),
            )

        # Indexation conforme à l'ancien Excel :
        # - Parts et labour sont indexés avec le coefficient cumulé de l'année finale du contrat.
        # - Misc, travel et other services ne sont pas indexés.
        # - Les frais admin/logistique restent calculés sur la base client non indexée.
        parts_factor = 1
        labour_factor = 1

        for year_number in range(1, contract_years + 1):
            parts_indexation = get_setting_float(settings, f"indexation_parts_year_{year_number}", 0)
            labour_indexation = get_setting_float(settings, f"indexation_labour_year_{year_number}", 0)

            parts_factor = parts_factor * (1 + parts_indexation / 100)
            labour_factor = labour_factor * (1 + labour_indexation / 100)

        indexed_parts = selling_parts * parts_factor
        indexed_labour = selling_labour * labour_factor

        non_indexed_subtotal = selling_parts + selling_labour + selling_misc + additional_services_total

        logistics_fee_amount = non_indexed_subtotal * logistics_fee / 100
        admin_fee_amount = non_indexed_subtotal * admin_fee / 100

        selling_total = (
            indexed_parts
            + indexed_labour
            + selling_misc
            + additional_services_total
            + logistics_fee_amount
            + admin_fee_amount
        )

        selling_per_hour = None
        if total_hours:
            selling_per_hour = selling_total / total_hours

        selling_monthly = None
        if total_hours and hours_per_year:
            years = total_hours / hours_per_year
            months = years * 12
            if months:
                selling_monthly = selling_total / months

        conn.execute(
            """
            UPDATE quotes
            SET
                fluid_total = ?,
                selling_total = ?,
                selling_monthly = ?,
                selling_per_hour = ?
            WHERE id = ?
            """,
            (
                fluid_total,
                selling_total,
                selling_monthly,
                selling_per_hour,
                quote_id,
            ),
        )

        conn.commit()

    print(f"Pricing applique au devis ID {quote_id}")
    print(f"Pieces achat dealer : {total_parts:.2f} {currency}")
    print(f"Pieces vente client : {selling_parts:.2f} {currency}")
    print(f"Lignes pièces avec DC utilisées : {dc_lines_used}")
    print(f"Main d'oeuvre base : {total_labour:.2f} {currency} + {labour_margin}%")
    print(f"Services additionnels inclus : {additional_services_total:.2f} {currency}")
    print(f"Total huile + coolant logiciel : {fluid_total:.2f} {currency}")
    print(f"Remplacement huile/coolant Overview : {'oui' if replace_overview_fluids else 'non'}")
    print(f"Frais deplacement fixes : {travel_fee_fixed:.2f} {currency}")
    print(f"Frais logistique : {logistics_fee}%")
    print(f"Frais admin : {admin_fee}%")
    print(f"Durée contrat calculée : {contract_years} an(s)")
    print("Indexations annuelles appliquées depuis Paramètres calcul")
    print(f"Prix client total : {selling_total:.2f} {currency}")

    if selling_monthly is not None:
        print(f"Prix mensuel : {selling_monthly:.2f} {currency}/mois")

    if selling_per_hour is not None:
        print(f"Prix par heure : {selling_per_hour:.2f} {currency}/h")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage : python backend/app/apply_pricing.py 1")
        raise SystemExit(1)

    apply_pricing(int(sys.argv[1]))
