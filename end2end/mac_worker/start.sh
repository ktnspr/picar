#!/bin/bash
# Startet den Trainings-Dienst. Beim ersten Mal wird alles eingerichtet:
#   - Python-Umgebung .venv mit allen Paketen
#   - config.json mit einem zufälligen Token (das Token dann auf dem Pi eintragen)
# Nach einem „git pull“ werden geänderte Pakete automatisch nachinstalliert.
set -e
cd "$(dirname "$0")"

PYTHON=${PYTHON:-python3}
if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "Bitte Python 3.10 oder neuer installieren (z. B. mit: brew install python)."
    exit 1
fi

# 1. Python-Umgebung einrichten bzw. Pakete aktualisieren, wenn requirements.txt sich geändert hat
if [ ! -x .venv/bin/python ]; then
    echo "Richte die Python-Umgebung ein (einmalig, dauert ein paar Minuten) ..."
    "$PYTHON" -m venv .venv
fi
if ! cmp -s requirements.txt .venv/requirements.installiert; then
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
    cp requirements.txt .venv/requirements.installiert
fi

# 2. Konfiguration mit zufälligem Token anlegen
if [ ! -f config.json ]; then
    TOKEN=$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(24))')
    sed "s|\"token\": \".*\"|\"token\": \"$TOKEN\"|" config.example.json > config.json
    echo
    echo "config.json angelegt. Dieses Token auf dem Pi eintragen (Training → Externe Trainingsressource):"
    echo
    echo "    $TOKEN"
    echo
    echo "Den Namen des Dienstes kannst du in config.json ändern."
    echo
fi

# 3. Dienst starten
exec .venv/bin/python dienst.py
