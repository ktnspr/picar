"""
kamera_regler.py – Schwenkt die Kamera so, dass die Linie in der Bildmitte bleibt („aktive Kamera“).

Ein PD-Regler (P = proportional, D = differenziell):
    Abweichung e  = Winkel der Linie neben der Bildmitte (aus linie.py), in Grad
    Schritt       = Kp · e  +  Kd · (e − e_vorher)
  - Der P-Teil dreht die Kamera um einen Teil der Abweichung in Richtung Linie.
  - Der D-Teil reagiert auf die ÄNDERUNG der Abweichung und dämpft Überschwingen.
  - Totzone: kleine Abweichungen ignorieren, damit die Kamera nicht zittert.
  - Höchstgeschwindigkeit: nicht zu schnell schwenken, sonst wird das Bild unscharf.

Ist die Linie verloren, sucht die Kamera – zuerst in die Richtung, in die sie zuletzt
geschwenkt hat. Bleibt die Linie länger als „verlust_zeit“ verschwunden, meldet der
Regler „verloren“ (beim autonomen Fahren hält das Auto dann an).

Der Schwenkwinkel der Kamera ist danach eine Messgröße: Er zeigt, in welche Richtung
die Linie vor dem Auto verläuft.
"""

STANDARD = {
    "kp": 0.35,                 # Anteil der Abweichung, der pro Bild ausgeglichen wird
    "kd": 0.15,                 # Dämpfung
    "totzone": 1.5,             # Grad
    "max_geschwindigkeit": 150, # Grad pro Sekunde
    "such_geschwindigkeit": 90, # Grad pro Sekunde beim Suchen
    "schwenk_max": 60,          # Grad – weiter schwenkt die Kamera nicht
    "verlust_zeit": 1.5,        # Sekunden ohne Linie → „verloren“
    "richtung": 1,              # 1 oder -1, falls der Servo andersherum eingebaut ist
}

FOLGT, SUCHT, VERLOREN = "folgt", "sucht", "verloren"


class Kameraregler:
    def __init__(self, einstellungen=None):
        self.einstellungen = dict(STANDARD)
        self.einstellen(einstellungen or {})
        self.zuruecksetzen()

    def einstellen(self, einstellungen):
        self.einstellungen.update({k: v for k, v in einstellungen.items() if k in STANDARD})

    def zuruecksetzen(self):
        self.zustand = FOLGT
        self._e_vorher = None
        self._letzte_richtung = 1      # +1 = Linie zuletzt rechts gesehen (Kamera schwenkte nach rechts), -1 = links
        self.zeit_ohne_linie = 0.0

    def schritt(self, linie, schwenken, dt):
        """Ein Regelschritt. linie: Ergebnis von linie.py; schwenken: aktueller Kamerawinkel (Grad);
        dt: Zeit seit dem letzten Schritt (Sekunden). Ergebnis: neuer Kamerawinkel."""
        e = self.einstellungen
        max_schritt = e["max_geschwindigkeit"] * dt

        if linie is not None and linie.sichtbar:
            self.zustand = FOLGT
            self.zeit_ohne_linie = 0.0
            abweichung = linie.winkel
            if abs(abweichung) < e["totzone"]:
                abweichung = 0.0
            else:
                # Auf dieser Seite liegt die Linie – dorthin schwenkt die Kamera gerade.
                # Verschwindet die Linie, suchen wir zuerst in diese Richtung.
                self._letzte_richtung = 1 if abweichung > 0 else -1
            d_teil = 0.0 if self._e_vorher is None else abweichung - self._e_vorher
            self._e_vorher = abweichung
            schritt = e["kp"] * abweichung + e["kd"] * d_teil
            schritt = max(-max_schritt, min(max_schritt, schritt))   # Höchstgeschwindigkeit
        else:
            # Linie weg: suchen – zuerst dorthin, wohin wir zuletzt geschwenkt haben
            self._e_vorher = None
            self.zeit_ohne_linie += dt
            self.zustand = SUCHT if self.zeit_ohne_linie < e["verlust_zeit"] else VERLOREN
            schritt = self._letzte_richtung * e["such_geschwindigkeit"] * dt
            if abs(schwenken + e["richtung"] * schritt) >= e["schwenk_max"]:
                self._letzte_richtung *= -1        # am Anschlag umkehren
                schritt = -schritt

        neu = schwenken + e["richtung"] * schritt
        return max(-e["schwenk_max"], min(e["schwenk_max"], neu))
