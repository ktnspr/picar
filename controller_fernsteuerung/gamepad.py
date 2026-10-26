"""
gamepad.py – Liest den Nintendo Switch Pro Controller über Bluetooth aus.

Linux meldet jede Änderung am Controller als „Ereignis“: welche Art (Taste oder
Achse), welche Taste/Achse (Code) und der neue Wert. Wir lesen diese Ereignisse
direkt aus den Gerätedateien in /dev/input – dafür braucht es kein Zusatzpaket.

Der Controller erscheint unter Linux als zwei Geräte:
  - „Pro Controller“        Tasten und Sticks
  - „Pro Controller (IMU)“  Bewegungssensor; schickt ständig Messwerte

Den Bewegungssensor nutzen wir als Lebenszeichen: Solange seine Messwerte
ankommen, ist der Controller in Reichweite.

Zum Ausprobieren direkt starten:   python3 gamepad.py
"""

import select
import struct
import threading
import time

# So ist ein Ereignis aufgebaut (24 Bytes): Zeit (2 Zahlen), Art, Code, Wert
EREIGNIS_FORMAT = "llHHi"
EREIGNIS_GROESSE = struct.calcsize(EREIGNIS_FORMAT)
ART_TASTE = 1
ART_ACHSE = 3

# Linux-Codes der Tasten → Namen wie auf dem Controller
TASTEN = {
    0x130: "B",        # BTN_SOUTH – die untere Taste
    0x131: "A",        # BTN_EAST  – die rechte Taste
    0x133: "X",        # BTN_NORTH – die obere Taste
    0x134: "Y",        # BTN_WEST  – die linke Taste
    0x135: "CAPTURE",
    0x136: "L",
    0x137: "R",
    0x138: "ZL",
    0x139: "ZR",
    0x13A: "MINUS",
    0x13B: "PLUS",
    0x13C: "HOME",
    0x13D: "L-STICK",  # linken Stick hineindrücken
    0x13E: "R-STICK",
}

# Linux-Codes der Achsen → Namen
ACHSEN = {
    0x00: "LX",  # linker Stick links/rechts
    0x01: "LY",  # linker Stick hoch/runter
    0x03: "RX",  # rechter Stick links/rechts
    0x04: "RY",  # rechter Stick hoch/runter
}
STICK_MAX = 32767      # so weit melden die Sticks maximal
STICK_TOTZONE = 0.1    # kleine Bewegungen um die Mitte herum ignorieren

# Das Steuerkreuz meldet sich als zwei Achsen mit den Werten -1, 0 oder 1.
# Wir machen daraus vier Tasten.
STEUERKREUZ_X = 0x10
STEUERKREUZ_Y = 0x11

# Kommt so lange nichts vom Controller, gilt er als nicht verbunden.
VERBINDUNG_TIMEOUT = 0.3  # Sekunden


def geraete_finden():
    """Sucht die Gerätedateien des Pro Controllers. Ergebnis: (tasten, imu) oder None."""
    gefunden = {}
    with open("/proc/bus/input/devices") as datei:
        # Die Datei besteht aus Blöcken, einer pro Gerät, getrennt durch Leerzeilen.
        for block in datei.read().split("\n\n"):
            name = ""
            ereignis_datei = ""
            for zeile in block.splitlines():
                if zeile.startswith("N: Name="):
                    name = zeile.split("=", 1)[1].strip('"')
                if zeile.startswith("H: Handlers="):
                    for handler in zeile.split("=", 1)[1].split():
                        if handler.startswith("event"):
                            ereignis_datei = "/dev/input/" + handler
            gefunden[name] = ereignis_datei
    if "Pro Controller" in gefunden and "Pro Controller (IMU)" in gefunden:
        return gefunden["Pro Controller"], gefunden["Pro Controller (IMU)"]
    return None


