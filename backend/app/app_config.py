from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parents[2]


def load_env_file():
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        os.environ.setdefault(key, value)


load_env_file()


def get_setting(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def get_path_setting(name: str, default: str) -> Path:
    value = get_setting(name, default)
    path = Path(value)

    if not path.is_absolute():
        path = BASE_DIR / path

    return path


APP_ENV = get_setting("APP_ENV", "local")
APP_NAME = get_setting("APP_NAME", "Dealer Quote Manager")
APP_VERSION = get_setting("APP_VERSION", "serveur-v1")
PUBLIC_URL = get_setting("PUBLIC_URL", "http://127.0.0.1:8001")
SECRET_KEY = get_setting("SECRET_KEY", "change-me-in-production")

DATABASE_URL = get_setting(
    "DATABASE_URL",
    "sqlite:///data/dealer_quote_manager.sqlite",
)

STORAGE_DIR = get_path_setting("STORAGE_DIR", "storage")
UPLOAD_DIR = get_path_setting("UPLOAD_DIR", "storage/uploads")
PDF_DIR = get_path_setting("PDF_DIR", "storage/pdf")
LOGO_DIR = get_path_setting("LOGO_DIR", "storage/logos")
CONTRACT_DIR = get_path_setting("CONTRACT_DIR", "storage/contracts")
SIGNED_DIR = get_path_setting("SIGNED_DIR", "storage/signed")
BACKUP_DIR = get_path_setting("BACKUP_DIR", "storage/backups")

FEEDBACK_DIR = get_path_setting("FEEDBACK_DIR", "data/feedback")
FEEDBACK_WEBHOOK_FILE = get_path_setting(
    "FEEDBACK_WEBHOOK_FILE",
    "data/feedback_webhook_url.txt",
)


def ensure_storage_dirs():
    for path in [
        STORAGE_DIR,
        UPLOAD_DIR,
        PDF_DIR,
        LOGO_DIR,
        CONTRACT_DIR,
        SIGNED_DIR,
        BACKUP_DIR,
        FEEDBACK_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)
