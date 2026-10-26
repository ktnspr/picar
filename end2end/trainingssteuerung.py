"""
trainingssteuerung.py – Startet das Training und speichert danach das Modell.

Das eigentliche Training steht im gemeinsamen Kern (kern/training.py). Diese Datei
kümmert sich nur um das Drumherum auf dem Pi: Fahrten heraussuchen, das fertige
Modell speichern und im Steckbrief festhalten, wo es trainiert wurde.
"""

import socket

import fahrten
import modelle
from kern.training import Training

THREADS = 3   # Rechenkerne fürs Training auf dem Pi (einer bleibt frei für die Weboberfläche)


class Trainingssteuerung:
    def __init__(self):
        self.training = Training(geraet="cpu", threads=THREADS)
        self.ergebnis = None   # nach dem Training: ID des neuen Modells

    @property
    def laeuft(self):
        return self.training.laeuft

    def status(self):
        return self.training.status() | {"ergebnis": self.ergebnis}

    def starten(self, fahrt_ids, gruendlich):
        ordner = [fahrten.fahrt_ordner(fahrt_id) for fahrt_id in fahrt_ids]   # prüft, ob es sie gibt
        self.ergebnis = None
        self.training.starten(ordner, gruendlich, bei_ende=self._speichern)

    def beenden(self):
        self.training.beenden()

    def abbrechen(self):
        self.training.abbrechen()

    def _speichern(self, training):
        """Wird am Ende des Trainings aufgerufen: Modell samt Steckbrief speichern."""
        meta = training.ergebnis_meta | {
            "trainiert_auf": {
                "ort": "Pi",
                "name": socket.gethostname(),
                "geraet": training.ergebnis_meta["geraet"],
                "dauer_s": training.ergebnis_meta["trainingsdauer_s"],
            },
        }
        self.ergebnis = modelle.speichern(training.ergebnis_netz.state_dict(), meta)
