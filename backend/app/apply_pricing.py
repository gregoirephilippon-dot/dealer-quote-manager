import json
import math
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
        ("oil_catalog_part_no", "TEXT"),
        ("oil_price_per_liter", "REAL DEFAULT 0"),
        ("oil_service_count", "REAL DEFAULT 0"),
        ("oil_quantity_per_service", "REAL DEFAULT 0"),
        ("oil_packaging_mode", "TEXT DEFAULT 'consumed'"),
        ("oil_packaging_liters", "REAL DEFAULT 0"),
        ("coolant_catalog_part_no", "TEXT"),
        ("coolant_price_per_liter", "REAL DEFAULT 0"),
        ("coolant_service_count", "REAL DEFAULT 0"),
        ("coolant_quantity_per_service", "REAL DEFAULT 0"),
        ("coolant_concentrate_percent", "REAL DEFAULT 100"),
        ("coolant_packaging_mode", "TEXT DEFAULT 'consumed'"),
        ("coolant_packaging_liters", "REAL DEFAULT 0"),
        ("fluid_total", "REAL DEFAULT 0"),
        ("replace_overview_fluids", "INTEGER DEFAULT 0"),
        ("replace_imported_oil", "INTEGER DEFAULT 0"),
        ("replace_imported_coolant", "INTEGER DEFAULT 0"),
        ("pricing_trace_json", "TEXT"),
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


def calculate_fluid_totals_from_quote(quote):
    oil_price_per_liter = to_float(
        quote_value(quote, "oil_price_per_liter", 0)
    )
    oil_service_count = to_float(
        quote_value(quote, "oil_service_count", 0)
    )
    oil_quantity_per_service = to_float(
        quote_value(quote, "oil_quantity_per_service", 0)
    )
    oil_packaging_liters = to_float(
        quote_value(quote, "oil_packaging_liters", 0)
    )
    oil_packaging_mode = str(
        quote_value(quote, "oil_packaging_mode", "consumed") or "consumed"
    ).strip().lower()

    oil_billable_liters_per_service = oil_quantity_per_service

    if (
        oil_packaging_mode == "package"
        and oil_packaging_liters > 0
        and oil_quantity_per_service > 0
    ):
        oil_billable_liters_per_service = (
            math.ceil(oil_quantity_per_service / oil_packaging_liters)
            * oil_packaging_liters
        )

    oil_total = (
        oil_price_per_liter
        * oil_service_count
        * oil_billable_liters_per_service
    )

    coolant_part_no = str(
        quote_value(quote, "coolant_catalog_part_no", "") or ""
    ).strip()

    coolant_is_concentrate = coolant_part_no in {
        "22567215",
        "22567217",
    }

    coolant_concentrate_percent = to_float(
        quote_value(quote, "coolant_concentrate_percent", 100)
    )

    # Compatibilite avec les devis existants :
    # vide ou <= 0 conserve l'ancien calcul a 100 %.
    if coolant_concentrate_percent <= 0:
        coolant_concentrate_percent = 100

    if coolant_concentrate_percent > 100:
        coolant_concentrate_percent = 100

    coolant_volume_factor = (
        coolant_concentrate_percent / 100
        if coolant_is_concentrate
        else 1
    )

    coolant_price_per_liter = to_float(
        quote_value(quote, "coolant_price_per_liter", 0)
    )
    coolant_service_count = to_float(
        quote_value(quote, "coolant_service_count", 0)
    )
    coolant_quantity_per_service = to_float(
        quote_value(quote, "coolant_quantity_per_service", 0)
    )
    coolant_packaging_liters = to_float(
        quote_value(quote, "coolant_packaging_liters", 0)
    )
    coolant_packaging_mode = str(
        quote_value(quote, "coolant_packaging_mode", "consumed") or "consumed"
    ).strip().lower()

    coolant_required_liters_per_service = (
        coolant_quantity_per_service * coolant_volume_factor
    )

    coolant_billable_liters_per_service = coolant_required_liters_per_service

    if (
        coolant_packaging_mode == "package"
        and coolant_packaging_liters > 0
        and coolant_required_liters_per_service > 0
    ):
        coolant_billable_liters_per_service = (
            math.ceil(
                coolant_required_liters_per_service / coolant_packaging_liters
            )
            * coolant_packaging_liters
        )

    coolant_total = (
        coolant_price_per_liter
        * coolant_service_count
        * coolant_billable_liters_per_service
    )

    return oil_total, coolant_total


