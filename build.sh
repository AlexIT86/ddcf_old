#!/usr/bin/env bash
# exit on error
set -o errexit

# Instalează LibreOffice
apt-get update
apt-get install -y libreoffice

# Continuă cu pașii standard de deployment Django
python -m pip install --upgrade pip
pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate