"""
controller_koppeln.py – Koppelt den Nintendo Switch Pro Controller per Bluetooth mit dem Pi.

Gestartet wird das auf der Seite „Kalibrierung“ (Knopf „Controller koppeln“). Zum Ausprobieren
geht es auch direkt im Terminal:   .venv/bin/python controller_koppeln.py

Ablauf:
  1. Suchen: Der Pi sucht 45 Sekunden lang nach Bluetooth-Geräten. Währenddessen hält man
     am Controller die kleine SYNC-Taste (oben neben dem USB-C-Anschluss), bis die vier
     LEDs hin- und herlaufen. Dann ist der Controller „sichtbar“ und will gekoppelt werden.
  2. Kennt der Pi den gefundenen Controller schon, versucht er zuerst, ihn einfach zu
     verbinden – vielleicht reicht das. Erst wenn das nicht klappt, wird die alte Kopplung
     gelöscht: Eine veraltete Kopplung ist der häufigste Grund, warum die Verbindung scheitert.
  3. Koppeln („pair“), dem Controller vertrauen („trust“, dann darf er sich später selbst
     verbinden) und verbinden („connect“). Koppeln klappt manchmal erst beim zweiten Versuch.
  4. Warten, bis die Daten des Controllers wirklich ankommen (controller.py).

Für alles benutzen wir das Linux-Programm bluetoothctl.
"""

import re
import subprocess
import threading
import time

SUCHDAUER = 45         # Sekunden: so lange suchen wir nach einem Controller im Kopplungsmodus
NAME = "Pro Controller"
FARBCODES = re.compile(r"\x1b\[[0-9;]*m")   # bluetoothctl färbt seine Ausgabe – das entfernen wir


def bluetoothctl(*befehl, timeout=15):
    """Führt einen bluetoothctl-Befehl aus und gibt seine Ausgabe (ohne Farbcodes) zurück."""
    try:
        ergebnis = subprocess.run(["bluetoothctl", *befehl], capture_output=True, text=True, timeout=timeout)
        return FARBCODES.sub("", ergebnis.stdout + ergebnis.stderr)
    except subprocess.TimeoutExpired:
        return "Zeitüberschreitung"


def gefundene_controller():
    """Adressen aller Pro Controller, die der Pi gerade kennt – gekoppelt oder nur bei der Suche entdeckt."""
    adressen = []
    for zeile in bluetoothctl("devices").splitlines():
        teile = zeile.split(" ", 2)   # "Device E0:EF:BF:39:16:69 Pro Controller"
        if len(teile) == 3 and teile[0] == "Device" and teile[2].strip() == NAME:
            adressen.append(teile[1])
    return adressen


def ist_gekoppelt(adresse):
    """Ist dieser Controller wirklich mit dem Pi gekoppelt? (Nur entdeckt reicht nicht.)"""
    return "Paired: yes" in bluetoothctl("info", adresse)


def gekoppelte_controller():
    return [adresse for adresse in gefundene_controller() if ist_gekoppelt(adresse)]


