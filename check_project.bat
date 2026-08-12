@echo off
title Dealer Quote Manager - verification projet

cd /d "%~dp0"

echo.
echo ==========================================
echo Dealer Quote Manager - verification projet
echo ==========================================
echo.

echo --- Git status ---
git status

echo.
echo --- Scripts BAT ---
dir *.bat

echo.
echo --- Fichiers ignores par Git ---
git check-ignore .env
git check-ignore data/dealer_quote_manager.sqlite
git check-ignore storage/backups/test.sqlite

echo.
echo --- Compilation Python ---
python -m py_compile backend\app\main.py
python -m py_compile backend\app\app_config.py
python -m py_compile backend\app\database.py
python -m py_compile backend\app\server_user_model.py

echo.
echo Verification terminee.
echo.
pause
