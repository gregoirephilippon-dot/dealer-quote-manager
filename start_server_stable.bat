@echo off
setlocal

echo.
echo ==========================================
echo Dealer Quote Manager - serveur stable
echo ==========================================
echo.

cd /d "%~dp0"

echo Verification environnement Python...
where python >nul 2>nul
if errorlevel 1 (
    echo ERREUR : Python introuvable.
    echo Installe Python puis relance ce script.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Environnement virtuel .venv introuvable.
    echo Creation de .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo ERREUR : creation .venv impossible.
        pause
        exit /b 1
    )
)

echo.
echo Installation / verification dependances...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERREUR : installation dependances impossible.
    pause
    exit /b 1
)

echo.
echo Initialisation base serveur test...
".venv\Scripts\python.exe" backend\app\setup_server_test.py
if errorlevel 1 (
    echo ERREUR : initialisation serveur test impossible.
    pause
    exit /b 1
)

echo.
echo Verification port 8001...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8001" ^| findstr "LISTENING"') do (
    echo ERREUR : le port 8001 est deja utilise par le PID %%a
    echo Ferme l ancien serveur ou lance :
    echo taskkill /PID %%a /T /F
    pause
    exit /b 1
)

echo.
echo Adresse locale du serveur sur ce PC :
ipconfig | findstr /i "IPv4"

echo.
echo Lancement serveur stable :
echo http://0.0.0.0:8001
echo.
echo Depuis un autre PC du reseau :
echo http://ADRESSE_IPV4_DU_PC:8001
echo.
echo Pour arreter le serveur : CTRL + C
echo.

".venv\Scripts\python.exe" -m uvicorn main:app --app-dir backend\app --host 0.0.0.0 --port 8001

pause
