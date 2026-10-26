"""
auto.py – Steuert die Hardware des PiCar-X: Motoren, Lenkung und Kamera-Halterung.

Hier steckt auch die Totmannschaltung: Der Browser muss regelmäßig ein
Lebenszeichen schicken. Bleibt es zu lange aus (WLAN weg, Seite geschlossen),
hält das Auto sofort an.
"""

import threading
import time

import picarx.picarx
from picarx import Picarx
from robot_hat import fileDB
from robot_hat.device import get_battery_voltage

import differential

# Die picarx-Bibliothek speichert ihre Kalibrierwerte mit fileDB und ruft dabei
# bei jedem Start „sudo chmod“ und „sudo chown“ auf – der Server würde dann jedes
# Mal nach dem sudo-Passwort fragen. Weil der Ordner /opt/picar-x schon uns gehört
# (siehe README.md), lassen wir diese beiden Angaben einfach weg.
picarx.picarx.fileDB = lambda datei, rechte=None, besitzer=None: fileDB(datei)

# Bleibt das Lebenszeichen länger als diese Zeit aus, stoppen die Motoren.
TOTMANN_ZEIT = 0.5  # Sekunden
# So oft schaut der Wächter nach, ob noch Lebenszeichen ankommen.
WAECHTER_PAUSE = 0.05  # Sekunden

# Nummern der Hinterrad-Motoren in der picarx-Bibliothek
LINKER_MOTOR = 0
RECHTER_MOTOR = 1
# Damit beide Räder vorwärts drehen, muss der rechte Motor andersherum laufen
# als der linke – er ist spiegelverkehrt eingebaut (so macht es auch picarx).
EINBAURICHTUNG = [1, -1]

# Die drei möglichen Fahrtrichtungen
VORWAERTS = "vor"
RUECKWAERTS = "zurueck"
STOPP = "stopp"


def begrenzen(wert, kleinster, groesster):
    """Sorgt dafür, dass ein Wert zwischen kleinster und groesster bleibt."""
    return max(kleinster, min(groesster, wert))