class Kopplung:
    """Koppelt den Controller im Hintergrund und berichtet dabei, was gerade passiert."""

    def __init__(self, controller):
        self.controller = controller   # aus controller.py – daran sehen wir, ob Daten ankommen
        self.laeuft = False
        self.ergebnis = None           # None, "ok" oder "fehler"
        self.schritte = []             # Was bisher passiert ist (wird auf der Webseite angezeigt)
        self._abbrechen = False
        self._suche = None             # der laufende bluetoothctl-Suchvorgang

    def status(self):
        return {"laeuft": self.laeuft, "ergebnis": self.ergebnis, "schritte": self.schritte}

    def starten(self):
        if self.laeuft:
            return
        self.laeuft, self.ergebnis, self.schritte, self._abbrechen = True, None, [], False
        threading.Thread(target=self._ausfuehren, daemon=True).start()

    def abbrechen(self):
        self._abbrechen = True
        self._suche_beenden()   # beendet auch das Warten auf Meldungen der Suche

    # ------------------------------------------------------------------

    def _melden(self, text):
        print("Controller koppeln:", text)
        self.schritte.append(text)

    def _ausfuehren(self):
        try:
            erfolg = self._koppeln()
            self.ergebnis = "ok" if erfolg else "fehler"
        except Exception as fehler:   # unerwartete Probleme verständlich melden statt abzustürzen
            self._melden(f"Unerwarteter Fehler: {fehler}")
            self.ergebnis = "fehler"
        finally:
            self._suche_beenden()
            self.laeuft = False

    def _koppeln(self):
        # 1. Suchen
        self._melden("Suche läuft. Jetzt am Controller die kleine SYNC-Taste (oben, neben dem USB-C-Anschluss) "
                     "gedrückt halten, bis die vier LEDs hin- und herlaufen.")
        adresse = self._controller_finden()
        if adresse is None:
            return False
        self._melden(f"Controller gefunden: {adresse}")

        # 2. Schon gekoppelt? Dann erst einmal einfach verbinden – die Kopplung bleibt so erhalten
        if ist_gekoppelt(adresse):
            self._melden("Der Controller ist schon gekoppelt – versuche zuerst, ihn einfach zu verbinden ...")
            bluetoothctl("connect", adresse, timeout=20)
            if self._warten_auf(self.controller.verbunden, 8):
                self._melden("Verbunden – die Daten des Controllers kommen an. Fertig!")
                return True
            if self._abbrechen:
                return self._abgebrochen()
            # Die alte Kopplung ist wohl veraltet: löschen und neu suchen.
            # (Ein gelöschtes Gerät meldet Bluetooth erst in einer NEUEN Suche wieder.)
            self._suche_beenden()
            for alt in gekoppelte_controller():
                bluetoothctl("remove", alt)
            self._melden("Das hat nicht gereicht – alte Kopplung gelöscht, suche den Controller neu. "
                         "SYNC-Taste weiter gedrückt halten (bzw. noch einmal drücken).")
            adresse = self._controller_finden()
            if adresse is None:
                return False
            self._melden(f"Controller wieder gefunden: {adresse}")

        # 3. Koppeln, vertrauen, verbinden
        for versuch in range(1, 4):
            ausgabe = bluetoothctl("pair", adresse, timeout=25)
            if "Pairing successful" in ausgabe or "AlreadyExists" in ausgabe:
                break
            self._melden(f"Koppeln, Versuch {versuch}: hat nicht geklappt.")
            if self._abbrechen:
                return self._abgebrochen()
            time.sleep(2)
        else:
            self._melden("Koppeln fehlgeschlagen. SYNC-Taste weiter gedrückt halten und noch einmal versuchen.")
            return False
        self._melden("Gekoppelt.")
        bluetoothctl("trust", adresse)
        self._suche_beenden()   # die Suche stört beim Verbinden nur

        # 4. Verbinden und warten, bis Daten ankommen
        for versuch in range(1, 4):
            bluetoothctl("connect", adresse, timeout=20)
            if self._warten_auf(self.controller.verbunden, 8):
                self._melden("Verbunden – die Daten des Controllers kommen an. Fertig! "
                             "Ab jetzt reicht nach dem Einschalten ein Druck auf eine Taste (z. B. Home).")
                return True
            self._melden(f"Verbinden, Versuch {versuch}: noch keine Daten vom Controller.")
            if self._abbrechen:
                return self._abgebrochen()
        self._melden("Gekoppelt, aber nicht verbunden. Eine Taste am Controller drücken (z. B. Home) – "
                     "dann sollte er sich von selbst verbinden.")
        return False

    def _controller_finden(self):
        """Startet die Suche und wartet, bis ein Pro Controller im Kopplungsmodus auftaucht."""
        bekannte = set(gekoppelte_controller())
        self._suche = subprocess.Popen(["bluetoothctl", "--timeout", str(SUCHDAUER), "scan", "on"],
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        ende = time.monotonic() + SUCHDAUER
        for zeile in self._suche.stdout:   # jede Zeile ist eine Meldung der Suche
            zeile = FARBCODES.sub("", zeile).strip()
            # Ein neues Gerät:            "[NEW] Device E0:EF:BF:39:16:69 Pro Controller"
            # Ein bekanntes, jetzt in Funkreichweite und sichtbar: "[CHG] Device E0:EF:... RSSI: -58"
            treffer = re.match(r"\[(NEW|CHG)\] Device ([0-9A-F:]{17}) (.*)", zeile)
            if treffer:
                art, adresse, rest = treffer.groups()
                neu_entdeckt = art == "NEW" and rest.strip() == NAME
                name_nachgeliefert = art == "CHG" and rest.strip() in (f"Name: {NAME}", f"Alias: {NAME}")
                gekoppelt_und_sichtbar = art == "CHG" and adresse in bekannte and "RSSI" in rest
                if neu_entdeckt or name_nachgeliefert or gekoppelt_und_sichtbar:
                    return adresse
            if self._abbrechen or time.monotonic() > ende:
                break
        if self._abbrechen:
            self._abgebrochen()
            return None
        self._melden(f"In {SUCHDAUER} Sekunden wurde kein Controller im Kopplungsmodus gefunden. "
                     "Laufen die vier LEDs hin und her? Dann noch einmal versuchen.")
        return None

    def _warten_auf(self, bedingung, sekunden):
        """Wartet höchstens so viele Sekunden, bis bedingung() wahr ist."""
        ende = time.monotonic() + sekunden
        while time.monotonic() < ende and not self._abbrechen:
            if bedingung():
                return True
            time.sleep(0.5)
        return False

    def _suche_beenden(self):
        suche, self._suche = self._suche, None
        if suche is not None and suche.poll() is None:
            suche.terminate()
            suche.wait(timeout=5)
            bluetoothctl("scan", "off")

    def _abgebrochen(self):
        self._melden("Abgebrochen.")
        return False


# Zum Ausprobieren im Terminal (die Weboberfläche darf dabei nicht laufen)
if __name__ == "__main__":
    from controller import Controller
    kopplung = Kopplung(Controller())
    kopplung.starten()
    gezeigt = 0
    while kopplung.laeuft or gezeigt < len(kopplung.schritte):
        while gezeigt < len(kopplung.schritte):
            print("  ", kopplung.schritte[gezeigt])
            gezeigt += 1
        time.sleep(0.3)
    print("Ergebnis:", kopplung.ergebnis)
