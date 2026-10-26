"""
netz.py – Das neuronale Netz: Kamerabild rein, Lenkwinkel raus.

Der Aufbau ist an NVIDIAs „PilotNet“ angelehnt (das Netz, mit dem NVIDIA 2016 ein
echtes Auto End-to-End fahren ließ), aber stark verkleinert, damit der Raspberry Pi
es in 1–2 Minuten trainieren kann:

    Bild 3 × 48 × 160 (Farbkanäle × Höhe × Breite)
      → 4 Faltungsschichten: erkennen Kanten, dann Linienstücke, dann den Linienverlauf
      → 3 vollständig verbundene Schichten: entscheiden daraus den Lenkwinkel
    Lenkwinkel (eine Zahl von -1 = ganz links bis 1 = ganz rechts)
"""

import numpy as np
import torch
import torch.nn as nn

from .konstanten import LENKUNG_MAX, NETZ_BREITE, NETZ_HOEHE

ARCHITEKTUR = "PilotNet-klein (4 Faltungs- und 3 Dense-Schichten)"


class PilotNetKlein(nn.Module):
    def __init__(self):
        super().__init__()
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
            nn.Linear(480, 64), nn.ELU(),
            nn.Linear(64, 16), nn.ELU(),
            nn.Linear(16, 1),
        )

    def forward(self, x):
        return self.entscheidung(self.faltungen(x))


def anzahl_parameter(netz):
    return sum(p.numel() for p in netz.parameters())


def bilder_zu_tensor(bilder):
    """Bilder (Anzahl × 48 × 160 × 3, Werte 0–255) → Tensor fürs Netz (Anzahl × 3 × 48 × 160, Werte −0,5 bis 0,5)."""
    x = torch.from_numpy(np.ascontiguousarray(bilder)).float()
    return x.permute(0, 3, 1, 2) / 255.0 - 0.5


def lenkwinkel_vorhersagen(netz, netzbild):
    """Sagt für EIN Bild (48 × 160 × 3) den Lenkwinkel in Grad vorher."""
    with torch.no_grad():
        ausgabe = netz(bilder_zu_tensor(netzbild[np.newaxis]))
    return float(np.clip(ausgabe.item(), -1, 1) * LENKUNG_MAX)


assert (NETZ_HOEHE, NETZ_BREITE) == (48, 160), "Die Schichtgrößen oben sind für 48 × 160 berechnet."
