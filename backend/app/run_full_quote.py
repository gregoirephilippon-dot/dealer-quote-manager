import sys
import subprocess
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_JSON = BASE_DIR / "data" / "examples" / "service_calculation_summary.json"


def run_command(command):
    print("")
    print("Commande :", " ".join(str(x) for x in command))
    print("-" * 80)

    result = subprocess.run(
        command,
        cwd=BASE_DIR,
        text=True,
        capture_output=True,
    )

    if result.stdout:
        print(result.stdout)

    if result.stderr:
        print(result.stderr)

    if result.returncode != 0:
        raise RuntimeError(f"Commande echouee : {' '.join(str(x) for x in command)}")

    return result


def extract_quote_id(output: str):
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Devis brouillon cree : ID"):
            return int(line.split("ID", 1)[1].strip())
    return None


def run_full_quote(input_excel: str):
    input_path = Path(input_excel)

    if not input_path.exists():
        raise FileNotFoundError(input_path)

    DEFAULT_JSON.parent.mkdir(parents=True, exist_ok=True)

    print("Dealer Quote Manager - generation complete")
    print("=" * 80)
    print(f"Input Excel : {input_path}")
    print(f"JSON sortie : {DEFAULT_JSON}")

    run_command(
        [
            sys.executable,
            "backend/app/database.py",
        ]
    )

    run_command(
        [
            sys.executable,
            "backend/app/importers/service_calculation_importer.py",
            str(input_path),
            "--out",
            str(DEFAULT_JSON),
            "--pretty",
        ]
    )

    create_result = run_command(
        [
            sys.executable,
            "backend/app/create_quote_from_import.py",
            str(DEFAULT_JSON),
        ]
    )

    quote_id = extract_quote_id(create_result.stdout)

    if quote_id is None:
        raise RuntimeError("Impossible de recuperer l'ID du devis cree.")

    run_command(
        [
            sys.executable,
            "backend/app/apply_pricing.py",
            str(quote_id),
        ]
    )

    run_command(
        [
            sys.executable,
            "backend/app/export_quote_html.py",
            str(quote_id),
        ]
    )

    run_command(
        [
            sys.executable,
            "backend/app/export_quote_pdf.py",
            str(quote_id),
        ]
    )

    pdf_path = BASE_DIR / "data" / "exports" / f"quote_{quote_id}.pdf"
    html_path = BASE_DIR / "data" / "exports" / f"quote_{quote_id}.html"

    print("")
    print("=" * 80)
    print("Generation terminee")
    print(f"Devis ID : {quote_id}")
    print(f"PDF : {pdf_path}")
    print(f"HTML : {html_path}")
    print("")
    print("Pour ouvrir le PDF :")
    print(f"start {pdf_path}")

    return quote_id


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage : python backend/app/run_full_quote.py ServiceCalculationExport.xlsx")
        raise SystemExit(1)

    run_full_quote(sys.argv[1])
