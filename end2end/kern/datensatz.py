"""
datensatz.py – Liest aufgenommene Fahrten von der Festplatte.

Eine Fahrt ist ein Ordner mit:
    meta.json      Beschreibung (Tempo, Kamerawinkel, Bildausschnitt ...)
    frames.csv     eine Zeile pro Bild: Dateiname, Lenkwinkel, Zeitstempel, Tempo
    bilder/        die Kamerabilder als JPEG

Auf dem Pi liegen die Fahrten in daten/fahrten/, auf dem Mac in einem Auftragsordner.
"""

import csv
import json

import cv2
import numpy as np

from .konstanten import LENKUNG_MAX
from .vorverarbeitung import netz_ausschnitt

BLOCK_SEKUNDEN = 3.0      # Länge eines Blocks für die Validierung (siehe training.py)


def meta_lesen(ordner):
    with open(ordner / "meta.json", encoding="utf-8") as datei:
        return json.load(datei)


def frames_lesen(ordner):
    """Alle Zeilen aus frames.csv als Liste von Dictionaries."""
    with open(ordner / "frames.csv", newline="") as datei:
        return list(csv.DictReader(datei))


def daten_laden(ordner_liste, melden):
    """Lädt alle Bilder der Fahrten und bildet Blöcke von je 3 Sekunden.

    Ergebnis: Bilder (fürs Netz vorbereitet), Lenkwinkel (−1 bis 1), Block-Nummer, Fahrt-Nummer.
    melden(text) wird ab und zu mit einer Fortschrittsmeldung aufgerufen.
    """
    bilder, winkel, bloecke, fahrt_nummern = [], [], [], []
    block = -1
    for nummer, ordner in enumerate(ordner_liste):
        ausschnitt = meta_lesen(ordner)["bild"]["ausschnitt_oben"]
        zeilen = frames_lesen(ordner)
        block_beginn, letzte_zeit = None, None
        for i, zeile in enumerate(zeilen):
            zeit = float(zeile["zeit"])
            # Neuer Block nach 3 Sekunden – oder wenn die Fahrt unterbrochen war
            if block_beginn is None or zeit - block_beginn >= BLOCK_SEKUNDEN or zeit - letzte_zeit > 0.5:
                block += 1
                block_beginn = zeit
            letzte_zeit = zeit
            bild = cv2.imread(str(ordner / "bilder" / zeile["datei"]))
            bilder.append(netz_ausschnitt(bild, ausschnitt))
            winkel.append(float(zeile["lenkwinkel"]) / LENKUNG_MAX)
            bloecke.append(block)
            fahrt_nummern.append(nummer)
            if i % 200 == 0:
                melden(f"Lade Fahrt {nummer + 1}/{len(ordner_liste)}: Bild {i}/{len(zeilen)}")
    return (np.stack(bilder), np.array(winkel, np.float32),
            np.array(bloecke), np.array(fahrt_nummern))
