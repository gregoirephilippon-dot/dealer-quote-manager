@echo off
title Dealer Quote Manager - Ancien package Windows

cd /d "%~dp0"

echo.
echo ==========================================
echo ATTENTION - ancien packaging Windows EXE
echo ==========================================
echo.
echo Ce script correspond a l'ancien mode package portable.
echo Le mode serveur-v1 actuel se lance avec :
echo.
echo start_server.bat
echo.
echo Ne pas utiliser ce script pour le serveur-v1 sauf besoin de reconstruire un ancien EXE.
echo.
pause

echo.
echo Creation du package complet Windows legacy...
echo.

python make_release.py

echo.
pause
