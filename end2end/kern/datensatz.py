"""
datensatz.py – Liest aufgenommene Fahrten von der Festplatte.

Eine Fahrt ist ein Ordner mit:
    meta.json      Beschreibung (Tempo, Kamerawinkel, Bildausschnitt ...)
    frames.csv     eine Zeile pro Bild: Dateiname, Lenkwinkel, Zeitstempel, Tempo
                   (neuere Fahrten auch: Kamera-Schwenkwinkel, Linienposition, „Linie sichtbar“)
    bilder/        die Kamerabilder als JPEG

Auf dem Pi liegen die Fahrten in daten/fahrten/, auf dem Mac in einem Auftragsordner.

Fahrten passen nur zusammen, wenn sie unter denselben Bedingungen aufgenommen wurden:
gleiche Geschwindigkeit, gleiche Kalibrierung, gleiche Kamerastellung, gleicher Bildausschnitt und – bei aktiver
Kamera – gleiche Regler- und Linienerkennungs-Einstellungen. Sonst würde das Netz Bilder
lernen, die beim Fahren so nie wieder vorkommen.
"""

import csv
import json

import cv2
import numpy as np

from .konstanten import LENKUNG_MAX
from .vorverarbeitung import netz_ausschnitt

BLOCK_SEKUNDEN = 3.0      # Länge eines Blocks für die Validierung (siehe training.py)

# Einstellungen der Linienerkennung, die nur bei bestimmten Verfahren wirken
NUR_BEI_VERFAHREN = {"farbe_bgr": ("farbe",), "toleranz": ("farbe",), "helligkeit_min": ("hell",),
                     "kontrast_min": ("hell", "dunkel")}

# Namen der Aufnahme-Einstellungen für Meldungen
NAMEN = {
    "kamera_modus": "Kameramodus",
    "tempo": "Geschwindigkeit",
    "kamera_neigen": "Kamera-Neigung",
    "kamera_schwenken": "Kamera-Schwenkwinkel",
    "ausschnitt_oben": "Bildausschnitt",
    "kalibrierung": "Kalibrierung",
    "regler": "Kameraregelung",
    "linienerkennung": "Linienerkennung",
}


def meta_lesen(ordner):
    with open(ordner / "meta.json", encoding="utf-8") as datei:
        return json.load(datei)


def frames_lesen(ordner):
    """Alle Zeilen aus frames.csv als Liste von Dictionaries."""
    with open(ordner / "frames.csv", newline="") as datei:
        return list(csv.DictReader(datei))


def aufnahme_einstellungen(meta):
    """Alle Einstellungen, unter denen eine Fahrt aufgenommen wurde – das, was gleich sein muss.

    Ältere Fahrten kennen manches noch nicht: Kameramodus fehlt → „fest“,
    Kalibrierung fehlt → None („unbekannt“).
    """
    modus = meta.get("kamera_modus", "fest")
    einstellungen = {
        "kamera_modus": modus,
        "tempo": int(round(meta["tempo"])),          # Prozent; bleibt während einer Aufnahme fest
        "kamera_neigen": float(meta["kamera"]["neigen"]),
        "ausschnitt_oben": float(meta["bild"]["ausschnitt_oben"]),
        "kalibrierung": meta.get("kalibrierung"),
    }
    if modus == "fest":
        einstellungen["kamera_schwenken"] = float(meta["kamera"]["schwenken"])
    else:   # aktive Kamera: Wie sie geschwenkt wurde, gehört zu den Daten
        einstellungen["regler"] = meta.get("regler")
        linie = meta.get("linienerkennung")
        if linie is not None:   # nur vergleichen, was beim gewählten Verfahren auch wirkt
            linie = {k: v for k, v in linie.items() if linie.get("modus") in NUR_BEI_VERFAHREN.get(k, (linie.get("modus"),))}
        einstellungen["linienerkennung"] = linie
    return einstellungen


def _als_text(wert):
    if wert is None:
        return "unbekannt"
    if isinstance(wert, dict):
        return ", ".join(f"{k} {_als_text(v)}" for k, v in sorted(wert.items()))
    if isinstance(wert, float):
        return f"{wert:g}"
    return str(wert)


def einheitlichkeit_pruefen(metas):
    """Prüft, ob Fahrten zusammenpassen. Ergebnis: Liste von Meldungen (leer = alles passt)."""
    alle = [(meta["anzeigename"], aufnahme_einstellungen(meta)) for meta in metas]
    meldungen = []
    modus_verschieden = len({e["kamera_modus"] for _, e in alle}) > 1
    for schluessel, name in NAMEN.items():
        if modus_verschieden and schluessel in ("kamera_schwenken", "regler", "linienerkennung"):
            continue   # Folgefehler – der Kameramodus wird schon gemeldet
        werte = [(fahrt, e.get(schluessel)) for fahrt, e in alle]
        if len({json.dumps(w, sort_keys=True) for _, w in werte}) <= 1:
            continue   # bei allen gleich
        if all(isinstance(w, dict) for _, w in werte):
            # Bei Einstellungsgruppen nur die Teile nennen, die sich unterscheiden
            teile = sorted({k for _, w in werte for k in w if len({json.dumps(x.get(k)) for _, x in werte}) > 1})
            unterschiede = "; ".join(f"{k}: " + " / ".join(_als_text(w.get(k)) for _, w in werte) for k in teile)
            meldungen.append(f"{name} unterschiedlich – {unterschiede}")
        else:
            meldungen.append(f"{name} unterschiedlich – " + " · ".join(f"{fahrt}: {_als_text(w)}" for fahrt, w in werte))
    return meldungen


def daten_laden(ordner_liste, melden):
    """Lädt alle Bilder der Fahrten und bildet Blöcke von je 3 Sekunden.

    Ergebnis: Bilder (fürs Netz vorbereitet), Lenkwinkel (−1 bis 1), Schwenkwinkel der Kamera (Grad),
    Block-Nummer, Fahrt-Nummer.
    melden(text) wird ab und zu mit einer Fortschrittsmeldung aufgerufen.
    """
    bilder, winkel, schwenkwinkel, bloecke, fahrt_nummern = [], [], [], [], []
    block = -1
    for nummer, ordner in enumerate(ordner_liste):
        meta = meta_lesen(ordner)
        ausschnitt = meta["bild"]["ausschnitt_oben"]
        fester_schwenkwinkel = float(meta["kamera"]["schwenken"])   # für ältere Fahrten ohne Spalte „schwenken“
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
            schwenkwinkel.append(float(zeile.get("schwenken") or fester_schwenkwinkel))
            bloecke.append(block)
            fahrt_nummern.append(nummer)
            if i % 200 == 0:
                melden(f"Lade Fahrt {nummer + 1}/{len(ordner_liste)}: Bild {i}/{len(zeilen)}")
    return (np.stack(bilder), np.array(winkel, np.float32), np.array(schwenkwinkel, np.float32),
            np.array(bloecke), np.array(fahrt_nummern))
