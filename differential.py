"""
differential.py – Elektronisches Differential für die beiden Hinterräder.

Fährt ein Auto eine Kurve, legt das äußere Hinterrad einen längeren Weg zurück
als das innere – es muss also schneller drehen. Bei einem echten Auto erledigt
das ein Zahnrad-Getriebe (das Differential). Der PiCar-X hat zwei einzelne
Motoren, deshalb rechnen wir aus, wie schnell jedes Rad drehen muss.

So sieht das von oben aus (Rechtskurve):

         Vorderräder (gelenkt)
            \\      \\
             \\      \\           Alle Räder fahren auf Kreisen um
              |      |           denselben Mittelpunkt M.
    Radstand  |      |
              |      |           Kurvenradius (Mitte Hinterachse):
         links O------O rechts   R = Radstand / tan(Lenkwinkel)
               |<---->|
               Spurweite  -------------------- M

    linkes Rad (außen):  Radius R + Spurweite/2   → schneller
    rechtes Rad (innen): Radius R - Spurweite/2   → langsamer

Diese Datei braucht keine Hardware – man kann sie auch am PC ausprobieren.
"""

import math

# Maße des PiCar-X V2.0 (aus der Maßzeichnung von SunFounder abgeleitet)
RADSTAND = 95.0    # mm, Abstand Vorderachse – Hinterachse
SPURWEITE = 115.0  # mm, Abstand der Hinterräder (Reifenmitte zu Reifenmitte)

# Unterhalb dieses PWM-Werts (in %) bleibt ein drehendes Rad stehen. Darüber
# wird es etwa gleichmäßig schneller, je mehr PWM es bekommt.
# Gemessen mit motortest.py am aufgebockten Auto: Ein drehendes Rad bleibt bei
# 10 % stehen; aus dem Stand läuft es erst ab 20 % an.
MINDEST_PWM = 10


def radgeschwindigkeiten(tempo, lenkwinkel):
    """Berechnet, wie schnell das linke und das rechte Hinterrad drehen sollen.

    tempo:       gewünschte Geschwindigkeit der Wagenmitte, 0 bis 1
    lenkwinkel:  in Grad, negativ = links, positiv = rechts

    Ergebnis: (links, rechts), jeweils höchstens 1 (= volle Kraft).
    """
    # Statt erst den Kurvenradius R auszurechnen, nehmen wir gleich das
    # Verhältnis (Spurweite/2) / R. Das funktioniert auch bei Lenkwinkel 0,
    # wo R unendlich groß wäre.
    unterschied = SPURWEITE * math.tan(math.radians(lenkwinkel)) / (2 * RADSTAND)

    links = tempo * (1 + unterschied)   # bei Rechtskurve außen → schneller
    rechts = tempo * (1 - unterschied)  # bei Rechtskurve innen → langsamer

    # Kein Rad kann schneller als 100 % drehen. Wäre das äußere Rad zu schnell,
    # bremsen wir beide gleichmäßig ab – so bleibt das Verhältnis richtig.
    schnellstes = max(abs(links), abs(rechts))
    if schnellstes > 1:
        links = links / schnellstes
        rechts = rechts / schnellstes
    return links, rechts


def pwm_wert(geschwindigkeit):
    """Rechnet eine Radgeschwindigkeit (0 bis 1) in einen PWM-Wert (0 bis 100 %) um."""
    if geschwindigkeit <= 0:
        return 0
    return MINDEST_PWM + geschwindigkeit * (100 - MINDEST_PWM)
