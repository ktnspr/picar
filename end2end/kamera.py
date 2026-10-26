"""
kamera.py – Liest die Frontkamera und bereitet die Bilder für das Netz vor.

Die Kamera liefert direkt kleine Bilder (320×240) mit 30 Bildern pro Sekunde.
Ein Hintergrund-Thread holt ständig das neueste Bild ab. Wer ein Bild braucht
(Aufnahme, Netz, Livebild im Browser), nimmt sich das neueste.
Den Ausschnitt fürs Netz macht kern/vorverarbeitung.py (gleich für Pi und Mac).

Hinweis zu den Farben: picamera2 nennt das Format „RGB888“, legt die Farben im
Speicher aber in der Reihenfolge Blau-Grün-Rot ab – genau so, wie OpenCV es erwartet.
"""

import threading
import time

import cv2
import numpy as np
from picamera2 import Picamera2

from einstellungen import AUSSCHNITT_OBEN, KAMERA_BILDRATE, KAMERA_BREITE, KAMERA_HOEHE, LENKUNG_MAX


class Kamera:
    def __init__(self):
        self.picam = Picamera2()
        konfiguration = self.picam.create_video_configuration(
            main={"size": (KAMERA_BREITE, KAMERA_HOEHE), "format": "RGB888"},
            # Sensor-Modus 640×480: voller Bildwinkel, bis 62 Bilder/s
            sensor={"output_size": (640, 480)},
            controls={"FrameRate": KAMERA_BILDRATE},
            buffer_count=4,
        )
        self.picam.configure(konfiguration)
        self.picam.start()

        self.bild = None        # das neueste Bild
        self.bildnummer = 0     # zählt mit, damit man erkennt, ob ein neues Bild da ist
        self._neues_bild = threading.Condition()
        self._laeuft = True
        threading.Thread(target=self._lesen, daemon=True).start()

    def _lesen(self):
        while self._laeuft:
            bild = self.picam.capture_array("main")  # wartet, bis die Kamera ein neues Bild hat
            with self._neues_bild:
                self.bild = bild
                self.bildnummer += 1
                self._neues_bild.notify_all()

    def naechstes_bild(self, letzte_nummer=0, timeout=1.0):
        """Wartet auf ein Bild, das neuer ist als letzte_nummer. Ergebnis: (nummer, bild)."""
        with self._neues_bild:
            self._neues_bild.wait_for(lambda: self.bildnummer > letzte_nummer, timeout)
            return self.bildnummer, self.bild

    def schliessen(self):
        self._laeuft = False
        time.sleep(0.1)
        self.picam.stop()
        self.picam.close()


def overlay_zeichnen(bild, lenkwinkel=None, text="", farbe=(0, 220, 0), ausschnitt_oben=AUSSCHNITT_OBEN):
    """Zeichnet ins Livebild: den Ausschnitt fürs Netz, den Lenkwinkel als Pfeil und einen Text."""
    bild = bild.copy()
    h, w = bild.shape[:2]
    oben = int(h * ausschnitt_oben)
    cv2.rectangle(bild, (0, oben), (w - 1, h - 1), (255, 200, 0), 1)  # was das Netz sieht

    if lenkwinkel is not None:
        # Pfeil vom unteren Bildrand in Lenkrichtung (0° = gerade nach oben)
        start = (w // 2, h - 5)
        laenge = h * 0.35
        winkel = np.radians(lenkwinkel)
        ende = (int(start[0] + laenge * np.sin(winkel)), int(start[1] - laenge * np.cos(winkel)))
        cv2.arrowedLine(bild, start, ende, farbe, 3, tipLength=0.2)
        text = f"{lenkwinkel:+.0f} Grad  {text}".strip()
        # Balken oben: wie weit ist eingeschlagen?
        mitte = w // 2
        balken = int(lenkwinkel / LENKUNG_MAX * (w // 2 - 10))
        cv2.rectangle(bild, (mitte, 4), (mitte + balken, 12), farbe, -1)
        cv2.line(bild, (mitte, 2), (mitte, 14), (255, 255, 255), 1)

    if text:
        cv2.putText(bild, text, (6, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(bild, text, (6, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return bild
