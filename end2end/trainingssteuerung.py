"""
trainingssteuerung.py – Startet das Training (auf dem Pi oder extern) und speichert danach das Modell.

Das eigentliche Training steht im gemeinsamen Kern (kern/training.py). Diese Datei
kümmert sich um das Drumherum auf dem Pi:
  - entscheiden, wo trainiert wird: auf dem Pi oder auf einem externen Rechner (extern.py)
  - ist der externe Rechner nicht erreichbar: auf dem Pi trainieren und das deutlich sagen
  - das fertige Modell speichern und im Steckbrief festhalten, wo, worauf und wie lange trainiert wurde
"""

import socket
import time

import extern
import fahrten
import konfiguration
import modelle
from kern.training import Training
from kern.version import code_version

THREADS = 3   # Rechenkerne fürs Training auf dem Pi (einer bleibt frei für die Weboberfläche)


class Trainingssteuerung:
    def __init__(self):
        self.aktiv = Training(geraet="cpu", threads=THREADS)   # das laufende (oder letzte) Training
        self.ort = "pi"         # "pi" oder "extern"
        self.hinweis = None     # z. B. „Externe Ressource nicht erreichbar – trainiere auf dem Pi“
        self.ergebnis = None    # nach dem Training: ID des neuen Modells
        self._startzeit = None

    @property
    def laeuft(self):
        return self.aktiv.laeuft

    def status(self):
        return self.aktiv.status() | {"ergebnis": self.ergebnis, "ort": self.ort, "hinweis": self.hinweis}

    def starten(self, fahrt_ids, gruendlich, ort="pi"):
        if self.laeuft:
            raise ValueError("Es läuft bereits ein Training.")
        ordner = [fahrten.fahrt_ordner(fahrt_id) for fahrt_id in fahrt_ids]   # prüft, ob es sie gibt
        if not ordner:
            raise ValueError("Bitte mindestens eine Fahrt auswählen.")
        self.ergebnis, self.hinweis, self._startzeit = None, None, time.time()

        if ort == "extern":
            einstellung = konfiguration.laden()["extern"]
            if not einstellung["aktiv"]:
                raise ValueError("Die externe Trainingsressource ist nicht eingeschaltet (siehe unten).")
            externes = extern.ExternesTraining(einstellung, code_version())
            try:
                externes.starten(ordner, gruendlich, bei_ende=self._speichern)
                self.aktiv, self.ort = externes, "extern"
                return
            except extern.Verbindungsfehler as fehler:
                # Rückfall: dann eben auf dem Pi
                name = einstellung["name"] or einstellung["host"]
                self.hinweis = f"Externe Trainingsressource „{name}“ nicht erreichbar ({fehler}) – trainiere auf dem Pi."

        self.aktiv, self.ort = Training(geraet="cpu", threads=THREADS), "pi"
        self.aktiv.starten(ordner, gruendlich, bei_ende=self._speichern)

    def beenden(self):
        self.aktiv.beenden()

    def abbrechen(self):
        self.aktiv.abbrechen()

    def _speichern(self, training):
        """Wird am Ende des Trainings aufgerufen: Modell samt Steckbrief speichern."""
        meta = training.ergebnis_meta
        if self.ort == "extern":
            gewichte = training.ergebnis_gewichte
            trainiert_auf = {
                "ort": "extern",
                "name": training.info["name"],
                "host": training.konfig["host"],
                "code_version": training.info["version"],
                "pi_version": code_version(),
            }
        else:
            gewichte = training.ergebnis_netz.state_dict()
            trainiert_auf = {"ort": "Pi", "name": socket.gethostname()}
        trainiert_auf |= {
            "geraet": meta["geraet"],
            "dauer_s": meta["trainingsdauer_s"],                          # reine Trainingszeit
            "gesamtdauer_s": round(time.time() - self._startzeit, 1),     # mit Übertragung
        }
        if self.hinweis:
            trainiert_auf["hinweis"] = self.hinweis
        self.ergebnis = modelle.speichern(gewichte, meta | {"trainiert_auf": trainiert_auf})
