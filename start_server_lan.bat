@echo off
title Dealer Quote Manager - serveur reseau local

cd /d "%~dp0"

echo.
echo ==========================================
echo Dealer Quote Manager - serveur LAN
echo ==========================================
echo.
echo Ce mode rend l application accessible depuis le reseau local.
echo.
echo Adresse locale du serveur sur ce PC :
ipconfig | findstr /i "IPv4"
echo.
echo Depuis un autre PC du reseau, ouvrir :
echo http://ADRESSE_IPV4_DU_PC:8001
echo.
echo Exemple avec ton PC actuel :
echo http://192.168.86.22:8001
echo.
if not exist "requirements.txt" (
    echo ERREUR : requirements.txt introuvable.
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
echo Lancement serveur reseau local :
echo http://0.0.0.0:8001
echo.
echo Pour acceder depuis un autre PC : utiliser l adresse IPv4 affichee plus haut.
echo Pour arreter le serveur : CTRL + C
echo.
cd backend\app
python -m uvicorn main:app --host 0.0.0.0 --port 8001 --reload

echo.
echo Le serveur LAN s est arrete.
echo Code retour : %ERRORLEVEL%
echo.
pause