class Auto:
    # Grenzen für die Servos, wie sie die picarx-Bibliothek vorgibt (in Grad)
    LENKUNG_MIN, LENKUNG_MAX = Picarx.DIR_MIN, Picarx.DIR_MAX
    SCHWENKEN_MIN, SCHWENKEN_MAX = Picarx.CAM_PAN_MIN, Picarx.CAM_PAN_MAX
    NEIGEN_MIN, NEIGEN_MAX = Picarx.CAM_TILT_MIN, Picarx.CAM_TILT_MAX
    # So weit darf die Mitte von Lenkung und Kamera beim Feinjustieren verschoben werden
    JUSTIERUNG_MAX = 20

    def __init__(self):
        try:
            self.px = Picarx()
        except PermissionError:
            raise SystemExit(
                "Die picarx-Bibliothek darf ihre Einstellungsdatei nicht anlegen.\n"
                "Bitte einmalig ausführen:\n"
                "    sudo mkdir -p /opt/picar-x && sudo chown pi:pi /opt/picar-x"
            )

        self.richtung = STOPP
        self.tempo = 30  # Prozent
        self.lenkwinkel = 0  # Grad, negativ = links, positiv = rechts
        self.schwenken = 0   # Kamera, Grad, negativ = links, positiv = rechts
        self.neigen = 0      # Kamera, Grad
        self.letztes_lebenszeichen = time.monotonic()

        # Mehrere Programmteile (Webseiten-Anfragen, Totmann-Wächter, Akku-Messung)
        # laufen gleichzeitig. Die Sperre sorgt dafür, dass immer nur einer
        # gerade mit der Hardware spricht.
        self._sperre = threading.Lock()

        # Der Wächter läuft im Hintergrund, solange das Programm läuft.
        threading.Thread(target=self._totmann_waechter, daemon=True).start()

    # ------------------------------------------------------------------
    # Befehle von der Webseite
    # ------------------------------------------------------------------

    def lebenszeichen(self):
        """Der Browser meldet: „Ich bin noch da.“"""
        self.letztes_lebenszeichen = time.monotonic()

    def fahren(self, richtung):
        """Fährt dauerhaft in die Richtung VORWAERTS, RUECKWAERTS oder STOPP."""
        if richtung not in (VORWAERTS, RUECKWAERTS, STOPP):
            raise ValueError(f"Unbekannte Richtung: {richtung}")
        # Wer einen Fahrbefehl schickt, ist offensichtlich noch da.
        self.lebenszeichen()
        with self._sperre:
            self.richtung = richtung
            self._motoren_einstellen()

    def tempo_setzen(self, prozent):
        """Ändert die Geschwindigkeit – auch mitten in der Fahrt."""
        with self._sperre:
            self.tempo = begrenzen(int(prozent), 0, 100)
            self._motoren_einstellen()

    def lenken(self, winkel):
        with self._sperre:
            self.lenkwinkel = begrenzen(winkel, self.LENKUNG_MIN, self.LENKUNG_MAX)
            self.px.set_dir_servo_angle(self.lenkwinkel)
            # In Kurven dreht das innere Rad langsamer als das äußere
            # (siehe differential.py) – also die Motoren neu einstellen.
            self._motoren_einstellen()

    def lenkung_justieren(self, aenderung):
        """Verschiebt die Mitte der Lenkung um „aenderung“ Grad (Feinjustierung).

        picarx speichert den Wert in /opt/picar-x/picar-x.conf – er gilt also
        auch nach einem Neustart und für die SunFounder-Beispielprogramme.
        """
        with self._sperre:
            neue_mitte = begrenzen(self.px.dir_cali_val + aenderung,
                                   -self.JUSTIERUNG_MAX, self.JUSTIERUNG_MAX)
            self.px.dir_servo_calibrate(neue_mitte)
            # dir_servo_calibrate stellt die Räder auf die neue Mitte –
            # falls gerade gelenkt wird, den Lenkwinkel wiederherstellen.
            self.px.set_dir_servo_angle(self.lenkwinkel)

    def kamera_ausrichten(self, schwenken, neigen):
        with self._sperre:
            self.schwenken = begrenzen(schwenken, self.SCHWENKEN_MIN, self.SCHWENKEN_MAX)
            self.neigen = begrenzen(neigen, self.NEIGEN_MIN, self.NEIGEN_MAX)
            self.px.set_cam_pan_angle(self.schwenken)
            self.px.set_cam_tilt_angle(self.neigen)

    def kamera_justieren(self, schwenken_aenderung, neigen_aenderung):
        """Verschiebt die Mitte der Kamera (Feinjustierung), so wie lenkung_justieren.

        Auch diese Werte speichert picarx dauerhaft in /opt/picar-x/picar-x.conf.
        """
        with self._sperre:
            # picarx rechnet bei der Kamera „Mitte minus Winkel“. Damit eine positive
            # Änderung die Kamera nach rechts bzw. oben dreht, ziehen wir sie ab.
            neue_mitte_schwenken = begrenzen(self.px.cam_pan_cali_val - schwenken_aenderung,
                                             -self.JUSTIERUNG_MAX, self.JUSTIERUNG_MAX)
            neue_mitte_neigen = begrenzen(self.px.cam_tilt_cali_val - neigen_aenderung,
                                          -self.JUSTIERUNG_MAX, self.JUSTIERUNG_MAX)
            self.px.cam_pan_servo_calibrate(neue_mitte_schwenken)
            self.px.cam_tilt_servo_calibrate(neue_mitte_neigen)
            # Die calibrate-Funktionen stellen die Kamera auf die neue Mitte –
            # falls sie gerade woanders hinschaut, die Stellung wiederherstellen.
            self.px.set_cam_pan_angle(self.schwenken)
            self.px.set_cam_tilt_angle(self.neigen)

    def akku_spannung_messen(self):
        """Misst die Akkuspannung in Volt."""
        with self._sperre:
            return get_battery_voltage()

    def status(self):
        """Der aktuelle Zustand, damit die Webseite ihn anzeigen kann."""
        return {
            "richtung": self.richtung,
            "tempo": self.tempo,
            "lenkwinkel": self.lenkwinkel,
            "lenkung_mitte": self.px.dir_cali_val,
            # Vorzeichen wie bei kamera_justieren: positiv = nach rechts bzw. oben verschoben
            "kamera_mitte_schwenken": -self.px.cam_pan_cali_val,
            "kamera_mitte_neigen": -self.px.cam_tilt_cali_val,
        }

    def herunterfahren(self):
        """Motoren aus, Lenkung und Kamera geradeaus – für das Programmende."""
        with self._sperre:
            self.richtung = STOPP
            self.px.stop()
            self.px.set_dir_servo_angle(0)
            self.schwenken, self.neigen = 0, 0
            self.px.set_cam_pan_angle(0)
            self.px.set_cam_tilt_angle(0)

    # ------------------------------------------------------------------
    # Interne Hilfsfunktionen
    # ------------------------------------------------------------------

    def _motoren_einstellen(self):
        """Stellt die Motoren passend zu Richtung, Tempo und Lenkwinkel ein.

        Darf nur aufgerufen werden, während die Sperre gehalten wird.
        """
        if self.richtung == STOPP:
            self.px.stop()
            return

        links, rechts = differential.radgeschwindigkeiten(self.tempo / 100, self.lenkwinkel)
        if self.richtung == RUECKWAERTS:
            links, rechts = -links, -rechts
        self._motor_setzen(LINKER_MOTOR, links)
        self._motor_setzen(RECHTER_MOTOR, rechts)

    def _motor_setzen(self, motor, geschwindigkeit):
        """Lässt einen Hinterrad-Motor drehen.

        geschwindigkeit: -1 bis 1, positiv = vorwärts, negativ = rückwärts

        Die picarx-Bibliothek kann beide Motoren nur gemeinsam steuern. Für das
        Differential stellen wir Drehrichtung und PWM jedes Motors selbst ein.
        """
        drehrichtung = 1 if geschwindigkeit >= 0 else -1
        # Die Motoren sind spiegelverkehrt eingebaut, und je nach Verkabelung
        # dreht ein Motor andersherum (Kalibrierwert aus /opt/picar-x).
        drehrichtung *= EINBAURICHTUNG[motor] * self.px.cali_dir_value[motor]

        if drehrichtung > 0:
            self.px.motor_direction_pins[motor].low()
        else:
            self.px.motor_direction_pins[motor].high()
        self.px.motor_speed_pins[motor].pulse_width_percent(differential.pwm_wert(abs(geschwindigkeit)))

    def _totmann_waechter(self):
        """Läuft endlos im Hintergrund und stoppt das Auto, wenn der Browser schweigt."""
        while True:
            time.sleep(WAECHTER_PAUSE)
            stille = time.monotonic() - self.letztes_lebenszeichen
            if self.richtung != STOPP and stille > TOTMANN_ZEIT:
                print(f"Totmannschaltung: {stille:.2f} s kein Lebenszeichen – Motoren gestoppt!")
                with self._sperre:
                    self.richtung = STOPP
                    self.px.stop()
