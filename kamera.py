"""
kamera.py – Holt die Bilder der Frontkamera und verschickt sie als Video-Stream.

Die Bibliothek vilib liest die Kamera im Hintergrund aus und legt das jeweils
neueste Bild in Vilib.img ab. Wir verpacken diese Bilder als JPEG und schicken
sie nacheinander an den Browser („MJPEG“ – eine Art Daumenkino aus JPEG-Bildern).
"""

import time

import cv2
import numpy as np
from vilib import Vilib

BILDER_PRO_SEKUNDE = 20
JPEG_QUALITAET = 70  # 0–100: weniger = kleinere Bilder, schneller übers WLAN
BILDGROESSE = (640, 480)

# Falls das Bild auf dem Kopf steht oder gespiegelt ist, hier umstellen.
SPIEGELN_VERTIKAL = False
SPIEGELN_HORIZONTAL = False


def starten():
    Vilib.camera_start(vflip=SPIEGELN_VERTIKAL, hflip=SPIEGELN_HORIZONTAL, size=BILDGROESSE)


def stoppen():
    Vilib.camera_close()


def mjpeg_stream():
    """Liefert endlos JPEG-Bilder im MJPEG-Format (für ein <img>-Element im Browser)."""
    while True:
        bild = Vilib.img
        # Ganz am Anfang gibt es eventuell noch kein Bild.
        if isinstance(bild, np.ndarray):
            ok, jpeg = cv2.imencode(".jpg", bild, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITAET])
            if ok:
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n")
        time.sleep(1 / BILDER_PRO_SEKUNDE)
