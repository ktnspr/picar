"""
akku.py – Schätzt den Ladestand des Akkus aus der gemessenen Spannung.

Das Robot HAT misst nur die Spannung. Ein Li-Ionen-Akku verliert seine Spannung
aber nicht gleichmäßig: Am Anfang und am Ende fällt sie schnell, in der Mitte nur
langsam. Deshalb rechnen wir nicht mit einer Geraden, sondern schauen in einer
Tabelle (Entladekurve) nach und rechnen zwischen den Tabellenwerten.
"""

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


def spannung_zu_prozent(spannung):
    """Rechnet eine Spannung (Volt) in einen geschätzten Ladestand (0–100 %) um."""
    if spannung >= ENTLADEKURVE[0][0]:
        return 100.0
    if spannung <= ENTLADEKURVE[-1][0]:
        return 0.0
    # Die zwei Tabellenzeilen suchen, zwischen denen die Spannung liegt, und dazwischen rechnen
    for (u_oben, p_oben), (u_unten, p_unten) in zip(ENTLADEKURVE, ENTLADEKURVE[1:]):
        if u_unten <= spannung <= u_oben:
            anteil = (spannung - u_unten) / (u_oben - u_unten)   # 0 = unten, 1 = oben
            return p_unten + anteil * (p_oben - p_unten)
