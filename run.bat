@echo off
chcp 65001 >nul
title DDCF - Django Server
echo ========================================
echo   DDCF - Pornire server Django
echo   Port: 8087
echo ========================================
echo.

:: Activare virtual environment
call .venv\Scripts\activate

:: Setare encoding UTF-8
set PYTHONUTF8=1

:: Rulare migrari (daca exista noi)
echo [*] Verificare migrari...
python manage.py migrate --run-syncdb
echo.

:: Pornire server
echo [*] Pornire server pe http://127.0.0.1:8088/
echo [*] Pentru oprire: CTRL+C
echo.
python manage.py runserver 8087
