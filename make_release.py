from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


PROJECT_DIR = Path(__file__).resolve().parent
DIST_DIR = PROJECT_DIR / "dist"
BUILD_DIR = PROJECT_DIR / "build"
RELEASE_DIR = PROJECT_DIR / "release"
APP_NAME = "Dealer Quote Manager"
APP_DIST_DIR = DIST_DIR / APP_NAME
FINAL_PACKAGE_DIR = RELEASE_DIR / APP_NAME
FINAL_ZIP = RELEASE_DIR / "Dealer_Quote_Manager_Windows_Portable.zip"


def run(command):
    print("")
    print(">", " ".join(command))
    subprocess.check_call(command, cwd=PROJECT_DIR)


def remove_path(path: Path):
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def ensure_data_structure():
    data_dir = PROJECT_DIR / "data"
    for sub in ["assets", "exports", "uploads", "examples", "imports"]:
        (data_dir / sub).mkdir(parents=True, exist_ok=True)
    (data_dir / ".gitkeep").touch(exist_ok=True)


def clean_sensitive_data_for_release(target_dir: Path):
    """
    Nettoie uniquement le package final, pas ton dossier projet.
    """
    sensitive_paths = [
        target_dir / "data" / "dealer_quote_manager.sqlite",
        target_dir / "data" / "dealer_quote_manager.sqlite3",
        target_dir / "data" / "exports",
        target_dir / "data" / "uploads",
        target_dir / "data" / "examples",
        target_dir / "data" / "imports",
    ]

    for path in sensitive_paths:
        remove_path(path)

    for sub in ["assets", "exports", "uploads", "examples", "imports"]:
        (target_dir / "data" / sub).mkdir(parents=True, exist_ok=True)

    for pattern in ["*.xlsx", "*.xlsm", "*.xls"]:
        for file in target_dir.rglob(pattern):
            remove_path(file)


def zip_folder(source_dir: Path, zip_path: Path):
    remove_path(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in source_dir.rglob("*"):
            if file.is_file():
                archive.write(file, file.relative_to(source_dir.parent))


def main():
    print("")
    print("==========================================")
    print(" Dealer Quote Manager - Package complet")
    print(" Version corrigee FastAPI / SQLite")
    print("==========================================")

    if not (PROJECT_DIR / "backend" / "app" / "main.py").exists():
        print("Erreur : backend/app/main.py introuvable.")
        print("Lance ce script depuis la racine du projet.")
        raise SystemExit(1)

    if not (PROJECT_DIR / "requirements.txt").exists():
        print("Erreur : requirements.txt introuvable.")
        raise SystemExit(1)

    ensure_data_structure()

    print("")
    print("Installation des dependances...")
    run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    run([sys.executable, "-m", "pip", "install", "pyinstaller"])

    print("")
    print("Nettoyage ancien build...")
    remove_path(BUILD_DIR)
    remove_path(DIST_DIR)
    remove_path(RELEASE_DIR)
    remove_path(PROJECT_DIR / f"{APP_NAME}.spec")

    print("")
    print("Creation de l'executable corrige...")
    pyinstaller_cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--name",
        APP_NAME,

        "--add-data",
        "backend;backend",
        "--add-data",
        "data;data",

        # FastAPI / Starlette
        "--collect-submodules",
        "fastapi",
        "--collect-submodules",
        "starlette",
        "--hidden-import",
        "fastapi.staticfiles",
        "--hidden-import",
        "starlette.staticfiles",
        "--hidden-import",
        "fastapi.templating",
        "--hidden-import",
        "starlette.templating",

        # Serveur
        "--collect-submodules",
        "uvicorn",
        "--hidden-import",
        "uvicorn.protocols.http.auto",
        "--hidden-import",
        "uvicorn.protocols.websockets.auto",
        "--hidden-import",
        "uvicorn.lifespan.on",

        # Formulaires / upload
        "--hidden-import",
        "multipart",
        "--hidden-import",
        "python_multipart",

        # Excel
        "--collect-submodules",
        "openpyxl",

        # PDF
        "--collect-submodules",
        "reportlab",
        "--collect-data",
        "reportlab",
        "--collect-submodules",
        "PIL",

        # SQLite
        "--hidden-import",
        "sqlite3",
        "--hidden-import",
        "_sqlite3",

        "run_app.py",
    ]
    run(pyinstaller_cmd)

    if not APP_DIST_DIR.exists():
        print("Erreur : le dossier dist final n'a pas ete cree.")
        raise SystemExit(1)

    print("")
    print("Creation du package final...")
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copytree(APP_DIST_DIR, FINAL_PACKAGE_DIR)

    clean_sensitive_data_for_release(FINAL_PACKAGE_DIR)

    readme = FINAL_PACKAGE_DIR / "LIRE_MOI.txt"
    readme.write_text(
        """Dealer Quote Manager - Version Windows portable

1. Ouvrir le dossier.
2. Double-cliquer sur :
   Dealer Quote Manager.exe

Le logiciel ouvre automatiquement le navigateur sur :
http://127.0.0.1:8000

Important :
- Ne pas sortir l'exe seul du dossier.
- Transmettre tout le dossier complet.
- Les PDF generes seront dans le dossier data/exports.
- Le logo Gwen Service peut etre place dans data/assets/gwen_service_logo.png.

Pour fermer le logiciel :
- fermer la fenetre noire Dealer Quote Manager.
""",
        encoding="utf-8",
    )

    zip_folder(FINAL_PACKAGE_DIR, FINAL_ZIP)

    print("")
    print("==========================================")
    print(" Package termine")
    print("==========================================")
    print("")
    print("Dossier final :")
    print(FINAL_PACKAGE_DIR)
    print("")
    print("ZIP final a transmettre :")
    print(FINAL_ZIP)
    print("")


if __name__ == "__main__":
    main()
