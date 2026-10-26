"""
konfiguration.py – Dauerhaft gespeicherte Einstellungen des Pi (konfiguration.json).

Zurzeit: die externe Trainingsressource (Adresse, Port, Token). Die Datei enthält das
Token und kommt deshalb NICHT ins Git-Repository – als Vorlage dient
konfiguration.example.json.
"""

import json

from einstellungen import PROJEKT

DATEI = PROJEKT / "konfiguration.json"
STANDARD = {
    "extern": {"aktiv": False, "name": "", "host": "", "port": 8765, "token": ""},
}


def laden():
    konfig = json.loads(json.dumps(STANDARD))   # tiefe Kopie der Standardwerte
    if DATEI.exists():
        with open(DATEI, encoding="utf-8") as datei:
            gespeichert = json.load(datei)
        for bereich, werte in gespeichert.items():
            konfig.setdefault(bereich, {}).update(werte)
    return konfig


def speichern(konfig):
    with open(DATEI, "w", encoding="utf-8") as datei:
        json.dump(konfig, datei, indent=2, ensure_ascii=False)
    DATEI.chmod(0o600)   # nur der Benutzer pi darf das Token lesen
