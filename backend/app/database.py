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

                oil_catalog_part_no TEXT,
                oil_price_per_liter REAL DEFAULT 0,
                oil_service_count REAL DEFAULT 0,
                oil_quantity_per_service REAL DEFAULT 0,
                oil_packaging_mode TEXT DEFAULT 'consumed',
                oil_packaging_liters REAL DEFAULT 0,
                coolant_catalog_part_no TEXT,
                coolant_price_per_liter REAL DEFAULT 0,
                coolant_service_count REAL DEFAULT 0,
                coolant_quantity_per_service REAL DEFAULT 0,
                coolant_concentrate_percent REAL DEFAULT 100,
                coolant_packaging_mode TEXT DEFAULT 'consumed',
                coolant_packaging_liters REAL DEFAULT 0,
                fluid_total REAL DEFAULT 0,
                replace_overview_fluids INTEGER DEFAULT 0,
                replace_imported_oil INTEGER DEFAULT 0,
                replace_imported_coolant INTEGER DEFAULT 0,

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
                discount_code TEXT,
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

            CREATE TABLE IF NOT EXISTS contracts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quote_id INTEGER NOT NULL,
                contract_number TEXT NOT NULL UNIQUE,
                company_id INTEGER,
                status TEXT DEFAULT 'draft',
                customer_name TEXT,
                engine_serial_number TEXT,
                product_name TEXT,
                product_designation TEXT,
                start_date TEXT,
                planned_end_date TEXT,
                start_engine_hours REAL DEFAULT 0,
                current_engine_hours REAL DEFAULT 0,
                planned_end_engine_hours REAL DEFAULT 0,
                hours_per_year REAL DEFAULT 0,
                package_key TEXT,
                currency TEXT DEFAULT 'EUR',
                contract_total REAL DEFAULT 0,
                billing_mode TEXT DEFAULT 'monthly',
                billing_day INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                activated_at TEXT,
                ended_at TEXT,

                FOREIGN KEY(quote_id) REFERENCES quotes(id)
            );

            CREATE TABLE IF NOT EXISTS contract_meter_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_id INTEGER NOT NULL,
                reading_date TEXT NOT NULL,
                engine_hours REAL NOT NULL,
                source TEXT DEFAULT 'manual',
                contract_intervention_id INTEGER,
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(contract_id) REFERENCES contracts(id)
            );

            CREATE TABLE IF NOT EXISTS contract_interventions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_id INTEGER NOT NULL,
                intervention_type TEXT,
                reference_engine_hours REAL,
                planned_engine_hours REAL,
                planned_date TEXT,
                actual_engine_hours REAL,
                actual_date TEXT,
                status TEXT DEFAULT 'planned',
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(contract_id) REFERENCES contracts(id)
            );

            CREATE TABLE IF NOT EXISTS contract_billing_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_id INTEGER NOT NULL,
                event_key TEXT NOT NULL,
                billing_type TEXT NOT NULL,
                due_date TEXT NOT NULL,
                source_intervention_id INTEGER,
                status TEXT DEFAULT 'planned',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                UNIQUE(contract_id, event_key),

                FOREIGN KEY(contract_id)
                    REFERENCES contracts(id),

                FOREIGN KEY(source_intervention_id)
                    REFERENCES contract_interventions(id)
            );


            CREATE TABLE IF NOT EXISTS contract_delivery_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                profile_key TEXT NOT NULL,
                profile_name TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                UNIQUE(company_id, profile_key)
            );

            CREATE TABLE IF NOT EXISTS contract_delivery_recipients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                recipient_name TEXT,
                email TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                attach_ics INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                UNIQUE(profile_id, email),

                FOREIGN KEY(profile_id)
                    REFERENCES contract_delivery_profiles(id)
            );


            CREATE TABLE IF NOT EXISTS contract_delivery_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                rule_key TEXT NOT NULL,
                event_type TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                trigger_value REAL,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                UNIQUE(profile_id, rule_key),

                FOREIGN KEY(profile_id)
                    REFERENCES contract_delivery_profiles(id)
            );

            CREATE TABLE IF NOT EXISTS contract_delivery_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                profile_id INTEGER NOT NULL,
                recipient_id INTEGER,
                rule_id INTEGER,
                event_key TEXT NOT NULL,
                event_uid TEXT NOT NULL,
                event_revision INTEGER DEFAULT 0,
                event_date TEXT,
                subject TEXT,
                status TEXT NOT NULL,
                sent_at TEXT,
                error_message TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                UNIQUE(
                    recipient_id,
                    rule_id,
                    event_key,
                    event_revision
                ),

                FOREIGN KEY(profile_id)
                    REFERENCES contract_delivery_profiles(id),

                FOREIGN KEY(recipient_id)
                    REFERENCES contract_delivery_recipients(id),

                FOREIGN KEY(rule_id)
                    REFERENCES contract_delivery_rules(id)
            );


            CREATE TABLE IF NOT EXISTS contract_intervention_parts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_intervention_id INTEGER NOT NULL,
                part_number TEXT,
                description TEXT,
                planned_quantity REAL DEFAULT 0,
                actual_quantity REAL DEFAULT 0,
                source TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(contract_intervention_id)
                    REFERENCES contract_interventions(id)
            );
            """
        )

        delivery_log_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(contract_delivery_log)"
            ).fetchall()
        }

        if "event_date" not in delivery_log_columns:
            conn.execute(
                """
                ALTER TABLE contract_delivery_log
                ADD COLUMN event_date TEXT
                """
            )

        conn.commit()


if __name__ == "__main__":
    init_db()