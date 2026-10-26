"""
extern.py – Spricht mit einem externen Trainings-Dienst (z. B. auf dem Mac, siehe mac_worker/).

Der Pi schickt die ausgewählten Fahrten als Archiv hin, fragt jede Sekunde den Fortschritt
ab und holt am Ende das fertige Modell. Nach außen verhält sich ExternesTraining genau wie
das Training im Kern – so funktionieren Fortschrittsbalken und Lernkurve unverändert.

Der Pi hat keinen anderen Zugang zum Mac als diesen Dienst (kein SSH).
"""

import io
import json
import tarfile
import tempfile
import threading
import time

import requests
import torch
from zeroconf import ServiceBrowser, Zeroconf

DIENST_TYP = "_picar-training._tcp.local."
TIMEOUT = 5            # Sekunden, die wir auf eine Antwort warten
STUECK = 256 * 1024    # so viele Bytes auf einmal hochladen


class Verbindungsfehler(Exception):
    """Der Dienst ist nicht erreichbar oder lehnt ab – mit einer verständlichen Meldung."""


# ----------------------------------------------------------------------
# Dienste im Netz finden und testen
# ----------------------------------------------------------------------

def dienste_suchen(sekunden=3):
    """Sucht per mDNS nach Trainings-Diensten im lokalen Netz. Ergebnis: Liste mit Name, Adresse, Port, Version."""
    gefunden = {}

    class Zuhoerer:
        def add_service(self, zc, typ, name):
            info = zc.get_service_info(typ, name, timeout=2000)
            if info and info.parsed_addresses():
                gefunden[name] = {
                    "name": name.removesuffix("." + typ),
                    "host": info.parsed_addresses()[0],
                    "port": info.port,
                    "version": info.properties.get(b"version", b"").decode(),
                }

        def update_service(self, zc, typ, name):
            self.add_service(zc, typ, name)

        def remove_service(self, zc, typ, name):
            gefunden.pop(name, None)

    zeroconf = Zeroconf()
    try:
        ServiceBrowser(zeroconf, DIENST_TYP, Zuhoerer())
        time.sleep(sekunden)
    finally:
        zeroconf.close()
    return list(gefunden.values())


def _anfrage(methode, konfig, pfad, **optionen):
    """Schickt eine Anfrage an den Dienst – mit Token – und übersetzt Fehler in verständliche Meldungen."""
    url = f"http://{konfig['host']}:{konfig['port']}{pfad}"
    kopf = {"Authorization": f"Bearer {konfig['token']}"}
    try:
        antwort = requests.request(methode, url, headers=kopf, timeout=optionen.pop("timeout", TIMEOUT), **optionen)
    except requests.ConnectionError:
        raise Verbindungsfehler(f"{konfig['host']}:{konfig['port']} ist nicht erreichbar.")
    except requests.Timeout:
        raise Verbindungsfehler(f"{konfig['host']}:{konfig['port']} antwortet nicht.")
    if antwort.status_code == 401:
        raise Verbindungsfehler("Das Token ist falsch.")
    if not antwort.ok:
        try:
            meldung = antwort.json().get("detail", antwort.text)
        except ValueError:
            meldung = antwort.text
        raise Verbindungsfehler(f"Der Dienst meldet: {meldung}")
    return antwort


def info_abfragen(konfig):
    """Fragt Name, Rechengerät und Code-Version des Dienstes ab („Verbindung testen“)."""
    if not konfig.get("host"):
        raise Verbindungsfehler("Kein Hostname bzw. keine IP-Adresse eingetragen.")
    info = _anfrage("GET", konfig, "/info").json()
    if info.get("dienst") != "picar-training":
        raise Verbindungsfehler("Unter dieser Adresse läuft kein PiCar-Trainings-Dienst.")
    return info


# ----------------------------------------------------------------------
# Training auf dem externen Rechner
# ----------------------------------------------------------------------

