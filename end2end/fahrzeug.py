"""
fahrzeug.py – Steuert die Hardware des PiCar-X: Motoren, Lenkung, Kamera-Servos.

Sicherheit:
  - Die Motoren laufen nur, wenn sie in der Weboberfläche freigegeben sind
    (großer Ein/Aus-Schalter) und nicht gesperrt sind (z. B. während des Trainings).
  - herunterfahren() hält an und stellt die Lenkung geradeaus – für das Programmende.

Die Kalibrierung (wo „geradeaus“ für Lenkung und Kamera liegt) speichert die
picarx-Bibliothek in /opt/picar-x/picar-x.conf. Sie gilt damit für alle Programme.
"""

import math
import threading

import picarx.picarx
from picarx import Picarx
from robot_hat import fileDB
from robot_hat.device import get_battery_voltage

from einstellungen import LENKUNG_MAX

# picarx ruft beim Start „sudo chmod/chown“ für seine Einstellungsdatei auf und würde
# dann nach dem sudo-Passwort fragen. Der Ordner /opt/picar-x gehört bereits dem
# Benutzer pi, deshalb lassen wir diese Angaben weg.
picarx.picarx.fileDB = lambda datei, rechte=None, besitzer=None: fileDB(datei)

# ---------- Elektronisches Differential ----------
# In der Kurve muss das äußere Hinterrad schneller drehen als das innere.
RADSTAND = 95.0     # mm, Vorderachse bis Hinterachse
SPURWEITE = 115.0   # mm, Abstand der Hinterräder
MINDEST_PWM = 10    # %, darunter bleibt ein drehendes Rad stehen (gemessen)

LINKER_MOTOR, RECHTER_MOTOR = 0, 1
EINBAURICHTUNG = [1, -1]   # der rechte Motor ist spiegelverkehrt eingebaut

KALIBRIERUNG_MAX = 20      # so weit darf die „Mitte“ eines Servos verschoben werden (Grad)


def begrenzen(wert, kleinster, groesster):
    return max(kleinster, min(groesster, wert))


def radgeschwindigkeiten(tempo, lenkwinkel):
    """Geschwindigkeit (0 bis 1) für linkes und rechtes Hinterrad.

    Alle Räder fahren in der Kurve um denselben Mittelpunkt. Das äußere Rad
    hat den größeren Kreis und muss deshalb schneller drehen.
    """
    unterschied = SPURWEITE * math.tan(math.radians(lenkwinkel)) / (2 * RADSTAND)
    links, rechts = tempo * (1 + unterschied), tempo * (1 - unterschied)
    schnellstes = max(abs(links), abs(rechts))
    if schnellstes > 1:   # kein Rad kann schneller als 100 % – beide gleich abbremsen
        links, rechts = links / schnellstes, rechts / schnellstes
    return links, rechts


