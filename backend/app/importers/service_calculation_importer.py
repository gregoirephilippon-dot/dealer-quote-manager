"""
Importeur ServiceCalculationExport.xlsx

But : lire un export Service Calculator et produire un JSON propre,
utilisable ensuite pour créer un devis brouillon dans le futur soft.

Usage :
    python service_calculation_importer.py /chemin/ServiceCalculationExport.xlsx --out summary.json

Dépendance :
    pip install openpyxl
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, date
from pathlib import Path
from typing import Any, Optional

from openpyxl import load_workbook


INTERVENTION_SHEET_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*\((\d+)\)$")
SERVICE_GROUP_RE = re.compile(r"^[A-Z]$")


@dataclass
class EngineInfo:
    unit: Optional[str] = None
    installation: Optional[str] = None
    chassis_id: Optional[str] = None
    serial_number: Optional[str] = None
    product_category: Optional[str] = None
    product_name: Optional[str] = None
    product_designation: Optional[str] = None
    product_part_number: Optional[str] = None
    status: Optional[str] = None
    current_country: Optional[str] = None


@dataclass
class CalculationBasis:
    price_list_used: Optional[str] = None
    currency: Optional[str] = None
    total_calculation_hours: Optional[float] = None
    op_hours_per_year: Optional[float] = None
    labour_rate: Optional[float] = None
    number_of_service_interventions: Optional[int] = None


@dataclass
class CalculationResult:
    cost_per_hour: Optional[float] = None
    total_labour_hours: Optional[float] = None
    total_labour_cost: Optional[float] = None
    total_material_cost: Optional[float] = None
    total_additional_material_cost: Optional[float] = None
    misc_cost: Optional[float] = None
    total: Optional[float] = None


def clean(value: Any) -> Any:
    """Nettoie les valeurs Excel pour les rendre JSON-friendly."""
    if isinstance(value, str):
        value = value.strip()
        return value if value else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def to_float(value: Any) -> Optional[float]:
    value = clean(value)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> Optional[int]:
    number = to_float(value)
    if number is None:
        return None
    return int(number)


def normalize_key(label: str) -> str:
    return (
        label.strip()
        .lower()
        .replace("/", "_")
        .replace(" ", "_")
        .replace("-", "_")
        .replace("__", "_")
    )


def get_ws(wb, name: str):
    if name not in wb.sheetnames:
        raise ValueError(f"Onglet manquant : {name}")
    return wb[name]


def parse_first_page(wb) -> dict[str, Any]:
    ws = get_ws(wb, "First page")

    # Ligne 2 = titres moteur, ligne 3 = valeurs moteur dans l'export actuel.
    headers = [clean(cell.value) for cell in ws[2]]
    values = [clean(cell.value) for cell in ws[3]]
    row_map = {h: v for h, v in zip(headers, values) if h}

    engine = EngineInfo(
        unit=row_map.get("Unit"),
        installation=row_map.get("Installation"),
        chassis_id=row_map.get("ChassisID"),
        serial_number=str(row_map.get("Serial Number")) if row_map.get("Serial Number") is not None else None,
        product_category=row_map.get("Product Category"),
        product_name=row_map.get("Product Name"),
        product_designation=row_map.get("Product Designation"),
        product_part_number=str(row_map.get("Product Part Number")) if row_map.get("Product Part Number") is not None else None,
        status=row_map.get("Status"),
        current_country=row_map.get("Current Country"),
    )

    # Lecture par libellés en colonne A, valeur en colonne B.
    labels: dict[str, Any] = {}
    for row in ws.iter_rows(min_row=1, max_row=60, values_only=True):
        label = clean(row[0])
        if label is not None:
            labels[label] = clean(row[1]) if len(row) > 1 else None

    basis = CalculationBasis(
        price_list_used=clean(ws[6][0].value),
        currency=labels.get("Currency"),
        total_calculation_hours=to_float(labels.get("Total No of calculation hours")),
        op_hours_per_year=to_float(labels.get("Op hrs / year")),
        labour_rate=to_float(labels.get("Labour rate")),
        number_of_service_interventions=to_int(labels.get("No of service interventions")),
    )

    result = CalculationResult(
        cost_per_hour=to_float(labels.get("Cost per hour")),
        total_labour_hours=to_float(labels.get("Total labour hours")),
        total_labour_cost=to_float(labels.get("Total labour cost")),
        total_material_cost=to_float(labels.get("Total material cost")),
        total_additional_material_cost=to_float(labels.get("Total additional material cost")),
        misc_cost=to_float(labels.get("Misc cost")),
        total=to_float(labels.get("Total")),
    )

    return {
        "engine": asdict(engine),
        "calculation_basis": asdict(basis),
        "calculation_result": asdict(result),
    }


def parse_hidden_for_import(wb) -> list[dict[str, Any]]:
    ws = get_ws(wb, "Hidden for import")
    lines: list[dict[str, Any]] = []
    current_group: Optional[str] = None

    for row_number, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        component, price, time, part_no, qty = [clean(v) for v in row[:5]]
        if component is None:
            continue

        component_text = str(component)
        is_group = bool(SERVICE_GROUP_RE.match(component_text)) and price is None and time is None and part_no is None

        if is_group:
            current_group = component_text
            line_type = "service_group"
        elif component_text.lower() == "labour":
            line_type = "labour"
        elif part_no is not None:
            line_type = "part"
        else:
            line_type = "operation"

        lines.append(
            {
                "source_row": row_number,
                "group": current_group,
                "line_type": line_type,
                "component": component_text,
                "unit_price": to_float(price),
                "labour_time": to_float(time),
                "part_number": str(part_no) if part_no is not None else None,
                "quantity": to_float(qty),
            }
        )

    return lines


def intervention_dates_from_sheets(wb) -> dict[str, int]:
    dates: dict[str, int] = {}
    for name in wb.sheetnames:
        match = INTERVENTION_SHEET_RE.match(name)
        if match:
            dates[match.group(1)] = int(match.group(2))
    return dates


def parse_overview(wb) -> dict[str, Any]:
    ws = get_ws(wb, "Overview")
    sheet_date_hours = intervention_dates_from_sheets(wb)

    headers = [clean(cell.value) for cell in ws[1]]
    date_columns: list[tuple[int, str]] = []
    for index, header in enumerate(headers, start=1):
        if isinstance(header, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", header):
            date_columns.append((index, header))

    lines: list[dict[str, Any]] = []
    totals_by_name: dict[str, dict[str, Any]] = {}
    current_group: Optional[str] = None

    for row_number in range(2, ws.max_row + 1):
        component = clean(ws.cell(row_number, 1).value)
        if component is None:
            continue
        component_text = str(component)

        line = {
            "source_row": row_number,
            "component": component_text,
            "price": to_float(ws.cell(row_number, 2).value),
            "total_cost": to_float(ws.cell(row_number, 3).value),
            "total_time": to_float(ws.cell(row_number, 4).value),
            "interval_hours": to_float(ws.cell(row_number, 5).value),
            "interval_months": to_float(ws.cell(row_number, 6).value),
            "part_number": str(clean(ws.cell(row_number, 7).value)) if clean(ws.cell(row_number, 7).value) is not None else None,
            "quantity": to_float(ws.cell(row_number, 8).value),
            "group": current_group,
            "schedule_quantities": {},
        }

        is_group = bool(SERVICE_GROUP_RE.match(component_text)) and line["price"] is None
        if is_group:
            current_group = component_text
            line["group"] = current_group
            line["line_type"] = "service_group"
        elif component_text in {"Parts", "Labour", "Misc", "Total", "Accumulated"}:
            line["line_type"] = "summary_total"
            totals_by_name[component_text.lower()] = line
        elif component_text.lower() == "labour":
            line["line_type"] = "labour"
        elif line["part_number"]:
            line["line_type"] = "part"
        else:
            line["line_type"] = "operation"

        for col_index, date_str in date_columns:
            qty = to_float(ws.cell(row_number, col_index).value)
            if qty is not None:
                line["schedule_quantities"][date_str] = qty

        lines.append(line)

    interventions: list[dict[str, Any]] = []
    for col_index, date_str in date_columns:
        interventions.append(
            {
                "date": date_str,
                "engine_hours": sheet_date_hours.get(date_str),
                "parts_cost": to_float(ws.cell(totals_by_name["parts"]["source_row"], col_index).value) if "parts" in totals_by_name else None,
                "labour_cost": to_float(ws.cell(totals_by_name["labour"]["source_row"], col_index).value) if "labour" in totals_by_name else None,
                "misc_cost": to_float(ws.cell(totals_by_name["misc"]["source_row"], col_index).value) if "misc" in totals_by_name else None,
                "total_cost": to_float(ws.cell(totals_by_name["total"]["source_row"], col_index).value) if "total" in totals_by_name else None,
                "accumulated_cost": to_float(ws.cell(totals_by_name["accumulated"]["source_row"], col_index).value) if "accumulated" in totals_by_name else None,
            }
        )

    return {
        "overview_lines": lines,
        "interventions": interventions,
    }


def parse_intervention_sheets(wb) -> list[dict[str, Any]]:
    interventions: list[dict[str, Any]] = []

    for sheet_name in wb.sheetnames:
        match = INTERVENTION_SHEET_RE.match(sheet_name)
        if not match:
            continue

        ws = wb[sheet_name]
        current_group: Optional[str] = None
        lines: list[dict[str, Any]] = []

        for row_number in range(2, ws.max_row + 1):
            component = clean(ws.cell(row_number, 1).value)
            if component is None:
                continue
            component_text = str(component)
            price = to_float(ws.cell(row_number, 2).value)
            part_no = clean(ws.cell(row_number, 7).value)

            is_group = bool(SERVICE_GROUP_RE.match(component_text)) and price is None
            if is_group:
                current_group = component_text
                line_type = "service_group"
            elif component_text.lower() == "labour":
                line_type = "labour"
            elif part_no is not None:
                line_type = "part"
            else:
                line_type = "operation"

            lines.append(
                {
                    "source_row": row_number,
                    "group": current_group,
                    "line_type": line_type,
                    "component": component_text,
                    "price": price,
                    "total_cost": to_float(ws.cell(row_number, 3).value),
                    "time": to_float(ws.cell(row_number, 4).value),
                    "interval_hours": to_float(ws.cell(row_number, 5).value),
                    "interval_months": to_float(ws.cell(row_number, 6).value),
                    "part_number": str(part_no) if part_no is not None else None,
                    "quantity": to_float(ws.cell(row_number, 8).value),
                }
            )

        interventions.append(
            {
                "sheet_name": sheet_name,
                "date": match.group(1),
                "engine_hours": int(match.group(2)),
                "lines": lines,
            }
        )

    return interventions


def parse_profitability(wb) -> dict[str, Any]:
    if "Profitabillity" not in wb.sheetnames:
        return {}

    ws = wb["Profitabillity"]
    rows: list[dict[str, Any]] = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        label = clean(row[0])
        if label is None:
            continue
        rows.append(
            {
                "category": str(label),
                "customer_cost": to_float(row[1]),
                "workshop_cost": to_float(row[2]),
                "profitability": to_float(row[3]),
            }
        )
    return {"rows": rows}


def build_quote_draft(summary: dict[str, Any]) -> dict[str, Any]:
    """Crée un premier brouillon de devis exploitable par la future application."""
    engine = summary["engine"]
    basis = summary["calculation_basis"]
    result = summary["calculation_result"]

    total_hours = basis.get("total_calculation_hours")
    op_hours_per_year = basis.get("op_hours_per_year")
    duration_years = None
    if total_hours and op_hours_per_year:
        duration_years = total_hours / op_hours_per_year

    return {
        "status": "draft_imported",
        "client": None,
        "engine": engine,
        "contract": {
            "currency": basis.get("currency"),
            "duration_years": duration_years,
            "total_hours": total_hours,
            "hours_per_year": op_hours_per_year,
            "number_of_interventions": basis.get("number_of_service_interventions"),
        },
        "base_costs": {
            "parts": result.get("total_material_cost"),
            "labour": result.get("total_labour_cost"),
            "misc": result.get("misc_cost"),
            "total": result.get("total"),
            "cost_per_hour": result.get("cost_per_hour"),
        },
        "dealer_parameters_to_add_later": {
            "parts_margin_percent": None,
            "labour_margin_percent": None,
            "admin_fee_percent": None,
            "logistics_fee_percent": None,
            "travel_cost": None,
            "indexation_percent_per_year": None,
        },
    }


def import_service_calculation(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    wb = load_workbook(path, data_only=True, read_only=True)

    summary: dict[str, Any] = {
        "source_file": path.name,
        "import_type": "ServiceCalculationExport",
        "imported_at": datetime.now().isoformat(timespec="seconds"),
        "workbook_sheets": wb.sheetnames,
    }
    summary.update(parse_first_page(wb))
    summary["hidden_import_lines"] = parse_hidden_for_import(wb)
    overview = parse_overview(wb)
    summary.update(overview)
    summary["intervention_details"] = parse_intervention_sheets(wb)
    summary["profitability"] = parse_profitability(wb)
    summary["quote_draft"] = build_quote_draft(summary)

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Importe un ServiceCalculationExport.xlsx en JSON.")
    parser.add_argument("input", help="Chemin vers ServiceCalculationExport.xlsx")
    parser.add_argument("--out", help="Fichier JSON de sortie")
    parser.add_argument("--pretty", action="store_true", help="Affiche un JSON indenté")
    args = parser.parse_args()

    data = import_service_calculation(args.input)
    json_text = json.dumps(data, ensure_ascii=False, indent=2 if args.pretty else None)

    if args.out:
        Path(args.out).write_text(json_text, encoding="utf-8")
        print(f"Import OK - {args.out}")
        result = data["calculation_result"]
        engine = data["engine"]
        print(f"Moteur : {engine.get('product_designation')} / SN {engine.get('serial_number')}")
        print(f"Total : {result.get('total')} {data['calculation_basis'].get('currency')}")
        print(f"Interventions : {len(data.get('interventions', []))}")
    else:
        print(json_text)


if __name__ == "__main__":
    main()
