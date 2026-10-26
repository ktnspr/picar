"""
regler_einmessen.py – Findet gute Reglerwerte (Kp, Kd) für die aktive Kamera durch Ausprobieren.

Das Auto steht, die Linie ist im Bild. Für jede Kombination aus Kp und Kd wird die Kamera
um 15° neben die Linie gedreht und dann losgelassen („Sprungantwort“), einmal nach links,
einmal nach rechts. Bei jedem Kamerabild wird mitgeschrieben, wie weit die Linie noch neben
der Bildmitte liegt. Daraus berechnet diese Datei drei Kennzahlen:

    Einschwingzeit   ab wann bleibt die Abweichung dauerhaft klein?        (Sekunden)
    Überschwingen    wie weit schießt die Kamera über die Linie hinaus?     (Grad)
    Unruhe           wie stark zappelt die Kamera danach noch?              (Grad, Standardabweichung)

und daraus eine Gesamtnote (kleiner = besser).
"""

import statistics

KP_WERTE = (0.15, 0.25, 0.35, 0.5)
KD_WERTE = (0.0, 0.05, 0.15, 0.3)
AUSLENKUNG = 15.0        # Grad – so weit wird die Kamera neben die Linie gedreht
VERSUCHSDAUER = 1.5      # Sekunden pro Versuch
RUHEZEIT = 0.5           # Sekunden am Ende, über die die Unruhe gemessen wird

# Gewichte der Gesamtnote: 1 s Einschwingzeit ≈ 33° Überschwingen ≈ 3,3° Unruhe
GEWICHT_UEBERSCHWINGEN = 0.03
GEWICHT_UNRUHE = 0.3
STRAFE_LINIE_VERLOREN = 0.5


def bewerten(aufzeichnung, toleranz):
    """aufzeichnung: Liste von (Zeit in s, Abweichung in Grad oder None, Schwenkwinkel in Grad).
    toleranz: ab dieser Abweichung gilt die Kamera als „noch nicht da“ (Grad)."""
    start = aufzeichnung[0][0]
    werte = [(t - start, fehler, schwenk) for t, fehler, schwenk in aufzeichnung]
    gueltig = [(t, fehler) for t, fehler, _ in werte if fehler is not None]
    verloren = sum(1 for _, fehler, _ in werte if fehler is None)
    if len(gueltig) < 5:
        return {"einschwingzeit": None, "ueberschwingen": None, "unruhe": None,
                "verloren": verloren, "note": 99.0}

    # Überschwingen: Abweichung auf der ANDEREN Seite als am Anfang
    seite = 1 if gueltig[0][1] > 0 else -1
    ueberschwingen = max(0.0, max(-seite * fehler for _, fehler in gueltig))

    # Einschwingzeit: der letzte Zeitpunkt, an dem die Abweichung noch zu groß war
    einschwingzeit = 0.0
    for t, fehler in gueltig:
        if abs(fehler) > toleranz:
            einschwingzeit = t
    dauer = werte[-1][0]
    if abs(gueltig[-1][1]) > toleranz:
        einschwingzeit = dauer       # am Ende immer noch nicht da

    # Unruhe: Wie sehr ändert sich der Schwenkwinkel am Ende noch?
    ende = [schwenk for t, _, schwenk in werte if t >= dauer - RUHEZEIT]
    unruhe = statistics.pstdev(ende) if len(ende) > 1 else 0.0

    note = (einschwingzeit + GEWICHT_UEBERSCHWINGEN * ueberschwingen + GEWICHT_UNRUHE * unruhe
            + (STRAFE_LINIE_VERLOREN if verloren else 0.0))
    return {"einschwingzeit": round(einschwingzeit, 2), "ueberschwingen": round(ueberschwingen, 1),
            "unruhe": round(unruhe, 2), "verloren": verloren, "note": round(note, 3)}


def zusammenfassen(kp, kd, links, rechts):
    """Mittelt die Kennzahlen aus dem Versuch nach links und dem nach rechts."""
    def mittel(name):
        werte = [v[name] for v in (links, rechts) if v[name] is not None]
        return round(sum(werte) / len(werte), 2) if werte else None
    return {"kp": kp, "kd": kd, "einschwingzeit": mittel("einschwingzeit"),
            "ueberschwingen": mittel("ueberschwingen"), "unruhe": mittel("unruhe"),
            "verloren": links["verloren"] + rechts["verloren"],
            "note": round((links["note"] + rechts["note"]) / 2, 3)}
