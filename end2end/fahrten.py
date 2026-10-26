"""
fahrten.py – Speichert die aufgenommenen Fahrten und verwaltet sie.

Jede Fahrt bekommt einen eigenen Ordner, benannt nach ihrem Startzeitpunkt:

    daten/fahrten/2026-10-26_14-03-12/
        meta.json      Beschreibung der Fahrt: Anzeigename, Tempo, Kamerawinkel, Bildparameter ...
        frames.csv     eine Zeile pro Bild: Dateiname, Lenkwinkel, Zeitstempel, Tempo
        bilder/        die Kamerabilder als JPEG (000001.jpg, 000002.jpg, ...)

Der Ordnername ändert sich nie. Umbenennen ändert nur den Anzeigenamen in meta.json.
"""

import csv
import json
import shutil
import threading
import time
from datetime import datetime

import cv2

from einstellungen import AUFNAHME_RATE, FAHRTEN, JPEG_QUALITAET, KAMERA_BREITE, KAMERA_HOEHE


def meta_lesen(ordner):
    with open(ordner / "meta.json", encoding="utf-8") as datei:
        return json.load(datei)


def meta_schreiben(ordner, meta):
    with open(ordner / "meta.json", "w", encoding="utf-8") as datei:
        json.dump(meta, datei, indent=2, ensure_ascii=False)


def fahrt_ordner(fahrt_id):
    """Der Ordner zu einer Fahrt – nur, wenn es diese Fahrt wirklich gibt."""
    ordner = FAHRTEN / fahrt_id
    # Schutz: fahrt_id darf nur ein Ordnername sein, kein Pfad wie "../../etwas"
    if ordner.parent != FAHRTEN or not (ordner / "meta.json").exists():
        raise ValueError(f"Unbekannte Fahrt: {fahrt_id}")
    return ordner


def alle_fahrten():
    """Liste aller Fahrten, neueste zuerst."""
    if not FAHRTEN.exists():
        return []
    fahrten = []
    for ordner in sorted(FAHRTEN.iterdir(), reverse=True):
        if (ordner / "meta.json").exists():
            meta = meta_lesen(ordner)
            meta["id"] = ordner.name
            fahrten.append(meta)
    return fahrten


def umbenennen(fahrt_id, neuer_name):
    ordner = fahrt_ordner(fahrt_id)
    meta = meta_lesen(ordner)
    meta["anzeigename"] = neuer_name.strip() or fahrt_id
    meta_schreiben(ordner, meta)


def loeschen(fahrt_id):
    shutil.rmtree(fahrt_ordner(fahrt_id))


def vorschaubild(fahrt_id):
    """Pfad zu einem Bild aus der Mitte der Fahrt (oder None, wenn sie leer ist)."""
    bilder = sorted((fahrt_ordner(fahrt_id) / "bilder").glob("*.jpg"))
    return bilder[len(bilder) // 2] if bilder else None


def frames_lesen(fahrt_id):
    """Alle Zeilen aus frames.csv als Liste von Dictionaries."""
    with open(fahrt_ordner(fahrt_id) / "frames.csv", newline="") as datei:
        return list(csv.DictReader(datei))


class Aufnahme:
    """Nimmt eine Fahrt auf: speichert Bilder mit Lenkwinkel und Zeitstempel."""

    def __init__(self):
        self.laeuft = False
        self.pausiert = False
        self.ordner = None
        self.anzahl = 0
        self._fahrzeit = 0.0
        self._letztes_bild = 0.0
        self._csv_datei = None
        self._sperre = threading.Lock()

    def starten(self, tempo, schwenken, neigen, ausschnitt_oben):
        with self._sperre:
            if self.laeuft:
                return
            name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            self.ordner = FAHRTEN / name
            (self.ordner / "bilder").mkdir(parents=True)
            self.meta = {
                "anzeigename": name,
                "erstellt": datetime.now().isoformat(timespec="seconds"),
                "tempo": tempo,                       # wird am Ende zum Durchschnitt
                "kamera": {"schwenken": schwenken, "neigen": neigen},
                "bild": {
                    "breite": KAMERA_BREITE,
                    "hoehe": KAMERA_HOEHE,
                    "ausschnitt_oben": ausschnitt_oben,   # ab welcher Bildhöhe das Netz das Bild sieht
                    "jpeg_qualitaet": JPEG_QUALITAET,
                    "aufnahme_rate": AUFNAHME_RATE,
                },
                "frames": 0,
                "dauer_s": 0.0,
            }
            meta_schreiben(self.ordner, self.meta)
            self._csv_datei = open(self.ordner / "frames.csv", "w", newline="")
            self._csv = csv.writer(self._csv_datei)
            self._csv.writerow(["datei", "lenkwinkel", "zeit", "tempo"])
            self._tempo_summe = 0
            self._fahrzeit = 0.0
            self._letzte_zeit = None
            self.anzahl = 0
            self.pausiert = False
            self.laeuft = True

    def pause_umschalten(self):
        if self.laeuft:
            self.pausiert = not self.pausiert

    def bild_speichern(self, bild, lenkwinkel, tempo):
        """Speichert ein Bild – höchstens AUFNAHME_RATE-mal pro Sekunde."""
        jetzt = time.time()
        if jetzt - self._letztes_bild < 1 / AUFNAHME_RATE * 0.9:   # kleine Toleranz für den Kameratakt
            return
        with self._sperre:
            if not self.laeuft or self.pausiert:
                return
            self._letztes_bild = jetzt
            self.anzahl += 1
            dateiname = f"{self.anzahl:06d}.jpg"
            cv2.imwrite(str(self.ordner / "bilder" / dateiname), bild,
                        [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITAET])
            self._csv.writerow([dateiname, round(lenkwinkel, 2), round(jetzt, 3), tempo])
            self._tempo_summe += tempo
            # Fahrzeit: nur Abstände zwischen direkt aufeinanderfolgenden Bildern zählen,
            # damit Pausen und Stillstand nicht mitgerechnet werden.
            if self._letzte_zeit is not None and jetzt - self._letzte_zeit < 0.5:
                self._fahrzeit += jetzt - self._letzte_zeit
            self._letzte_zeit = jetzt

    def dauer(self):
        """Reine Fahrzeit in Sekunden."""
        return self._fahrzeit

    def stoppen(self):
        with self._sperre:
            if not self.laeuft:
                return
            self.laeuft = False
            self.pausiert = False
            self._csv_datei.close()
            if self.anzahl == 0:
                shutil.rmtree(self.ordner)   # leere Fahrten nicht aufheben
                return
            self.meta["frames"] = self.anzahl
            self.meta["dauer_s"] = round(self.dauer(), 1)
            self.meta["tempo"] = round(self._tempo_summe / self.anzahl)
            meta_schreiben(self.ordner, self.meta)
