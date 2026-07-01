@echo off
title Dealer Quote Manager - Package complet corrige
cd /d "%~dp0"

echo.
echo Creation du package complet Windows corrige...
echo.

python make_release.py

echo.
pause
