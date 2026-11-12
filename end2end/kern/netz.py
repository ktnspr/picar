"""
netz.py – Das neuronale Netz: Kamerabild rein, Lenkwinkel raus.

Der Aufbau ist an NVIDIAs „PilotNet“ angelehnt (das Netz, mit dem NVIDIA 2016 ein
echtes Auto End-to-End fahren ließ), aber stark verkleinert, damit der Raspberry Pi
es in 1–2 Minuten trainieren kann:

    Bild 3 × 48 × 160 (Farbkanäle × Höhe × Breite)
      → 4 Faltungsschichten: erkennen Kanten, dann Linienstücke, dann den Linienverlauf
      → 3 vollständig verbundene Schichten: entscheiden daraus den Lenkwinkel
    Lenkwinkel (eine Zahl von -1 = ganz links bis 1 = ganz rechts)

Drei Varianten – benannt danach, was das Netz bekommt:
    einzelbild              nur das Kamerabild (feste Kamera)
    bild_und_schwenkwinkel  Kamerabild + Schwenkwinkel der aktiven Kamera. Der Winkel wird
                            hinter den Faltungsschichten als zusätzliche Zahl eingespeist: Die
                            Faltungen sehen, WO die Linie im Bild liegt, der Schwenkwinkel sagt,
                            wohin die Kamera dabei schaut.
    bildfolge               das aktuelle Kamerabild und die Bilder der letzten 4 Sekunden
                            (feste Kamera). So kann sich das Netz „merken“, auf welcher Seite die
                            Linie aus dem Bild verschwunden ist. Aufbau: siehe BildfolgeNetz unten.
"""

import numpy as np
import torch
import torch.nn as nn

from .konstanten import LENKUNG_MAX, NETZ_BREITE, NETZ_HOEHE

SCHWENK_SKALA = 90.0   # Schwenkwinkel (Grad) wird durch 90 geteilt → etwa −1 bis 1 wie die anderen Werte

# Die Varianten des Netzes (so stehen sie auch im Steckbrief jedes Modells)
EINZELBILD = "einzelbild"
BILD_UND_SCHWENKWINKEL = "bild_und_schwenkwinkel"
BILDFOLGE = "bildfolge"

MERKMALE = 64       # so viele Zahlen rechnet das Einzelbild-Netz aus jedem Bild (seine erste Dense-Schicht)
GRU_ZUSTAND = 32    # so viele Zahlen umfasst das Gedächtnis der GRU


def moegliche_varianten(kamera_modus):
    """Welche Varianten passen zu Fahrten mit diesem Kameramodus? Die erste ist der Standard."""
    return [BILD_UND_SCHWENKWINKEL] if kamera_modus == "aktiv" else [EINZELBILD, BILDFOLGE]


def netz_fuer(variante):
    """Ein frisches (untrainiertes) Netz für diese Variante."""
    if variante == BILDFOLGE:
        return BildfolgeNetz()
    return PilotNetKlein(mit_schwenkwinkel=variante == BILD_UND_SCHWENKWINKEL)


def architektur(variante):
    """Kurzbeschreibung des Aufbaus für den Steckbrief."""
    text = "PilotNet-klein (4 Faltungs- und 3 Dense-Schichten)"
    if variante == BILDFOLGE:
        text += f" als Auge, dazu GRU ({GRU_ZUSTAND} Zahlen Gedächtnis)"
    return text


class PilotNetKlein(nn.Module):
    def __init__(self, mit_schwenkwinkel=False):
        super().__init__()
        self.mit_schwenkwinkel = mit_schwenkwinkel   # True = Variante „Bild und Schwenkwinkel“
        self.faltungen = nn.Sequential(
            # Faltung: ein kleines Fenster (z. B. 5×5 Pixel) wandert über das Bild und sucht Muster.
            # stride=2 heißt: das Fenster springt 2 Pixel weiter – das Bild wird dabei halb so groß.
            nn.Conv2d(3, 12, kernel_size=5, stride=2), nn.ELU(),    # → 12 × 22 × 78
            nn.Conv2d(12, 18, kernel_size=5, stride=2), nn.ELU(),   # → 18 ×  9 × 37
            nn.Conv2d(18, 24, kernel_size=5, stride=2), nn.ELU(),   # → 24 ×  3 × 17
            nn.Conv2d(24, 32, kernel_size=3), nn.ELU(),             # → 32 ×  1 × 15
            nn.Flatten(),                                           # → 480 Zahlen
        )
        self.entscheidung = nn.Sequential(
            nn.Dropout(0.3),        # beim Training zufällig 30 % abschalten → lernt robuster
            nn.Linear(480 + (1 if mit_schwenkwinkel else 0), 64), nn.ELU(),
            nn.Linear(64, 16), nn.ELU(),
            nn.Linear(16, 1),
        )

    def forward(self, x, schwenken=None):
        merkmale = self.faltungen(x)
        if not self.mit_schwenkwinkel:
            return self.entscheidung(merkmale)
        # Bild und Schwenkwinkel: erst Dropout auf die Bildmerkmale, dann den Schwenkwinkel anhängen
        merkmale = self.entscheidung[0](merkmale)
        merkmale = torch.cat([merkmale, schwenken.reshape(-1, 1) / SCHWENK_SKALA], dim=1)
        return self.entscheidung[1:](merkmale)

    def merkmale(self, x):
        """Die 64 Merkmale, aus denen das Netz den Lenkwinkel bestimmt (nur Einzelbild).
        Das Netz der Variante „Bildfolge“ benutzt sie als Eingabe für sein Gedächtnis."""
        return self.entscheidung[1:3](self.faltungen(x))   # Faltungen, dann Dense-Schicht 480 → 64


