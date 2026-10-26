"""
linie.py – Findet die Klebeband-Linie im Kamerabild (klassische Bildverarbeitung mit OpenCV).

So geht es, Schritt für Schritt:
  1. Suchstreifen: Wir schauen nur auf einen waagerechten Streifen des Bildes
     (optional einen zweiten, näher am Auto). Das ist schnell und reicht für die Richtung.
  2. Schwellwert: Welche Pixel gehören zum Band?
       „hell“  – Graustufen, Schwelle automatisch nach Otsu (Band heller als Boden)
       „dunkel“ – dasselbe für dunkles Band auf hellem Boden
       „farbe“ – Abstand zur angeklickten Bandfarbe im Lab-Farbraum
                 (Lab: „Abstand“ ≈ Farbunterschied, wie ihn das Auge sieht – klappt auch für Weiß)
  3. Öffnung (Morphologie): einzelne Störpixel (Holzmaserung, Rauschen) entfernen.
  4. Zusammenhängende Flecken suchen und den größten in der Nähe der letzten bekannten
     Linienposition nehmen (Tracking – wichtig bei Kreuzungen und Störungen).
  5. Schwerpunkt = Linienposition. Daraus über die Brennweite der Kamera einen Winkel:
     Wie weit (in Grad) liegt die Linie rechts oder links von der Bildmitte?
"""

import math
import time
from dataclasses import dataclass

import cv2
import numpy as np

STANDARD = {
    "modus": "hell",            # "hell", "dunkel" oder "farbe"
    "farbe_bgr": None,          # angeklickte Bandfarbe (Blau, Grün, Rot) für Modus „farbe“
    "toleranz": 25,             # Modus „farbe“: so weit darf ein Pixel farblich abweichen (Lab-Abstand)
    "kontrast_min": 25,         # Modus „hell/dunkel“: Mindest-Helligkeitsunterschied Band ↔ Boden
    "helligkeit_min": 155,      # Modus „hell“: so hell muss das Band mindestens sein (0–255).
                                # Gemessen: weißes Band 160–200, helle Dielen höchstens etwa 150.
    "streifen_y": 0.55,         # Mitte des Suchstreifens (Anteil der Bildhöhe, 0 = oben)
    "streifen_hoehe": 16,       # Pixel
    "zweiter_streifen": True,   # zusätzlicher, näherer Streifen
    "streifen2_y": 0.85,
    "min_pixel": 60,            # weniger Bandpixel → „Linie nicht sichtbar“
    "max_breite": 0.6,          # Flecken breiter als 60 % des Bildes sind kein Band (z. B. Lichtfleck)
    "max_sprung": 60,           # Pixel: so weit darf die Linie von Bild zu Bild springen (Tracking)
    "bildwinkel": 53.5,         # Grad, waagerechter Bildwinkel der Kamera (OV5647, voller Sensor)
}


@dataclass
class Streifenergebnis:
    sichtbar: bool
    x: float = None             # Pixel, Schwerpunkt der Linie
    pixel: int = 0              # Anzahl der Bandpixel des gewählten Flecks
    helligkeit: float = None    # mittlere Helligkeit der „Band“-Pixel (Modus hell/dunkel) – zum Einstellen
    y0: int = 0                 # Lage des Streifens im Bild
    y1: int = 0


@dataclass
class Linienergebnis:
    sichtbar: bool
    x: float = None             # Pixel (aus dem Hauptstreifen, sonst aus dem nahen Streifen)
    winkel: float = None        # Grad; positiv = Linie rechts von der Bildmitte
    streifen: tuple = ()        # Ergebnisse der einzelnen Streifen (für das Overlay)
    rechenzeit_ms: float = 0.0


def brennweite_pixel(bildbreite, bildwinkel):
    """Brennweite in Pixeln: f = (Bildbreite / 2) / tan(Bildwinkel / 2)."""
    return (bildbreite / 2) / math.tan(math.radians(bildwinkel) / 2)