def calculate_fluid_total_from_quote(quote):
    oil_total, coolant_total = calculate_fluid_totals_from_quote(quote)
    return oil_total + coolant_total



def calculate_catalog_fluid_prices(conn, part_no, catalog_total):
    """
    Applique aux fluides la meme logique DC que les pieces :
    - dealer net = catalogue x (1 - remise dealer)
    - client = catalogue x (1 - remise client)

    Si aucune reference catalogue exploitable n'est presente,
    le montant saisi/calcul? reste utilise sans remise.
    """
    catalog_total = to_float(catalog_total)
    part_no = str(part_no or "").strip()

    result = {
        "part_no": part_no,
        "discount_code": None,
        "catalog_total": catalog_total,
        "dealer_discount": 0.0,
        "customer_discount": 0.0,
        "dealer_total": catalog_total,
        "customer_total": catalog_total,
    }

    if not part_no or catalog_total <= 0:
        return result

    row = conn.execute(
        """
        SELECT discount_code
        FROM price_catalog
        WHERE TRIM(part_no) = ?
        LIMIT 1
        """,
        (part_no,),
    ).fetchone()

    if not row:
        return result

    dc = normalize_discount_code(row["discount_code"])

    if dc is None:
        return result

    discount_row = conn.execute(
        """
        SELECT dealer_discount, customer_type_discount
        FROM dealer_discount_codes
        WHERE dc = ?
        """,
        (dc,),
    ).fetchone()

    if not discount_row:
        return result

    dealer_discount = to_float(discount_row["dealer_discount"])
    customer_discount = to_float(discount_row["customer_type_discount"])

    result.update(
        {
            "discount_code": dc,
            "dealer_discount": dealer_discount,
            "customer_discount": customer_discount,
            "dealer_total": catalog_total * (1 - dealer_discount),
            "customer_total": catalog_total * (1 - customer_discount),
        }
    )

    return result


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
                source_labour_rate,
                source_total_labour_hours,
                source_total_labour_cost,
                oil_catalog_part_no,
                oil_price_per_liter,
                oil_service_count,
                oil_quantity_per_service,
                oil_packaging_mode,
                oil_packaging_liters,
                coolant_catalog_part_no,
                coolant_price_per_liter,
                coolant_service_count,
                coolant_quantity_per_service,
                coolant_concentrate_percent,
                coolant_packaging_mode,
                coolant_packaging_liters,
                fluid_total,
                replace_overview_fluids,
                replace_imported_oil,
                replace_imported_coolant
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

        imported_parts_total = total_parts
        imported_labour_total = total_labour
        imported_misc_total = total_misc
        imported_total_cost = quote["total_cost"] or (
            imported_parts_total
            + imported_labour_total
            + imported_misc_total
        )

        total_hours = quote["total_hours"] or 0
        hours_per_year = quote["hours_per_year"] or 0
        labour_rate_input = quote["labour_rate"] or 0
        oil_calculated_total, coolant_calculated_total = calculate_fluid_totals_from_quote(quote)

        coolant_part_no = str(
            quote_value(quote, "coolant_catalog_part_no", "") or ""
        ).strip()

        coolant_is_concentrate = coolant_part_no in {
            "22567215",
            "22567217",
        }

        coolant_concentrate_percent = to_float(
            quote_value(quote, "coolant_concentrate_percent", 100)
        )

        if coolant_concentrate_percent <= 0:
            coolant_concentrate_percent = 100

        if coolant_concentrate_percent > 100:
            coolant_concentrate_percent = 100

        coolant_volume_factor = (
            coolant_concentrate_percent / 100
            if coolant_is_concentrate
            else 1
        )

        replace_overview_fluids = bool(
            quote_value(quote, "replace_overview_fluids", 0)
        )
        replace_imported_oil = bool(
            quote_value(quote, "replace_imported_oil", 0)
        )
        replace_imported_coolant = bool(
            quote_value(quote, "replace_imported_coolant", 0)
        )

        imported_oil_present = conn.execute(
            """
            SELECT 1
            FROM quote_lines
            WHERE quote_id = ?
              AND COALESCE(quantity, 0) > 0
              AND (
                    lower(trim(COALESCE(description, ''))) = 'engine oil'
                 OR TRIM(COALESCE(part_number, '')) IN (
                        '24567220', '24567221', '24567222', '54419768'
                    )
              )
            LIMIT 1
            """,
            (quote_id,),
        ).fetchone() is not None

        imported_coolant_present = conn.execute(
            """
            SELECT 1
            FROM quote_lines
            WHERE quote_id = ?
              AND COALESCE(quantity, 0) > 0
              AND (
                    lower(trim(COALESCE(description, ''))) = 'volvo coolant ready mixed'
                 OR TRIM(COALESCE(part_number, '')) IN (
                        '22567233', '22567259', '22567215',
                        '24712786', '24712788', '24712790',
                        '24712783', '22567261', '22567217'
                    )
              )
            LIMIT 1
            """,
            (quote_id,),
        ).fetchone() is not None

        oil_software_active = (
            not imported_oil_present
            or replace_imported_oil
        )

        coolant_software_active = (
            not imported_coolant_present
            or replace_imported_coolant
        )

        oil_catalog_pricing = calculate_catalog_fluid_prices(
            conn,
            quote_value(quote, "oil_catalog_part_no", ""),
            oil_calculated_total,
        )

        coolant_catalog_pricing = calculate_catalog_fluid_prices(
            conn,
            quote_value(quote, "coolant_catalog_part_no", ""),
            coolant_calculated_total,
        )

        oil_dealer_total = (
            oil_catalog_pricing["dealer_total"]
            if oil_software_active
            else 0
        )

        coolant_dealer_total = (
            coolant_catalog_pricing["dealer_total"]
            if coolant_software_active
            else 0
        )

        oil_total = (
            oil_catalog_pricing["customer_total"]
            if oil_software_active
            else 0
        )

        coolant_total = (
            coolant_catalog_pricing["customer_total"]
            if coolant_software_active
            else 0
        )

        fluid_dealer_total = round(oil_dealer_total + coolant_dealer_total, 2)
        fluid_total = round(oil_total + coolant_total, 2)

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

        parts_rows = conn.execute(
            """
            SELECT
                ql.part_number,
                ql.description,
                ql.quantity,
                ql.unit_price AS imported_unit_price,
                ql.total_price AS imported_total_price,
                ql.discount_code,
                ql.dealer_net_total,
                ql.customer_price_total,
                pc.price_excl_vat AS catalog_unit_price,
                pc.product_group,
                pc.source_file AS catalog_source
            FROM quote_lines ql
            LEFT JOIN price_catalog pc
                ON TRIM(pc.part_no) = TRIM(ql.part_number)
            WHERE ql.quote_id = ?
            ORDER BY ql.id
            """,
            (quote_id,),
        ).fetchall()

        parts_trace = []

        for row in parts_rows:
            quantity = to_float(row["quantity"])
            imported_unit_price = to_float(row["imported_unit_price"])
            imported_total_price = to_float(row["imported_total_price"])
            catalog_unit_price = to_float(row["catalog_unit_price"])
            dealer_net_total = to_float(row["dealer_net_total"])
            customer_price_total = to_float(row["customer_price_total"])

            reference_total = imported_total_price
            if reference_total <= 0 and quantity > 0 and imported_unit_price > 0:
                reference_total = quantity * imported_unit_price

            dealer_discount_percent = None
            customer_discount_percent = None

            if reference_total > 0:
                dealer_discount_percent = (
                    1 - dealer_net_total / reference_total
                ) * 100
                customer_discount_percent = (
                    1 - customer_price_total / reference_total
                ) * 100

            margin_amount = customer_price_total - dealer_net_total
            margin_percent = (
                margin_amount / dealer_net_total * 100
                if dealer_net_total > 0
                else None
            )

            parts_trace.append(
                {
                    "part_number": row["part_number"] or "",
                    "description": row["description"] or "",
                    "quantity": quantity,
                    "imported_unit_price": imported_unit_price,
                    "imported_total_price": imported_total_price,
                    "catalog_unit_price": catalog_unit_price,
                    "discount_code": row["discount_code"] or "",
                    "product_group": row["product_group"] or "",
                    "catalog_source": row["catalog_source"] or "",
                    "dealer_discount_percent": dealer_discount_percent,
                    "dealer_net_total": dealer_net_total,
                    "customer_discount_percent": customer_discount_percent,
                    "customer_price_total": customer_price_total,
                    "margin_amount": margin_amount,
                    "margin_percent": margin_percent,
                }
            )

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
        services_trace = []

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

        service_2_2_present = "2,2" in included_service_ids

        fluid_service_id = None

        if fluid_total > 0:
            if "2,2" in included_service_ids:
                fluid_service_id = "2,2"
            elif "2,1" in included_service_ids:
                fluid_service_id = "2,1"

        for service in included_services:

            if is_overview_imported_service(service):
                # Montant déjà calculé dans l'Overview importé.
                # Ne pas recalculer avec work_time_hours x labour_rate.
                service_price = service["fixed_price"] or service["calculated_price"] or 0
            else:
                service_price = calculate_service_price(service, labour_rate_input, travel_fee_fixed)

            is_fluid_target = (
                fluid_service_id
                and str(service["service_id"] or "") == fluid_service_id
            )

            if is_fluid_target and not is_overview_imported_service(service):
                service_price += fluid_total

            # Anti-doublon import Volvo / Overview :
            # un service importé sert à afficher le périmètre inclus,
            # mais son montant est déjà repris dans total_parts / total_labour / total_misc.
            # On continue donc à appliquer DC, marge, indexation et frais sur la base importée,
            # sans ajouter le service importé une deuxième fois comme service additionnel.
            service_price_for_total = service_price

            if is_overview_imported_service(service):
                service_price_for_total = (
                    fluid_total
                    if is_fluid_target
                    else 0
                )

            # Anti-doublon 2.1 / 2.2 :
            # 2.1 = pieces de maintenance uniquement.
            # 2.2 = pieces de maintenance + main-d'oeuvre.
            # Si 2.2 est inclus, 2.1 ne doit jamais ajouter une seconde
            # fois les memes pieces, quelle que soit l'origine du 2.2.
            if (
                service_2_2_present
                and str(service["service_id"] or "") == "2,1"
            ):
                service_price_for_total = 0

            additional_services_total += service_price_for_total

            exclusion_reason = ""

            if is_overview_imported_service(service):
                exclusion_reason = (
                    "Amount already included in imported parts, labour and misc."
                )
            elif (
                service_2_2_present
                and str(service["service_id"] or "") == "2,1"
            ):
                exclusion_reason = (
                    "Neutralized to avoid duplicate maintenance parts "
                    "because service 2.2 already includes maintenance parts."
                )

            services_trace.append(
                {
                    "service_id": str(service["service_id"] or ""),
                    "service_name": service["service_name"] or "",
                    "source_excel": service["source_excel"] or "",
                    "calculated_price": service_price,
                    "amount_added_to_total": service_price_for_total,
                    "exclusion_reason": exclusion_reason,
                }
            )

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

        indexation_trace = []
        running_parts_factor = 1
        running_labour_factor = 1

        for year_number in range(1, contract_years + 1):
            parts_rate = get_setting_float(
                settings,
                f"indexation_parts_year_{year_number}",
                0,
            )
            labour_rate_index = get_setting_float(
                settings,
                f"indexation_labour_year_{year_number}",
                0,
            )

            running_parts_factor *= 1 + parts_rate / 100
            running_labour_factor *= 1 + labour_rate_index / 100

            indexation_trace.append(
                {
                    "year": year_number,
                    "parts_rate": parts_rate,
                    "labour_rate": labour_rate_index,
                    "parts_factor": running_parts_factor,
                    "labour_factor": running_labour_factor,
                }
            )

        imported_cost_per_hour = (
            imported_total_cost / total_hours
            if total_hours
            else None
        )

        pricing_trace = {
            "version": 1,
            "quote_id": quote_id,
            "currency": currency,
            "import": {
                "parts": imported_parts_total,
                "labour": imported_labour_total,
                "misc": imported_misc_total,
                "total_cost": imported_total_cost,
                "total_hours": total_hours,
                "hours_per_year": hours_per_year,
                "cost_per_hour": imported_cost_per_hour,
            },
            "parts": {
                "dealer_total": dealer_parts_total,
                "customer_total_before_indexation": selling_parts,
                "indexed_customer_total": indexed_parts,
                "dc_lines_used": dc_lines_used,
                "factor": parts_factor,
                "lines": parts_trace,
            },
            "labour": {
                "imported_total": total_labour,
                "source_rate": quote_value(quote, "source_labour_rate", None),
                "source_hours": quote_value(quote, "source_total_labour_hours", None),
                "source_total": quote_value(quote, "source_total_labour_cost", None),
                "active_rate": labour_rate_input,
                "active_total": total_labour,
                "delta": (
                    total_labour
                    - float(quote_value(quote, "source_total_labour_cost", 0) or 0)
                ),
                "margin_percent": labour_margin,
                "customer_total_before_indexation": selling_labour,
                "indexed_customer_total": indexed_labour,
                "factor": labour_factor,
            },
            "services": {
                "total_added": additional_services_total,
                "lines": services_trace,
            },
            "fluids": {
                "total": fluid_total,
                "service_id": fluid_service_id,
                "replace_overview": replace_overview_fluids,
                "oil": {
                    "part_no": quote_value(quote, "oil_catalog_part_no", ""),
                    "calculated_total": oil_calculated_total,
                    "catalog_total": oil_catalog_pricing["catalog_total"],
                    "discount_code": oil_catalog_pricing["discount_code"],
                    "dealer_discount_percent": oil_catalog_pricing["dealer_discount"] * 100,
                    "dealer_total": oil_dealer_total,
                    "customer_discount_percent": oil_catalog_pricing["customer_discount"] * 100,
                    "active_total": oil_total,
                    "imported_present": imported_oil_present,
                    "replace_imported": replace_imported_oil,
                    "software_active": oil_software_active,
                },
                "coolant": {
                    "part_no": quote_value(quote, "coolant_catalog_part_no", ""),
                    "is_concentrate": coolant_is_concentrate,
                    "concentrate_percent": (
                        coolant_concentrate_percent
                        if coolant_is_concentrate
                        else None
                    ),
                    "volume_factor": coolant_volume_factor,
                    "calculated_total": coolant_calculated_total,
                    "catalog_total": coolant_catalog_pricing["catalog_total"],
                    "discount_code": coolant_catalog_pricing["discount_code"],
                    "dealer_discount_percent": coolant_catalog_pricing["dealer_discount"] * 100,
                    "dealer_total": coolant_dealer_total,
                    "customer_discount_percent": coolant_catalog_pricing["customer_discount"] * 100,
                    "active_total": coolant_total,
                    "imported_present": imported_coolant_present,
                    "replace_imported": replace_imported_coolant,
                    "software_active": coolant_software_active,
                },
                "dealer_total": fluid_dealer_total,
            },
            "fees": {
                "travel_fixed_setting": travel_fee_fixed,
                "logistics_percent": logistics_fee,
                "logistics_amount": logistics_fee_amount,
                "admin_percent": admin_fee,
                "admin_amount": admin_fee_amount,
                "non_indexed_base": non_indexed_subtotal,
            },
            "indexation": indexation_trace,
            "result": {
                "contract_years": contract_years,
                "selling_total": selling_total,
                "selling_monthly": selling_monthly,
                "selling_per_hour": selling_per_hour,
                "cost_per_hour": imported_cost_per_hour,
            },
        }

        pricing_trace_json = json.dumps(
            pricing_trace,
            ensure_ascii=False,
        )

        conn.execute(
            """
            UPDATE quotes
            SET
                fluid_total = ?,
                selling_total = ?,
                selling_monthly = ?,
                selling_per_hour = ?,
                pricing_trace_json = ?
            WHERE id = ?
            """,
            (
                fluid_total,
                selling_total,
                selling_monthly,
                selling_per_hour,
                pricing_trace_json,
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
    print(f"Huile catalogue : {oil_calculated_total:.2f} {currency}")
    print(f"Huile cout dealer : {oil_dealer_total:.2f} {currency}")
    print(f"Huile prix client actif : {oil_total:.2f} {currency}")
    print(f"Coolant catalogue : {coolant_calculated_total:.2f} {currency}")
    print(f"Coolant cout dealer : {coolant_dealer_total:.2f} {currency}")
    print(f"Coolant prix client actif : {coolant_total:.2f} {currency}")
    print(f"Total fluides cout dealer : {fluid_dealer_total:.2f} {currency}")
    print(f"Total fluides prix client : {fluid_total:.2f} {currency}")
    print(f"Service fluides : {fluid_service_id or 'aucun'}")
    print(f"Huile importee detectee : {'oui' if imported_oil_present else 'non'}")
    print(f"Huile importee neutralisee : {'oui' if replace_imported_oil else 'non'}")
    print(f"Coolant importe detecte : {'oui' if imported_coolant_present else 'non'}")
    print(f"Coolant importe neutralise : {'oui' if replace_imported_coolant else 'non'}")
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
