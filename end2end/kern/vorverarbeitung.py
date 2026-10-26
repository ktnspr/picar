"""vorverarbeitung.py – Aus einem Kamerabild das Bild fürs Netz machen."""

import cv2

from .konstanten import NETZ_BREITE, NETZ_HOEHE


def netz_ausschnitt(bild, ausschnitt_oben):
    """Schneidet den unteren Bildteil (Boden) aus und verkleinert ihn auf die Netzgröße.

    ausschnitt_oben: ab welcher Bildhöhe (0 bis 1) der Ausschnitt beginnt, z. B. 0.25.
    """
    oben = int(bild.shape[0] * ausschnitt_oben)
    return cv2.resize(bild[oben:, :], (NETZ_BREITE, NETZ_HOEHE), interpolation=cv2.INTER_AREA)