class Linienerkennung:
    def __init__(self, einstellungen=None):
        self.einstellungen = dict(STANDARD)
        self.einstellen(einstellungen or {})
        self._letzte_x = {}           # je Streifen: letzte bekannte Linienposition
        self._verloren_seit = {}      # je Streifen: so viele Bilder ohne Linie

    def einstellen(self, einstellungen):
        self.einstellungen.update({k: v for k, v in einstellungen.items() if k in STANDARD})
        farbe = self.einstellungen["farbe_bgr"]
        self._farbe_lab = None
        if farbe is not None:
            self._farbe_lab = cv2.cvtColor(np.uint8([[farbe]]), cv2.COLOR_BGR2LAB)[0, 0].astype(np.float32)

    def erkennen(self, bild):
        start = time.perf_counter()
        e = self.einstellungen
        hoehe, breite = bild.shape[:2]
        streifen = [self._streifen(bild, "haupt", e["streifen_y"])]
        if e["zweiter_streifen"]:
            streifen.append(self._streifen(bild, "nah", e["streifen2_y"]))

        # Hauptstreifen bevorzugt; sieht nur der nahe Streifen die Linie, nehmen wir den
        gewaehlt = next((s for s in streifen if s.sichtbar), None)
        ergebnis = Linienergebnis(sichtbar=gewaehlt is not None, streifen=tuple(streifen))
        if gewaehlt:
            ergebnis.x = gewaehlt.x
            f = brennweite_pixel(breite, e["bildwinkel"])
            ergebnis.winkel = math.degrees(math.atan((gewaehlt.x - breite / 2) / f))
        ergebnis.rechenzeit_ms = (time.perf_counter() - start) * 1000
        return ergebnis

    # ------------------------------------------------------------------

    def _streifen(self, bild, name, mitte_anteil):
        e = self.einstellungen
        hoehe, breite = bild.shape[:2]
        y0 = int(np.clip(mitte_anteil * hoehe - e["streifen_hoehe"] / 2, 0, hoehe - e["streifen_hoehe"]))
        y1 = y0 + e["streifen_hoehe"]
        ausschnitt = bild[y0:y1]

        # 2. Schwellwert: Maske der Bandpixel
        maske, helligkeit = self._maske(ausschnitt)
        if maske is None:
            return self._nicht_gefunden(name, y0, y1, helligkeit)

        # 3. Öffnung: Störpixel entfernen (breiter Kern, weil das Band waagerecht durch den Streifen läuft)
        maske = cv2.morphologyEx(maske, cv2.MORPH_OPEN, np.ones((3, 5), np.uint8))

        # 4. Zusammenhängende Flecken
        anzahl, _, werte, schwerpunkte = cv2.connectedComponentsWithStats(maske, connectivity=8)
        kandidaten = [(werte[i, cv2.CC_STAT_AREA], schwerpunkte[i][0]) for i in range(1, anzahl)
                      if werte[i, cv2.CC_STAT_AREA] >= e["min_pixel"]
                      and werte[i, cv2.CC_STAT_WIDTH] <= e["max_breite"] * breite]
        if not kandidaten:
            return self._nicht_gefunden(name, y0, y1, helligkeit)

        # Tracking: Flecken in der Nähe der letzten Position bevorzugen
        letzte = self._letzte_x.get(name)
        if letzte is not None:
            nahe = [k for k in kandidaten if abs(k[1] - letzte) <= e["max_sprung"]]
            if nahe:
                kandidaten = nahe
        pixel, x = max(kandidaten)        # der größte Fleck
        self._letzte_x[name] = x
        self._verloren_seit[name] = 0
        return Streifenergebnis(True, float(x), int(pixel), helligkeit, y0, y1)

    def _maske(self, ausschnitt):
        """Maske der Bandpixel (255 = Band) – oder None, wenn das Band sich nicht genug abhebt.
        Zweiter Wert: Helligkeit der „Band“-Pixel (nur Modus hell/dunkel, sonst None)."""
        e = self.einstellungen
        if e["modus"] == "farbe" and self._farbe_lab is not None:
            lab = cv2.cvtColor(ausschnitt, cv2.COLOR_BGR2LAB).astype(np.float32)
            abstand = np.linalg.norm(lab - self._farbe_lab, axis=2)
            return ((abstand <= e["toleranz"]) * 255).astype(np.uint8), None

        grau = cv2.GaussianBlur(cv2.cvtColor(ausschnitt, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        art = cv2.THRESH_BINARY_INV if e["modus"] == "dunkel" else cv2.THRESH_BINARY
        _, maske = cv2.threshold(grau, 0, 255, art + cv2.THRESH_OTSU)
        # Otsu findet IMMER eine Schwelle – auch ohne Band. Hebt sich das „Band“ kaum vom
        # Rest ab, ist es nur Holzmaserung. Und auf dunklem Boden wären sonst helle Dielen-
        # fugen „Band“ – deshalb muss weißes Band zusätzlich wirklich hell sein.
        band, rest = grau[maske > 0], grau[maske == 0]
        if len(band) == 0 or len(rest) == 0:
            return None, None
        helligkeit = float(band.mean())
        if abs(helligkeit - float(rest.mean())) < e["kontrast_min"]:
            return None, helligkeit
        if e["modus"] == "hell" and helligkeit < e["helligkeit_min"]:
            return None, helligkeit
        return maske, helligkeit

    def _nicht_gefunden(self, name, y0, y1, helligkeit=None):
        # Wer die Linie länger verloren hat (1 Sekunde), vergisst ihre alte Position
        self._verloren_seit[name] = self._verloren_seit.get(name, 0) + 1
        if self._verloren_seit[name] > 30:
            self._letzte_x.pop(name, None)
        return Streifenergebnis(False, None, 0, helligkeit, y0, y1)


def overlay_linie(bild, ergebnis, schwenken=None, regler_zustand=None):
    """Zeichnet Suchstreifen, Bildmitte und die erkannte Linie ins Bild (für das Livebild)."""
    hoehe, breite = bild.shape[:2]
    cv2.line(bild, (breite // 2, 0), (breite // 2, hoehe), (200, 200, 200), 1)   # Bildmitte
    for s in ergebnis.streifen:
        farbe = (80, 220, 80) if s.sichtbar else (60, 60, 230)
        cv2.rectangle(bild, (0, s.y0), (breite - 1, s.y1), farbe, 1)
        if s.sichtbar:
            x = int(s.x)
            cv2.line(bild, (x, s.y0 - 6), (x, s.y1 + 6), farbe, 3)
    unten = hoehe - 8
    text = f"Linie {ergebnis.winkel:+.1f} Grad" if ergebnis.sichtbar else "Linie nicht sichtbar"
    if schwenken is not None:
        text += f" | Kamera {schwenken:+.0f} Grad"
    if regler_zustand is not None:
        text += {"folgt": " | folgt Linie", "sucht": " | sucht", "verloren": " | Linie verloren"}[regler_zustand]
    cv2.putText(bild, text, (6, unten), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(bild, text, (6, unten), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    return bild
