#!/bin/bash
# Startet das End-to-End-Projekt mit der eigenen Python-Umgebung (.venv).
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
    echo "Die Python-Umgebung fehlt. Bitte zuerst ./einrichten.sh ausführen."
    exit 1
fi
exec .venv/bin/python app.py
