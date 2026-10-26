"""
akku.py – Schätzt den Ladestand des Akkus aus der gemessenen Spannung.

Das Robot HAT kann nur die Spannung des Akkus messen, nicht direkt den
Ladestand in Prozent. Ein Li-Ionen-Akku verliert seine Spannung aber nicht
gleichmäßig: Am Anfang und am Ende fällt sie schnell, in der Mitte nur
langsam. Deshalb rechnen wir nicht mit einer Geraden, sondern schauen in
einer Tabelle (Entladekurve) nach.

Diese Datei braucht keine Hardware – man kann sie auch am PC ausprobieren.
"""

from collections import deque

# Typische Entladekurve eines 2S-Li-Ionen-Akkus (zwei Zellen hintereinander).
# Jede Zeile: (Spannung in Volt, Ladestand in Prozent), von voll nach leer.
ENTLADEKURVE = [
    (8.40, 100),
    (8.20, 90),
    (8.00, 80),
    (7.84, 70),
    (7.70, 60),
    (7.60, 50),
    (7.50, 40),
    (7.40, 30),
    (7.30, 20),
    (7.10, 10),
    (6.80, 5),
    (6.40, 0),
]

# Messwerte außerhalb dieses Bereichs sind Messfehler (oder kein Akku dran)
# und werden ignoriert.
KLEINSTE_PLAUSIBLE_SPANNUNG = 5.0  # Volt
GROESSTE_PLAUSIBLE_SPANNUNG = 9.0  # Volt


def spannung_zu_prozent(spannung):
    """Rechnet eine Spannung (Volt) in einen geschätzten Ladestand (0–100 %) um."""
    hoechste_spannung = ENTLADEKURVE[0][0]
    niedrigste_spannung = ENTLADEKURVE[-1][0]
    if spannung >= hoechste_spannung:
        return 100.0
    if spannung <= niedrigste_spannung:
        return 0.0

    # Wir suchen die zwei Tabellenzeilen, zwischen denen die Spannung liegt,
    # und rechnen dazwischen linear (Interpolation).
    for (u_oben, p_oben), (u_unten, p_unten) in zip(ENTLADEKURVE, ENTLADEKURVE[1:]):
        if u_unten <= spannung <= u_oben:
            anteil = (spannung - u_unten) / (u_oben - u_unten)  # 0 = unten, 1 = oben
            return p_unten + anteil * (p_oben - p_unten)


class AkkuAnzeige:
    """Sammelt Spannungs-Messwerte und glättet sie mit einem gleitenden Mittelwert.

    Beim Anfahren brechen die Motoren die Spannung kurz ein. Würden wir jeden
    einzelnen Messwert anzeigen, würde der Ladestand ständig springen. Deshalb
    merken wir uns die letzten Messwerte und zeigen ihren Durchschnitt an.
    """

    def __init__(self, anzahl_werte=10):
        # Eine deque mit maxlen vergisst automatisch den ältesten Wert,
        # sobald ein neuer dazukommt.
        self.messwerte = deque(maxlen=anzahl_werte)

    def messwert_hinzufuegen(self, spannung):
        if KLEINSTE_PLAUSIBLE_SPANNUNG <= spannung <= GROESSTE_PLAUSIBLE_SPANNUNG:
            self.messwerte.append(spannung)

    def spannung(self):
        """Geglättete Spannung in Volt, oder None, wenn es noch keine Messwerte gibt."""
        werte = list(self.messwerte)  # Kopie, falls gerade ein neuer Wert dazukommt
        if not werte:
            return None
        return sum(werte) / len(werte)

    def als_dict(self):
        """Ladestand und Spannung so, wie die Webseite sie braucht."""
        spannung = self.spannung()
        if spannung is None:
            return {"prozent": None, "spannung": None}
        return {
            "prozent": round(spannung_zu_prozent(spannung)),
            "spannung": round(spannung, 2),
        }
