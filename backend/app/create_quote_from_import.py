import json
import sys
from pathlib import Path

from database import get_connection, init_db


def create_quote_from_json(json_path: str):
    path = Path(json_path)

    if not path.exists():
        raise FileNotFoundError(path)

    data = json.loads(path.read_text(encoding="utf-8"))

    engine = data.get("engine", {})
    basis = data.get("calculation_basis", {})
    result = data.get("calculation_result", {})
    lines = data.get("hidden_import_lines", [])
    interventions = data.get("interventions", [])

    engine_serial = engine.get("serial_number")
    product_name = engine.get("product_name")
    product_designation = engine.get("product_designation")
    country = engine.get("current_country")

    currency = basis.get("currency") or "EUR"

    total_hours = basis.get("total_calculation_hours")
    hours_per_year = basis.get("op_hours_per_year")
    labour_rate = basis.get("labour_rate")

    total_parts = result.get("total_material_cost")
    total_labour = result.get("total_labour_cost")
    total_misc = result.get("misc_cost")
    total_cost = result.get("total")
    cost_per_hour = result.get("cost_per_hour")

    init_db()

    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO imports (
                source_file,
                engine_serial_number,
                product_designation,
                currency,
                total_cost,
                raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(path),
                engine_serial,
                product_designation,
                currency,
                total_cost,
                json.dumps(data, ensure_ascii=False),
            ),
        )

        import_id = cursor.lastrowid

        cursor.execute(
            """
            INSERT INTO quotes (
                import_id,
                status,
                engine_serial_number,
                product_name,
                product_designation,
                country,
                currency,
                total_hours,
                hours_per_year,
                labour_rate,
                total_parts,
                total_labour,
                total_misc,
                total_cost,
                selling_total,
                selling_monthly,
                selling_per_hour
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                import_id,
                "draft",
                engine_serial,
                product_name,
                product_designation,
                country,
                currency,
                total_hours,
                hours_per_year,
                labour_rate,
                total_parts,
                total_labour,
                total_misc,
                total_cost,
                total_cost,
                None,
                cost_per_hour,
            ),
        )

        quote_id = cursor.lastrowid

        for line in lines:
            quantity = line.get("quantity")
            unit_price = line.get("unit_price")

            total_price = None
            if quantity is not None and unit_price is not None:
                total_price = quantity * unit_price

            cursor.execute(
                """
                INSERT INTO quote_lines (
                    quote_id,
                    component,
                    description,
                    part_number,
                    quantity,
                    unit_price,
                    total_price,
                    labour_time,
                    source_sheet
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    quote_id,
                    line.get("group"),
                    line.get("component"),
                    line.get("part_number"),
                    quantity,
                    unit_price,
                    total_price,
                    line.get("labour_time"),
                    "Hidden for import",
                ),
            )

        for intervention in interventions:
            cursor.execute(
                """
                INSERT INTO interventions (
                    quote_id,
                    intervention_date,
                    engine_hours,
                    parts_cost,
                    labour_cost,
                    misc_cost,
                    total_cost,
                    source_sheet
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    quote_id,
                    intervention.get("date"),
                    intervention.get("engine_hours"),
                    intervention.get("parts_cost"),
                    intervention.get("labour_cost"),
                    intervention.get("misc_cost"),
                    intervention.get("total_cost"),
                    intervention.get("source_sheet"),
                ),
            )

        conn.commit()

    print(f"Devis brouillon cree : ID {quote_id}")
    print(f"Moteur : {product_designation} / SN {engine_serial}")
    print(f"Total : {total_cost} {currency}")
    print(f"Lignes : {len(lines)}")
    print(f"Interventions : {len(interventions)}")

    return quote_id


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage : python backend/app/create_quote_from_import.py data/examples/service_calculation_summary.json")
        raise SystemExit(1)

    create_quote_from_json(sys.argv[1])