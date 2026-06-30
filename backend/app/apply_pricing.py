import sys
from database import get_connection, init_db
from settings import get_settings_dict


def apply_margin(amount, percent):
    if amount is None:
        amount = 0
    return amount * (1 + percent / 100)


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


def apply_pricing(quote_id: int):
    init_db()

    with get_connection() as conn:
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
                labour_rate
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

        parts_margin = settings.get("parts_margin_percent", 0)
        labour_margin = settings.get("labour_margin_percent", 0)
        admin_fee = settings.get("admin_fee_percent", 0)
        logistics_fee = settings.get("logistics_fee_percent", 0)
        travel_fee_fixed = settings.get("travel_fee_fixed", 0)
        indexation = settings.get("indexation_percent", 0)

        selling_parts = apply_margin(total_parts, parts_margin)
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

        for service in included_services:
            service_price = calculate_service_price(service, labour_rate_input, travel_fee_fixed)
            additional_services_total += service_price

            conn.execute(
                """
                UPDATE quote_services
                SET calculated_price = ?
                WHERE id = ?
                """,
                (service_price, service["id"]),
            )

        subtotal = selling_parts + selling_labour + selling_misc + additional_services_total

        logistics_amount = subtotal * logistics_fee / 100
        admin_amount = subtotal * admin_fee / 100

        selling_total = subtotal + logistics_amount + admin_amount

        if indexation:
            selling_total = selling_total * (1 + indexation / 100)

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
                selling_total = ?,
                selling_monthly = ?,
                selling_per_hour = ?
            WHERE id = ?
            """,
            (
                selling_total,
                selling_monthly,
                selling_per_hour,
                quote_id,
            ),
        )

        conn.commit()

    print(f"Pricing applique au devis ID {quote_id}")
    print(f"Pieces base : {total_parts:.2f} {currency} + {parts_margin}%")
    print(f"Main d'oeuvre base : {total_labour:.2f} {currency} + {labour_margin}%")
    print(f"Services additionnels inclus : {additional_services_total:.2f} {currency}")
    print(f"Frais deplacement fixes : {travel_fee_fixed:.2f} {currency}")
    print(f"Frais logistique : {logistics_fee}%")
    print(f"Frais admin : {admin_fee}%")
    print(f"Indexation : {indexation}%")
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
