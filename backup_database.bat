@echo off
title Dealer Quote Manager - sauvegarde base

cd /d "%~dp0"

echo.
echo ==========================================
echo Dealer Quote Manager - sauvegarde SQLite
echo ==========================================
echo.

set DB=data\dealer_quote_manager.sqlite
set BACKUP_DIR=storage\backups

if not exist "%DB%" (
    echo ERREUR : base introuvable : %DB%
    echo Lance d abord l application au moins une fois.
    pause
    exit /b 1
)

if not exist "%BACKUP_DIR%" (
    mkdir "%BACKUP_DIR%"
)

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set TS=%%i

set BACKUP_FILE=%BACKUP_DIR%\dealer_quote_manager_%TS%.sqlite

copy "%DB%" "%BACKUP_FILE%"

if errorlevel 1 (
    echo.
    echo ERREUR : sauvegarde echouee.
    pause
    exit /b 1
)

echo.
echo Sauvegarde creee :
echo %BACKUP_FILE%
echo.
pause
