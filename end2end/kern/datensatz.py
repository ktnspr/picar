"""
datensatz.py – Liest aufgenommene Fahrten von der Festplatte.

Eine Fahrt ist ein Ordner mit:
    meta.json      Beschreibung (Tempo, Kamerawinkel, Bildausschnitt ...)
    frames.csv     eine Zeile pro Bild: Dateiname, Lenkwinkel, Zeitstempel, Tempo
                   (neuere Fahrten auch: Kamera-Schwenkwinkel, Linienposition, „Linie sichtbar“,
                   „lernen“ – 0 heißt: absichtlich abgedriftet, das Bild ist nur Vorgeschichte)
    bilder/        die Kamerabilder als JPEG

Auf dem Pi liegen die Fahrten in daten/fahrten/, auf dem Mac in einem Auftragsordner.

Fahrten passen nur zusammen, wenn sie unter denselben Bedingungen aufgenommen wurden:
gleiche Geschwindigkeit, gleiche Kalibrierung, gleiche Kamerastellung, gleicher Bildausschnitt und – bei aktiver
Kamera – gleiche Regler- und Linienerkennungs-Einstellungen. Sonst würde das Netz Bilder
lernen, die beim Fahren so nie wieder vorkommen.
"""

import csv
import json
from dataclasses import dataclass

import cv2
import numpy as np

from .konstanten import LENKUNG_MAX
from .vorverarbeitung import netz_ausschnitt

BLOCK_SEKUNDEN = 3.0      # Länge eines Blocks für die Validierung (siehe training.py)
LUECKE_SEKUNDEN = 0.5     # längerer Abstand zwischen zwei Bildern = die Fahrt war unterbrochen

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


@dataclass
class Daten:
    """Alle Bilder der ausgewählten Fahrten – fürs Netz vorbereitet – und was zu jedem Bild gehört."""
    bilder: np.ndarray          # Anzahl × 48 × 160 × 3
    winkel: np.ndarray          # Lenkwinkel, −1 bis 1
    schwenkwinkel: np.ndarray   # Schwenkwinkel der Kamera (Grad)
    zeiten: np.ndarray          # Aufnahmezeitpunkt (Sekunden)
    lernen: np.ndarray          # False = absichtlich abgedriftet: nur Vorgeschichte, kein Lernziel
    bloecke: np.ndarray         # Block-Nummer (3-Sekunden-Blöcke für die Validierung)
    abschnitte: np.ndarray      # Nummer des zusammenhängenden Fahrtabschnitts (ohne Halt dazwischen)
    fahrt_nummern: np.ndarray


def daten_laden(ordner_liste, melden):
    """Lädt alle Bilder der Fahrten und bildet Blöcke von je 3 Sekunden.

    melden(text) wird ab und zu mit einer Fortschrittsmeldung aufgerufen.
    """
    spalten = {name: [] for name in ("bilder", "winkel", "schwenkwinkel", "zeiten", "lernen",
                                     "bloecke", "abschnitte", "fahrt_nummern")}
    block, abschnitt = -1, -1
    for nummer, ordner in enumerate(ordner_liste):
        meta = meta_lesen(ordner)
        ausschnitt = meta["bild"]["ausschnitt_oben"]
        fester_schwenkwinkel = float(meta["kamera"]["schwenken"])   # für ältere Fahrten ohne Spalte „schwenken“
        zeilen = frames_lesen(ordner)
        block_beginn, letzte_zeit = None, None
        for i, zeile in enumerate(zeilen):
            zeit = float(zeile["zeit"])
            # Neuer Abschnitt am Anfang jeder Fahrt und nach jeder Unterbrechung (Pause, Halt)
            unterbrochen = block_beginn is None or zeit - letzte_zeit > LUECKE_SEKUNDEN
            if unterbrochen:
                abschnitt += 1
            # Neuer Block nach 3 Sekunden – oder wenn die Fahrt unterbrochen war
            if unterbrochen or zeit - block_beginn >= BLOCK_SEKUNDEN:
                block += 1
                block_beginn = zeit
            letzte_zeit = zeit
            bild = cv2.imread(str(ordner / "bilder" / zeile["datei"]))
            spalten["bilder"].append(netz_ausschnitt(bild, ausschnitt))
            spalten["winkel"].append(float(zeile["lenkwinkel"]) / LENKUNG_MAX)
            spalten["schwenkwinkel"].append(float(zeile.get("schwenken") or fester_schwenkwinkel))
            spalten["zeiten"].append(zeit)
            spalten["lernen"].append(zeile.get("lernen", "1") != "0")   # ältere Fahrten: alles lernen
            spalten["bloecke"].append(block)
            spalten["abschnitte"].append(abschnitt)
            spalten["fahrt_nummern"].append(nummer)
            if i % 200 == 0:
                melden(f"Lade Fahrt {nummer + 1}/{len(ordner_liste)}: Bild {i}/{len(zeilen)}")
    return Daten(
        bilder=np.stack(spalten["bilder"]),
        winkel=np.array(spalten["winkel"], np.float32),
        schwenkwinkel=np.array(spalten["schwenkwinkel"], np.float32),
        zeiten=np.array(spalten["zeiten"]),
        lernen=np.array(spalten["lernen"]),
        bloecke=np.array(spalten["bloecke"]),
        abschnitte=np.array(spalten["abschnitte"]),
        fahrt_nummern=np.array(spalten["fahrt_nummern"]),
    )