class Fahrzeug:
    def __init__(self):
        try:
            self.px = Picarx()
        except PermissionError:
            raise SystemExit("Bitte einmalig ausführen:\n"
                             "    sudo mkdir -p /opt/picar-x && sudo chown pi:pi /opt/picar-x")
        self.motoren_frei = False      # großer Schalter in der Weboberfläche – beim Start AUS
        self.motoren_gesperrt = False  # z. B. während des Trainings
        self.tempo = 0                 # Prozent; 0 = steht
        self.lenkwinkel = 0.0          # Grad; negativ = links, positiv = rechts
        self.schwenken = 0.0           # Kamera, Grad; positiv = rechts
        self.neigen = 0.0              # Kamera, Grad; positiv = oben
        # Mehrere Programmteile laufen gleichzeitig – nur einer darf mit der Hardware sprechen.
        self._sperre = threading.Lock()

    # ------------------------------------------------------------------
    # Fahren und Lenken
    # ------------------------------------------------------------------

    def faehrt(self):
        return self.tempo > 0

    def fahren(self, tempo):
        """Fährt vorwärts mit tempo Prozent (0 = anhalten). Geht nur bei freigegebenen Motoren."""
        with self._sperre:
            if not self.motoren_frei or self.motoren_gesperrt:
                tempo = 0
            self.tempo = begrenzen(tempo, 0, 100)
            self._motoren_einstellen()

    def anhalten(self):
        self.fahren(0)

    def lenken(self, winkel):
        with self._sperre:
            self.lenkwinkel = begrenzen(winkel, -LENKUNG_MAX, LENKUNG_MAX)
            self.px.set_dir_servo_angle(self.lenkwinkel)
            self._motoren_einstellen()   # das Differential braucht den neuen Lenkwinkel

    def motoren_freigeben(self, frei):
        self.motoren_frei = frei
        if not frei:
            self.anhalten()

    def motoren_sperren(self, gesperrt):
        self.motoren_gesperrt = gesperrt
        if gesperrt:
            self.anhalten()

    def kamera_ausrichten(self, schwenken, neigen):
        with self._sperre:
            self.schwenken = begrenzen(schwenken, Picarx.CAM_PAN_MIN, Picarx.CAM_PAN_MAX)
            self.neigen = begrenzen(neigen, Picarx.CAM_TILT_MIN, Picarx.CAM_TILT_MAX)
            self.px.set_cam_pan_angle(self.schwenken)
            self.px.set_cam_tilt_angle(self.neigen)

    def akku_spannung(self):
        with self._sperre:
            return get_battery_voltage()

    def herunterfahren(self):
        """Motoren aus, Lenkung geradeaus – für das Programmende."""
        with self._sperre:
            self.tempo = 0
            self.px.stop()
            self.px.set_dir_servo_angle(0)

    # ------------------------------------------------------------------
    # Kalibrierung
    # ------------------------------------------------------------------
    # Die Werte geben an, wie weit die „Mitte“ eines Servos verschoben ist.
    # Positiv heißt immer: Lenkung nach rechts, Kamera nach rechts bzw. oben.
    # (Bei der Kamera rechnet picarx mit umgekehrtem Vorzeichen – das gleichen wir hier aus.)

    def kalibrierung_lesen(self):
        return {
            "lenkung": float(self.px.dir_cali_val),
            "schwenken": -float(self.px.cam_pan_cali_val),
            "neigen": -float(self.px.cam_tilt_cali_val),
        }

    def kalibrierung_vorschau(self, lenkung, schwenken, neigen):
        """Stellt die Servos auf die Mitte mit diesen Werten – ohne zu speichern."""
        with self._sperre:
            self.px.stop()
            self.tempo = 0
            self.px.dir_servo_pin.angle(begrenzen(lenkung, -KALIBRIERUNG_MAX, KALIBRIERUNG_MAX))
            self.px.cam_pan.angle(-begrenzen(schwenken, -KALIBRIERUNG_MAX, KALIBRIERUNG_MAX))
            self.px.cam_tilt.angle(-begrenzen(neigen, -KALIBRIERUNG_MAX, KALIBRIERUNG_MAX))

    def kalibrierung_speichern(self, lenkung, schwenken, neigen):
        """Speichert die Werte über die Kalibrierfunktionen von picarx (gilt systemweit)."""
        with self._sperre:
            self.px.dir_servo_calibrate(begrenzen(lenkung, -KALIBRIERUNG_MAX, KALIBRIERUNG_MAX))
            self.px.cam_pan_servo_calibrate(-begrenzen(schwenken, -KALIBRIERUNG_MAX, KALIBRIERUNG_MAX))
            self.px.cam_tilt_servo_calibrate(-begrenzen(neigen, -KALIBRIERUNG_MAX, KALIBRIERUNG_MAX))
        self.lenken(0)
        self.kamera_ausrichten(0, 0)

    def kalibrierung_voruebergehend(self, werte):
        """Setzt eine Kalibrierung nur für jetzt – OHNE sie zu speichern.

        Damit fährt ein Modell mit genau der Kalibrierung, mit der seine Daten aufgenommen
        wurden. Zurück zur gespeicherten Kalibrierung: kalibrierung_aus_datei().
        """
        with self._sperre:
            self.px.dir_cali_val = float(werte["lenkung"])
            self.px.cam_pan_cali_val = -float(werte["schwenken"])
            self.px.cam_tilt_cali_val = -float(werte["neigen"])
        self._servos_neu_stellen()

    def kalibrierung_aus_datei(self):
        """Wieder die gespeicherte (systemweite) Kalibrierung verwenden."""
        with self._sperre:
            datei = self.px.config_flie
            self.px.dir_cali_val = float(datei.get("picarx_dir_servo", default_value=0))
            self.px.cam_pan_cali_val = float(datei.get("picarx_cam_pan_servo", default_value=0))
            self.px.cam_tilt_cali_val = float(datei.get("picarx_cam_tilt_servo", default_value=0))
        self._servos_neu_stellen()

    def gespeicherte_kalibrierung(self):
        """Die Kalibrierung aus der Datei – auch während gerade eine vorübergehende gilt."""
        datei = self.px.config_flie
        return {
            "lenkung": float(datei.get("picarx_dir_servo", default_value=0)),
            "schwenken": -float(datei.get("picarx_cam_pan_servo", default_value=0)),
            "neigen": -float(datei.get("picarx_cam_tilt_servo", default_value=0)),
        }

    def _servos_neu_stellen(self):
        """Nach einer Änderung der Kalibrierung die Servos mit der neuen Mitte neu stellen."""
        self.lenken(self.lenkwinkel)
        self.kamera_ausrichten(self.schwenken, self.neigen)

    # ------------------------------------------------------------------

    def _motoren_einstellen(self):
        """Stellt beide Hinterrad-Motoren ein. Nur aufrufen, während die Sperre gehalten wird."""
        if self.tempo <= 0:
            self.px.stop()
            return
        links, rechts = radgeschwindigkeiten(self.tempo / 100, self.lenkwinkel)
        self._motor_setzen(LINKER_MOTOR, links)
        self._motor_setzen(RECHTER_MOTOR, rechts)

    def _motor_setzen(self, motor, geschwindigkeit):
        """Ein Motor vorwärts mit geschwindigkeit (0 bis 1)."""
        drehrichtung = EINBAURICHTUNG[motor] * self.px.cali_dir_value[motor]
        if drehrichtung > 0:
            self.px.motor_direction_pins[motor].low()
        else:
            self.px.motor_direction_pins[motor].high()
        pwm = MINDEST_PWM + geschwindigkeit * (100 - MINDEST_PWM) if geschwindigkeit > 0 else 0
        self.px.motor_speed_pins[motor].pulse_width_percent(pwm)
