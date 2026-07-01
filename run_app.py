from pathlib import Path
import os
import sys
import threading
import time
import traceback
import webbrowser

import uvicorn


def resource_path(relative_path: str) -> Path:
    """
    Compatible Python normal + PyInstaller.
    """
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative_path
    return Path(__file__).resolve().parent / relative_path


APP_DIR = resource_path("backend") / "app"


def open_browser():
    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:8000")


def main():
    try:
        if not APP_DIR.exists():
            print("Erreur : dossier backend/app introuvable.")
            print("Dossier cherche :", APP_DIR)
            input("Appuie sur Entree pour fermer...")
            raise SystemExit(1)

        os.chdir(APP_DIR)
        sys.path.insert(0, str(APP_DIR))

        # Import direct pour eviter certains problemes de resolution PyInstaller.
        import main as app_main

        try:
            from database import init_db
            init_db()
        except Exception as exc:
            print("Attention : initialisation base impossible :", exc)

        threading.Thread(target=open_browser, daemon=True).start()

        print("Dealer Quote Manager")
        print("Interface : http://127.0.0.1:8000")
        print("Ferme cette fenetre pour arreter le logiciel.")
        print("")

        uvicorn.run(
            app_main.app,
            host="127.0.0.1",
            port=8000,
            reload=False,
            access_log=False,
        )

    except Exception:
        print("")
        print("ERREUR AU DEMARRAGE")
        print("===================")
        traceback.print_exc()
        print("")
        input("Appuie sur Entree pour fermer...")
        raise


if __name__ == "__main__":
    main()