class Gamepad:
    def __init__(self):
        self.gedrueckt = set()           # Namen der Tasten, die gerade gedrückt sind
        self.achsen = {}                 # Name der Achse → Wert von -1 bis 1
        self._neu_gedrueckt = []         # Tasten, die seit der letzten Abfrage gedrückt wurden
        self._letztes_lebenszeichen = 0.0
        self._sperre = threading.Lock()
        threading.Thread(target=self._lesen, daemon=True).start()

    def verbunden(self):
        return time.monotonic() - self._letztes_lebenszeichen < VERBINDUNG_TIMEOUT

    def achse(self, name):
        """Stellung eines Sticks von -1 bis 1 (0 = Mitte)."""
        return self.achsen.get(name, 0.0)

    def neu_gedrueckte_tasten(self):
        """Alle Tasten, die seit dem letzten Aufruf gedrückt wurden (jede nur einmal)."""
        with self._sperre:
            tasten = self._neu_gedrueckt
            self._neu_gedrueckt = []
        return tasten

    # ------------------------------------------------------------------

    def _lesen(self):
        """Läuft im Hintergrund: verbindet sich mit dem Controller und liest seine Ereignisse."""
        while True:
            geraete = geraete_finden()
            if geraete is None:
                time.sleep(1)  # Controller (noch) nicht da – später nochmal schauen
                continue
            try:
                with open(geraete[0], "rb") as tasten_datei, open(geraete[1], "rb") as imu_datei:
                    while True:
                        bereit, _, _ = select.select([tasten_datei, imu_datei], [], [], 1.0)
                        if imu_datei in bereit:
                            imu_datei.read(EREIGNIS_GROESSE)
                            self._letztes_lebenszeichen = time.monotonic()
                        if tasten_datei in bereit:
                            self._ereignis_verarbeiten(tasten_datei.read(EREIGNIS_GROESSE))
            except OSError:
                pass  # Controller ist weg (ausgeschaltet oder außer Reichweite)
            # Nach dem Verbindungsabbruch ist nichts mehr gedrückt.
            self.gedrueckt.clear()
            self.achsen.clear()

    def _ereignis_verarbeiten(self, daten):
        _, _, art, code, wert = struct.unpack(EREIGNIS_FORMAT, daten)

        if art == ART_TASTE and code in TASTEN:
            self._taste_setzen(TASTEN[code], wert == 1)

        elif art == ART_ACHSE and code in ACHSEN:
            stellung = wert / STICK_MAX
            if abs(stellung) < STICK_TOTZONE:
                stellung = 0.0
            self.achsen[ACHSEN[code]] = max(-1.0, min(1.0, stellung))

        elif art == ART_ACHSE and code == STEUERKREUZ_X:
            self._taste_setzen("LINKS", wert < 0)
            self._taste_setzen("RECHTS", wert > 0)

        elif art == ART_ACHSE and code == STEUERKREUZ_Y:
            self._taste_setzen("HOCH", wert < 0)
            self._taste_setzen("RUNTER", wert > 0)

    def _taste_setzen(self, name, gedrueckt):
        if gedrueckt and name not in self.gedrueckt:
            self.gedrueckt.add(name)
            with self._sperre:
                self._neu_gedrueckt.append(name)
        elif not gedrueckt:
            self.gedrueckt.discard(name)


# Selbsttest: zeigt an, was am Controller passiert
if __name__ == "__main__":
    gamepad = Gamepad()
    print("Drück Tasten und bewege die Sticks (Beenden mit Strg+C) ...")
    war_verbunden = None
    try:
        while True:
            if gamepad.verbunden() != war_verbunden:
                war_verbunden = gamepad.verbunden()
                print("Controller verbunden" if war_verbunden else "Controller NICHT verbunden")
            for taste in gamepad.neu_gedrueckte_tasten():
                print("Taste:", taste)
            sticks = "  ".join(f"{n}={gamepad.achse(n):+.2f}" for n in ACHSEN.values())
            print(sticks, end="\r")
            time.sleep(0.05)
    except KeyboardInterrupt:
        print()
