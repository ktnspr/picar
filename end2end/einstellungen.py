"""
einstellungen.py – Alle wichtigen Zahlen des Projekts an einer Stelle.

Die Werte stammen aus Messungen auf dem Raspberry Pi 5 (siehe README.md):
Die Kamera schafft 60 Bilder/s bei 320×240, das Netz rechnet ein Bild in etwa
1 ms und trainiert mit etwa 600 Bildern pro Sekunde.
"""

from pathlib import Path

# Was Pi und Mac gleich verwenden müssen, steht im gemeinsamen Kern
from kern.konstanten import LENKUNG_MAX, NETZ_BREITE, NETZ_HOEHE  # noqa: F401

# ---------- Webserver ----------
PORT = 8080

# ---------- Ordner ----------
PROJEKT = Path(__file__).resolve().parent
DATEN = PROJEKT / "daten"
FAHRTEN = DATEN / "fahrten"    # eine Fahrt = ein Unterordner mit Bildern und Lenkwinkeln
MODELLE = DATEN / "modelle"    # ein Modell = ein Unterordner mit Netz und Beschreibung

# ---------- Kamera ----------
# Die Kamera liefert direkt kleine Bilder (kein Umweg über 5 Megapixel).
KAMERA_BREITE, KAMERA_HOEHE = 320, 240
KAMERA_BILDRATE = 30           # Bilder pro Sekunde
JPEG_QUALITAET = 90            # beim Speichern der Fahrten

# Für das Netz zählt nur der Boden vor dem Auto: Wir schneiden den unteren Teil
# des Bildes aus. 0.25 = ab einem Viertel der Bildhöhe nach unten.
# Je steiler die Kamera nach unten schaut, desto mehr vom Bild ist Boden – dann
# kann der Ausschnitt weiter oben beginnen. In der Weboberfläche einstellbar.
AUSSCHNITT_OBEN = 0.25

# ---------- Taktung ----------
AUFNAHME_RATE = 10             # gespeicherte Bilder pro Sekunde beim Aufnehmen
INFERENZ_RATE = 30             # Lenkentscheidungen pro Sekunde beim autonomen Fahren

# ---------- Fahren ----------
TEMPO_STANDARD = 100           # Prozent
KAMERA_NEIGEN_STANDARD = -20   # Grad; leicht nach unten, damit die Kamera den Boden sieht
