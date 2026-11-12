"""
bildfolge.py – Welche früheren Bilder sieht das Netz der Variante „Bildfolge“?

Das Netz bekommt das aktuelle Bild und die Bilder von vor 0,2 s, 0,4 s, ... 4 s – zusammen
FOLGE_LAENGE = 21 Bilder, das älteste zuerst.

Beim Training stammen die Bilder aus einer gespeicherten Fahrt (10 Bilder pro Sekunde),
beim Fahren direkt von der Kamera (30 Bilder pro Sekunde). Damit das Netz beim Fahren
dasselbe sieht wie beim Lernen, gilt beide Male dieselbe Regel (naechste_bilder):

  - Zu jedem Zeitpunkt nehmen wir das Bild, das zeitlich am nächsten liegt.
  - Reicht die Vorgeschichte nicht so weit zurück (Anfang einer Fahrt, nach einem Halt),
    nehmen wir das älteste vorhandene Bild – so, als hätte das Auto dort eine Weile gestanden.
"""

from collections import deque

import numpy as np

from .konstanten import FOLGE_ABSTAND_S, FOLGE_LAENGE


def zeitpunkte(jetzt, laenge=FOLGE_LAENGE, abstand=FOLGE_ABSTAND_S):
    """Die Zeitpunkte der Folge, ältester zuerst: jetzt − 4,0 s, jetzt − 3,8 s, ..., jetzt.
    jetzt darf auch ein Array sein – dann gibt es eine Zeile pro Zeitpunkt."""
    rueckblick = abstand * np.arange(laenge - 1, -1, -1)
    return np.asarray(jetzt)[..., np.newaxis] - rueckblick


def naechste_bilder(zeiten, ziele):
    """Zu jedem Zielzeitpunkt das Bild, das zeitlich am nächsten liegt (als Index in zeiten).

    zeiten: Aufnahmezeitpunkte der vorhandenen Bilder, aufsteigend sortiert.
    Liegt ein Ziel vor dem ersten Bild, ist das erste (älteste) Bild das nächste.
    """
    zeiten = np.asarray(zeiten)
    if len(zeiten) == 1:
        return np.zeros(np.shape(ziele), dtype=np.int64)
    rechts = np.searchsorted(zeiten, ziele).clip(1, len(zeiten) - 1)   # erstes Bild nicht vor dem Ziel
    links = rechts - 1                                                   # letztes Bild vor dem Ziel
    links_naeher = np.abs(ziele - zeiten[links]) <= np.abs(zeiten[rechts] - ziele)
    return np.where(links_naeher, links, rechts)


def fenster_bilden(zeiten, abschnitte, laenge=FOLGE_LAENGE, abstand=FOLGE_ABSTAND_S):
    """Für jedes Bild der Trainingsdaten die Bilder seiner Folge (Ergebnis: Anzahl × laenge Indizes).

    abschnitte: Nummer des zusammenhängenden Fahrtabschnitts jedes Bildes. Eine Folge reicht
    nie über einen Abschnitt hinaus – also nie in eine andere Fahrt oder über einen Halt hinweg.
    Ein Bild aus der Zukunft kommt nie in die Folge: Alle Zeitpunkte liegen vor oder auf „jetzt“.
    """
    fenster = np.empty((len(zeiten), laenge), dtype=np.int64)
    for abschnitt in np.unique(abschnitte):
        indizes = np.where(abschnitte == abschnitt)[0]
        z = zeiten[indizes]
        fenster[indizes] = indizes[naechste_bilder(z, zeitpunkte(z, laenge, abstand))]
    return fenster


class Gedaechtnis:
    """Beim Fahren: merkt sich die Merkmale der Kamerabilder der letzten gut 4 Sekunden."""

    def __init__(self, laenge=FOLGE_LAENGE, abstand=FOLGE_ABSTAND_S):
        self.laenge, self.abstand = laenge, abstand
        self._zeiten = deque()
        self._merkmale = deque()

    def hinzufuegen(self, zeit, merkmale):
        self._zeiten.append(zeit)
        self._merkmale.append(merkmale)
        # Was älter ist als der Rückblick (plus ein Bild Reserve), wird nicht mehr gebraucht
        grenze = zeit - (self.laenge - 1) * self.abstand - self.abstand
        while self._zeiten[0] < grenze:
            self._zeiten.popleft()
            self._merkmale.popleft()

    def folge(self):
        """Die Merkmale der Folge zum neuesten Bild, ältestes zuerst."""
        indizes = naechste_bilder(np.array(self._zeiten), zeitpunkte(self._zeiten[-1], self.laenge, self.abstand))
        return [self._merkmale[i] for i in indizes]
