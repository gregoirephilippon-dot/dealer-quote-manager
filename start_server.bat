@echo off
title Dealer Quote Manager - serveur local

cd /d "%~dp0"

echo.
echo ==========================================
echo Dealer Quote Manager - serveur-v1
echo ==========================================
echo Dossier projet :
echo %cd%
echo ==========================================
echo.

if not exist "requirements.txt" (
    echo ERREUR : requirements.txt introuvable.
    echo Lance ce fichier depuis le dossier dealer-quote-manager.
    pause
    exit /b 1
)

if exist ".venv\Scripts\activate.bat" (
    echo Activation environnement virtuel .venv...
    call ".venv\Scripts\activate.bat"
) else (
    echo Environnement virtuel .venv introuvable.
    echo Creation de .venv...
    python -m venv .venv
    call ".venv\Scripts\activate.bat"
    pip install -r requirements.txt
)

echo.
echo Verification Python...
python --version

echo.
echo Verification Uvicorn...
python -m uvicorn --version

echo.
echo Lancement serveur local :
echo http://127.0.0.1:8001
echo.
echo Si le serveur demarre correctement, cette fenetre doit rester ouverte.
echo Pour arreter le serveur : CTRL + C
echo.

cd backend\app

python -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload

echo.
echo ==========================================
echo Le serveur s'est arrete.
echo Code retour : %ERRORLEVEL%
echo ==========================================
echo.
pause
