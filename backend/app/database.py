from pathlib import Path
import sqlite3


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "dealer_quote_manager.sqlite"


def get_connection():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS imports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_file TEXT,
                imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
                engine_serial_number TEXT,
                product_designation TEXT,
                currency TEXT,
                total_cost REAL,
                raw_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS quotes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                import_id INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'draft',

                customer_name TEXT,
                engine_serial_number TEXT,
                product_name TEXT,
                product_designation TEXT,
                country TEXT,

                currency TEXT,
                total_hours REAL,
                hours_per_year REAL,
                labour_rate REAL,

                total_parts REAL,
                total_labour REAL,
                total_misc REAL,
                total_cost REAL,

                selling_total REAL,
                selling_monthly REAL,
                selling_per_hour REAL,

                FOREIGN KEY(import_id) REFERENCES imports(id)
            );

            CREATE TABLE IF NOT EXISTS quote_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quote_id INTEGER NOT NULL,
                component TEXT,
                description TEXT,
                part_number TEXT,
                quantity REAL,
                unit_price REAL,
                total_price REAL,
                labour_time REAL,
                source_sheet TEXT,

                FOREIGN KEY(quote_id) REFERENCES quotes(id)
            );

            CREATE TABLE IF NOT EXISTS interventions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quote_id INTEGER NOT NULL,
                intervention_date TEXT,
                engine_hours REAL,
                parts_cost REAL,
                labour_cost REAL,
                misc_cost REAL,
                total_cost REAL,
                source_sheet TEXT,

                FOREIGN KEY(quote_id) REFERENCES quotes(id)
            );

            CREATE TABLE IF NOT EXISTS dealer_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL UNIQUE,
                value REAL NOT NULL,
                description TEXT
            );

            CREATE TABLE IF NOT EXISTS quote_services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quote_id INTEGER NOT NULL,
                service_id TEXT NOT NULL,
                service_group TEXT,
                service_name TEXT,
                source_excel TEXT,
                included INTEGER DEFAULT 0,
                work_time_hours REAL DEFAULT 0,
                quantity REAL DEFAULT 0,
                unit_price REAL DEFAULT 0,
                fixed_price REAL DEFAULT 0,
                extra_travel TEXT DEFAULT 'Exclude',
                calculated_price REAL DEFAULT 0,
                notes TEXT,
                UNIQUE(quote_id, service_id),
                FOREIGN KEY(quote_id) REFERENCES quotes(id)
            );
            """
        )

    print(f"Base initialisee : {DB_PATH}")


if __name__ == "__main__":
    init_db()
