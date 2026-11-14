@echo off
rem Double-cliquez sur ce fichier pour ouvrir Vigie dans votre navigateur.
rem Gardez cette fenetre ouverte pendant l utilisation ; fermez-la pour arreter Vigie.
cd /d "%~dp0"
chcp 65001 >nul
python lancer_vigie.py interface %*
if errorlevel 1 pause