class ExternesTraining:
    """Training auf einem externen Rechner – mit derselben Bedienung wie kern.training.Training."""

    def __init__(self, konfig, pi_version):
        self.konfig = konfig
        self.pi_version = pi_version
        self.info = {}                 # Name, Gerät, Version des Dienstes
        self.laeuft = False
        self.text, self.fortschritt, self.kurven, self.fehler = "", 0.0, {}, None
        self.ergebnis_gewichte = None  # nach dem Training: die Gewichte (state_dict)
        self.ergebnis_meta = None      # ... und der Steckbrief
        self._auftrag = None
        self._abbrechen = False
        self._beenden = False

    def status(self):
        return {"laeuft": self.laeuft, "text": self.text, "fortschritt": round(self.fortschritt, 3),
                "kurven": self.kurven, "fehler": self.fehler, "fertig": self.ergebnis_gewichte is not None}

    def starten(self, fahrt_ordner, gruendlich, bei_ende=None, variante="B"):
        self.info = info_abfragen(self.konfig)   # wirft Verbindungsfehler, wenn nicht erreichbar
        if self.info.get("beschaeftigt"):
            raise Verbindungsfehler(f"{self.info['name']} trainiert gerade schon etwas anderes.")
        if variante not in self.info.get("varianten", ["B"]):   # ältere Dienste kennen nur Variante B
            raise Verbindungsfehler(f"{self.info['name']} kann Variante {variante} noch nicht – bitte dort "
                                    "„git pull“ ausführen und den Dienst neu starten.")
        self.laeuft, self._abbrechen, self._beenden, self._auftrag = True, False, False, None
        self.text, self.fortschritt, self.kurven, self.fehler = "Starte ...", 0.0, {}, None
        self.ergebnis_gewichte, self.ergebnis_meta = None, None
        threading.Thread(target=self._ausfuehren, args=(fahrt_ordner, gruendlich, bei_ende), daemon=True).start()

    def beenden(self):
        """Den Dienst bitten aufzuhören und das bisher beste Modell zu liefern."""
        self._beenden = True   # falls der Auftrag noch hochgeladen wird: gleich danach beenden
        if self._auftrag:
            _anfrage("POST", self.konfig, f"/auftraege/{self._auftrag}/beenden")

    def abbrechen(self):
        self._abbrechen = True
        if self._auftrag:
            _anfrage("POST", self.konfig, f"/auftraege/{self._auftrag}/abbrechen")

    # ------------------------------------------------------------------

    def _ausfuehren(self, fahrt_ordner, gruendlich, bei_ende):
        name = self.info.get("name", "externer Rechner")
        try:
            self._hochladen(fahrt_ordner, gruendlich, name)
            self._beobachten(name)
            if self.ergebnis_gewichte is not None and bei_ende:
                bei_ende(self)
        except Verbindungsfehler as fehler:
            if self._abbrechen:
                self.text = "Training abgebrochen."
            else:
                self.fehler = f"Problem mit {name}: {fehler}"
                self.text = "Fehler beim externen Training."
        except Exception as fehler:
            self.fehler = str(fehler)
            self.text = "Fehler beim externen Training."
            print("Fehler beim externen Training:", repr(fehler))
        finally:
            self.laeuft = False

    def _hochladen(self, fahrt_ordner, gruendlich, name):
        """Packt die Fahrten in ein Archiv und lädt es hoch (Fortschrittsbalken 0–5 %)."""
        self.text = "Packe die Fahrten ein ..."
        with tempfile.TemporaryFile() as archiv:
            with tarfile.open(fileobj=archiv, mode="w") as tar:   # ohne Kompression – JPEGs sind schon klein
                for ordner in fahrt_ordner:
                    tar.add(ordner / "meta.json", arcname=f"{ordner.name}/meta.json")
                    tar.add(ordner / "frames.csv", arcname=f"{ordner.name}/frames.csv")
                    tar.add(ordner / "bilder", arcname=f"{ordner.name}/bilder")
            groesse = archiv.tell()
            archiv.seek(0)

            def stuecke():
                gesendet = 0
                while daten := archiv.read(STUECK):
                    if self._abbrechen:
                        raise Verbindungsfehler("Abgebrochen.")
                    gesendet += len(daten)
                    self.fortschritt = 0.05 * gesendet / groesse
                    self.text = f"Übertrage {groesse / 1e6:.0f} MB zu {name}: {100 * gesendet / groesse:.0f} %"
                    yield daten

            einstellungen = json.dumps({"fahrten": [o.name for o in fahrt_ordner], "gruendlich": gruendlich,
                                        "pi_version": self.pi_version})
            antwort = _anfrage("POST", self.konfig, "/auftraege", params={"einstellungen": einstellungen},
                               data=stuecke(), timeout=120)
            self._auftrag = antwort.json()["auftrag"]
            if self._beenden:
                self.beenden()

    def _beobachten(self, name):
        """Fragt jede Sekunde den Fortschritt ab und übernimmt Text, Balken und Lernkurve (5–97 %)."""
        while True:
            time.sleep(1)
            status = _anfrage("GET", self.konfig, f"/auftraege/{self._auftrag}").json()
            self.kurven = status["kurven"]
            self.fortschritt = 0.05 + 0.92 * status["fortschritt"]
            self.text = f"{name} ({status['geraet'].upper()}): {status['text']}"
            if status["fehler"]:
                raise Verbindungsfehler(status["fehler"])
            if status["fertig"]:
                break
            if not status["laeuft"]:   # abgebrochen
                self.text = status["text"]
                _anfrage("DELETE", self.konfig, f"/auftraege/{self._auftrag}")
                return

        # Fertig: Modell und Steckbrief abholen (97–100 %)
        self.text = f"Hole das Modell von {name} ..."
        self.fortschritt = 0.97
        modell = _anfrage("GET", self.konfig, f"/auftraege/{self._auftrag}/modell", timeout=60).content
        self.ergebnis_gewichte = torch.load(io.BytesIO(modell), weights_only=True)
        self.ergebnis_meta = status["meta"]
        _anfrage("DELETE", self.konfig, f"/auftraege/{self._auftrag}")
        self.text = status["text"].replace("Fertig in", f"Fertig auf {name} in")
        self.fortschritt = 1.0
