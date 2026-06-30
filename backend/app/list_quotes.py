from database import get_connection, init_db


def list_quotes():
    init_db()

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                created_at,
                status,
                product_designation,
                engine_serial_number,
                currency,
                total_cost,
                selling_total,
                selling_per_hour
            FROM quotes
            ORDER BY id DESC
            """
        ).fetchall()

    if not rows:
        print("Aucun devis trouve.")
        return

    print("Historique des devis")
    print("-" * 100)

    for row in rows:
        total_cost = row["total_cost"]
        selling_total = row["selling_total"]
        selling_per_hour = row["selling_per_hour"]

        total_cost_txt = f"{total_cost:.2f}" if total_cost is not None else "-"
        selling_total_txt = f"{selling_total:.2f}" if selling_total is not None else "-"
        selling_per_hour_txt = f"{selling_per_hour:.2f}" if selling_per_hour is not None else "-"

        print(
            f"ID {row['id']} | "
            f"{row['created_at']} | "
            f"{row['status']} | "
            f"{row['product_designation']} | "
            f"SN {row['engine_serial_number']} | "
            f"Cout {total_cost_txt} {row['currency']} | "
            f"Prix {selling_total_txt} {row['currency']} | "
            f"{selling_per_hour_txt} {row['currency']}/h"
        )


if __name__ == "__main__":
    list_quotes()