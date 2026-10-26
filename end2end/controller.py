"""
controller.py – Liest den Nintendo Switch Pro Controller mit der Bibliothek evdev.

Linux meldet jede Änderung am Controller als „Ereignis“ (z. B. „Taste A gedrückt“
oder „linker Stick steht jetzt bei 12000“). evdev liest diese Ereignisse für uns.

Der Controller erscheint als zwei Geräte:
  - „Pro Controller“        Tasten und Sticks
  - „Pro Controller (IMU)“  Bewegungssensor, schickt ständig Messwerte
Solange die Messwerte des Bewegungssensors ankommen, ist der Controller in Reichweite.

Zum Ausprobieren direkt starten:   .venv/bin/python controller.py
"""

import select
import threading
import time

import evdev
from evdev import ecodes

# Linux-Tastencodes → Namen wie auf dem Controller
TASTEN = {
    ecodes.BTN_EAST: "A",       # rechte Taste
    ecodes.BTN_SOUTH: "B",      # untere Taste
    ecodes.BTN_NORTH: "X",
    ecodes.BTN_WEST: "Y",
    ecodes.BTN_TL: "L",
    ecodes.BTN_TR: "R",
    ecodes.BTN_TL2: "ZL",
    ecodes.BTN_TR2: "ZR",
    ecodes.BTN_SELECT: "MINUS",
    ecodes.BTN_START: "PLUS",
    ecodes.BTN_MODE: "HOME",
}
STICK_MAX = 32767
STICK_TOTZONE = 0.08        # kleine Bewegungen um die Mitte ignorieren
VERBINDUNG_TIMEOUT = 0.3    # Sekunden ohne Daten → Controller gilt als getrennt


def geraete_finden():
    """Sucht die beiden Geräte des Pro Controllers. Ergebnis: (tasten, imu) oder None."""
    geraete = {}
    for pfad in evdev.list_devices():
        geraet = evdev.InputDevice(pfad)
        geraete[geraet.name] = geraet
    if "Pro Controller" in geraete and "Pro Controller (IMU)" in geraete:
        return geraete["Pro Controller"], geraete["Pro Controller (IMU)"]
    return None


class Controller:
    def __init__(self):
        self.gedrueckt = set()      # Tasten, die gerade gedrückt sind
        self.lenkung = 0.0          # linker Stick links/rechts: -1 bis 1
        self._neu_gedrueckt = []    # Tasten, die seit der letzten Abfrage gedrückt wurden
        self._letztes_lebenszeichen = 0.0
        self._sperre = threading.Lock()
        threading.Thread(target=self._lesen, daemon=True).start()

    def verbunden(self):
        return time.monotonic() - self._letztes_lebenszeichen < VERBINDUNG_TIMEOUT

    def neu_gedrueckte_tasten(self):
        """Alle Tasten, die seit dem letzten Aufruf gedrückt wurden – jede nur einmal."""
        with self._sperre:
            tasten, self._neu_gedrueckt = self._neu_gedrueckt, []
        return tasten

    def _lesen(self):
        """Läuft im Hintergrund: verbindet sich mit dem Controller und liest seine Ereignisse."""
        while True:
            geraete = geraete_finden()
            if geraete is None:
                time.sleep(1)   # noch kein Controller da – später nochmal schauen
                continue
            tasten_geraet, imu_geraet = geraete
            try:
                while True:
                    bereit, _, _ = select.select([tasten_geraet, imu_geraet], [], [], 1.0)
                    if imu_geraet in bereit:
                        for _ in imu_geraet.read():
                            pass   # Inhalt egal – Hauptsache, es kommt etwas an
                        self._letztes_lebenszeichen = time.monotonic()
                    if tasten_geraet in bereit:
                        for ereignis in tasten_geraet.read():
                            self._verarbeiten(ereignis)
            except OSError:
                pass   # Controller ausgeschaltet oder außer Reichweite
            self.gedrueckt.clear()
            self.lenkung = 0.0

    def _verarbeiten(self, ereignis):
        if ereignis.type == ecodes.EV_KEY and ereignis.code in TASTEN:
            name = TASTEN[ereignis.code]
            if ereignis.value == 1:
                self.gedrueckt.add(name)
                with self._sperre:
                    self._neu_gedrueckt.append(name)
            elif ereignis.value == 0:
                self.gedrueckt.discard(name)
        elif ereignis.type == ecodes.EV_ABS and ereignis.code == ecodes.ABS_X:
            stellung = ereignis.value / STICK_MAX
            self.lenkung = 0.0 if abs(stellung) < STICK_TOTZONE else max(-1.0, min(1.0, stellung))


# Selbsttest: zeigt an, was am Controller passiert
if __name__ == "__main__":
    controller = Controller()
    print("Tasten drücken und den linken Stick bewegen (Beenden mit Strg+C) ...")
    try:
        while True:
            for taste in controller.neu_gedrueckte_tasten():
                print("\nTaste:", taste)
            status = "verbunden" if controller.verbunden() else "NICHT verbunden"
            print(f"Controller {status:16}  Lenkung {controller.lenkung:+.2f}", end="\r")
            time.sleep(0.05)
    except KeyboardInterrupt:
        print()