class BildfolgeNetz(nn.Module):
    """Variante „Bildfolge“: ein Einzelbild-Netz als Auge und eine GRU als Gedächtnis.

    Trainiert wird in zwei Stufen (siehe training.py):
      1. Sehen:    Ein Einzelbild-Netz lernt wie gewohnt, aus einem Bild zu lenken.
                   Danach rechnet es aus jedem Bild 64 Merkmale („Linie halb links, schräg“ ...).
      2. Erinnern: Die GRU bekommt die Merkmale der Bildfolge, ältestes Bild zuerst, und
                   bestimmt am Ende den Lenkwinkel. Das Auge lernt dabei nicht mehr mit.

    Die GRU („Gated Recurrent Unit“) ist ein kleines rückgekoppeltes Netz (RNN): Sie hat einen
    inneren Zustand von 32 Zahlen, den sie Bild für Bild aktualisiert. Zwei „Tore“ entscheiden
    dabei, wie viel sie vom alten Zustand behält und wie viel sie aus dem neuen Bild übernimmt.
    """

    def __init__(self, auge=None):
        super().__init__()
        self.auge = auge if auge is not None else PilotNetKlein()
        self.auge.requires_grad_(False)          # das Auge lernt in Stufe 2 nicht mehr mit
        self.vergessen = nn.Dropout(0.2)         # beim Lernen zufällig Merkmale weglassen → robuster
        self.gedaechtnis = nn.GRU(MERKMALE, GRU_ZUSTAND, batch_first=True)
        self.entscheidung = nn.Linear(GRU_ZUSTAND, 1)

    def folge_auswerten(self, merkmale):
        """merkmale: Anzahl × Folgenlänge × 64, ältestes Bild zuerst → Lenkwinkel (−1 bis 1)."""
        zustaende, _ = self.gedaechtnis(self.vergessen(merkmale))
        return self.entscheidung(zustaende[:, -1])   # der Zustand nach dem neuesten Bild

    def forward(self, x, schwenken=None):
        """x: die ganzen Bildfolgen, Anzahl × Folgenlänge × 3 × 48 × 160."""
        anzahl, laenge = x.shape[:2]
        merkmale = self.auge.merkmale(x.flatten(0, 1)).reshape(anzahl, laenge, MERKMALE)
        return self.folge_auswerten(merkmale)


def anzahl_parameter(netz):
    return sum(p.numel() for p in netz.parameters())


def bilder_zu_tensor(bilder):
    """Bilder (Anzahl × 48 × 160 × 3, Werte 0–255) → Tensor fürs Netz (Anzahl × 3 × 48 × 160, Werte −0,5 bis 0,5)."""
    x = torch.from_numpy(np.ascontiguousarray(bilder)).float()
    return x.permute(0, 3, 1, 2) / 255.0 - 0.5


def lenkwinkel_vorhersagen(netz, netzbild, schwenken=0.0):
    """Sagt für EIN Bild (48 × 160 × 3) den Lenkwinkel in Grad vorher.
    schwenken: Schwenkwinkel der Kamera in Grad (nur bei „Bild und Schwenkwinkel“)."""
    with torch.no_grad():
        ausgabe = netz(bilder_zu_tensor(netzbild[np.newaxis]), torch.tensor([float(schwenken)]))
    return float(np.clip(ausgabe.item(), -1, 1) * LENKUNG_MAX)


def bildmerkmale(netz, netzbild):
    """Variante „Bildfolge“: die 64 Merkmale EINES Bildes (48 × 160 × 3), für das Gedächtnis."""
    with torch.no_grad():
        return netz.auge.merkmale(bilder_zu_tensor(netzbild[np.newaxis]))[0]


def lenkwinkel_aus_folge(netz, folge):
    """Variante „Bildfolge“: Lenkwinkel in Grad aus den Merkmalen der Folge (Liste, ältestes zuerst)."""
    with torch.no_grad():
        ausgabe = netz.folge_auswerten(torch.stack(folge)[np.newaxis])
    return float(np.clip(ausgabe.item(), -1, 1) * LENKUNG_MAX)


assert (NETZ_HOEHE, NETZ_BREITE) == (48, 160), "Die Schichtgrößen oben sind für 48 × 160 berechnet."
