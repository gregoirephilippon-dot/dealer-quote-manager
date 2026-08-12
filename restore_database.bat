@echo off
title Dealer Quote Manager - restauration base

cd /d "%~dp0"

echo.
echo ==========================================
echo Dealer Quote Manager - restauration SQLite
echo ==========================================
echo.

set DB=data\dealer_quote_manager.sqlite
set BACKUP_DIR=storage\backups

if not exist "%BACKUP_DIR%" (
    echo ERREUR : dossier de sauvegardes introuvable : %BACKUP_DIR%
    pause
    exit /b 1
)

echo Sauvegardes disponibles :
echo.
dir "%BACKUP_DIR%\*.sqlite" /b /o-d
echo.

set /p BACKUP_NAME=Nom exact du fichier a restaurer : 

if "%BACKUP_NAME%"=="" (
    echo Restauration annulee.
    pause
    exit /b 1
)

set BACKUP_FILE=%BACKUP_DIR%\%BACKUP_NAME%

if not exist "%BACKUP_FILE%" (
    echo ERREUR : fichier introuvable : %BACKUP_FILE%
    pause
    exit /b 1
)

echo.
echo ATTENTION : cette action va remplacer la base actuelle.
echo Base actuelle : %DB%
echo Sauvegarde choisie : %BACKUP_FILE%
echo.
set /p CONFIRM=Confirmer la restauration ? taper OUI : 

if not "%CONFIRM%"=="OUI" (
    echo Restauration annulee.
    pause
    exit /b 1
)

if not exist "data" (
    mkdir data
)

if exist "%DB%" (
    for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set TS=%%i
    copy "%DB%" "%BACKUP_DIR%\avant_restauration_%TS%.sqlite"
)

copy /Y "%BACKUP_FILE%" "%DB%"

if errorlevel 1 (
    echo.
    echo ERREUR : restauration echouee.
    pause
    exit /b 1
)

echo.
echo Restauration terminee.
echo Base restauree depuis : %BACKUP_FILE%
echo.
pause
