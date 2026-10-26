"""
regler_einmessen.py – Findet gute Reglerwerte (Kp, Kd) für die aktive Kamera durch Ausprobieren.

Das Auto steht, die Linie ist im Bild. Für jede Kombination aus Kp und Kd wird die Kamera
um 15° neben die Linie gedreht und dann losgelassen („Sprungantwort“), einmal nach links,
einmal nach rechts. Bei jedem Kamerabild wird mitgeschrieben, wie weit die Linie noch neben
der Bildmitte liegt. Daraus berechnet diese Datei drei Kennzahlen:

    Einschwingzeit   ab wann bleibt die Abweichung dauerhaft klein?        (Sekunden)
    Überschwingen    wie weit schießt die Kamera über die Linie hinaus?     (Grad)
    Unruhe           wie stark zappelt die Kamera danach noch?              (Grad, Standardabweichung)
    Ruckeln          wie abrupt ändert sich die Schwenkgeschwindigkeit?      (°/s pro Bild, Mittelwert)

und daraus eine Gesamtnote (kleiner = besser).

Zwei Profile:
    flott  so schnell wie möglich: Die Einschwingzeit zählt am meisten.
    ruhig  so ruhig wie möglich, aber so schnell wie nötig: Die Kamera muss innerhalb von
           0,8 s auf der Linie sein (sonst Strafaufschlag); darunter gewinnt der ruhigste Regler.
"""

import statistics

PROFILE = {
    "flott": {
        "kp_werte": (0.15, 0.25, 0.35, 0.5),
        "kd_werte": (0.0, 0.05, 0.15, 0.3),
        "versuchsdauer": 1.5,       # Sekunden pro Versuch
        # Gewichte der Gesamtnote: 1 s Einschwingzeit ≈ 33° Überschwingen ≈ 3,3° Unruhe
        "gewicht_zeit": 1.0, "gewicht_ueberschwingen": 0.03, "gewicht_unruhe": 0.3, "gewicht_ruckeln": 0.0,
        "max_einschwingzeit": None,
    },
    "ruhig": {
        "kp_werte": (0.06, 0.1, 0.15, 0.2),
        "kd_werte": (0.0, 0.03, 0.06, 0.1),
        "versuchsdauer": 2.0,       # träge Regler brauchen länger
        # Die Zeit zählt nur, wenn sie zu lang ist; sonst gewinnt, wer am ruhigsten ist
        "gewicht_zeit": 0.0, "gewicht_ueberschwingen": 0.1, "gewicht_unruhe": 1.0, "gewicht_ruckeln": 0.2,
        "max_einschwingzeit": 0.8,  # Sekunden – schneller muss die Kamera für enge Kurven sein
    },
}
AUSLENKUNG = 15.0        # Grad – so weit wird die Kamera neben die Linie gedreht
RUHEZEIT = 0.5           # Sekunden am Ende, über die die Unruhe gemessen wird
STRAFE_LINIE_VERLOREN = 0.5
STRAFE_ZU_LANGSAM = 0.5          # plus 5 Punkte pro Sekunde über der erlaubten Einschwingzeit


def bewerten(aufzeichnung, toleranz, profil="flott"):
    """aufzeichnung: Liste von (Zeit in s, Abweichung in Grad oder None, Schwenkwinkel in Grad).
    toleranz: ab dieser Abweichung gilt die Kamera als „noch nicht da“ (Grad).
    profil: "flott" oder "ruhig" – bestimmt, wie die Kennzahlen gewichtet werden."""
    p = PROFILE[profil]
    start = aufzeichnung[0][0]
    werte = [(t - start, fehler, schwenk) for t, fehler, schwenk in aufzeichnung]
    gueltig = [(t, fehler) for t, fehler, _ in werte if fehler is not None]
    verloren = sum(1 for _, fehler, _ in werte if fehler is None)
    if len(gueltig) < 5:
        return {"einschwingzeit": None, "ueberschwingen": None, "unruhe": None, "ruckeln": None,
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

    # Ruckeln: Wie sehr ändert sich die Schwenkgeschwindigkeit von Bild zu Bild?
    zeiten = [t for t, _, _ in werte]
    schwenks = [s for _, _, s in werte]
    geschwindigkeiten = [(s2 - s1) / max(t2 - t1, 1e-3)
                         for (t1, s1), (t2, s2) in zip(zip(zeiten, schwenks), zip(zeiten[1:], schwenks[1:]))]
    ruckeln = statistics.mean(abs(b - a) for a, b in zip(geschwindigkeiten, geschwindigkeiten[1:])) \
        if len(geschwindigkeiten) > 1 else 0.0

    note = (p["gewicht_zeit"] * einschwingzeit + p["gewicht_ueberschwingen"] * ueberschwingen
            + p["gewicht_unruhe"] * unruhe + p["gewicht_ruckeln"] * ruckeln
            + (STRAFE_LINIE_VERLOREN if verloren else 0.0))
    if p["max_einschwingzeit"] is not None and einschwingzeit > p["max_einschwingzeit"]:
        note += STRAFE_ZU_LANGSAM + 5 * (einschwingzeit - p["max_einschwingzeit"])   # zu träge für enge Kurven
    return {"einschwingzeit": round(einschwingzeit, 2), "ueberschwingen": round(ueberschwingen, 1),
            "unruhe": round(unruhe, 2), "ruckeln": round(ruckeln, 1), "verloren": verloren, "note": round(note, 3)}


def zusammenfassen(kp, kd, links, rechts):
    """Mittelt die Kennzahlen aus dem Versuch nach links und dem nach rechts."""
    def mittel(name):
        werte = [v[name] for v in (links, rechts) if v[name] is not None]
        return round(sum(werte) / len(werte), 2) if werte else None
    return {"kp": kp, "kd": kd, "einschwingzeit": mittel("einschwingzeit"),
            "ueberschwingen": mittel("ueberschwingen"), "unruhe": mittel("unruhe"), "ruckeln": mittel("ruckeln"),
            "verloren": links["verloren"] + rechts["verloren"],
            "note": round((links["note"] + rechts["note"]) / 2, 3)}
