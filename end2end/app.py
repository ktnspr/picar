"""
app.py – Webserver und Steuerzentrale für das End-to-End-Projekt.

Start:   ./start.sh      (oder:  .venv/bin/python app.py)
Dann im Browser auf dem Notebook öffnen:   http://<IP-Adresse-des-Pi>:8080

Die Weboberfläche kennt drei Modi – Daten aufnehmen, Trainieren, Autonom fahren –
und eine eigene Seite zum Kalibrieren.
"""

import logging
import signal
import subprocess
import sys
import threading
import time

import cv2
import torch
from flask import Flask, Response, jsonify, render_template, request, send_file

import extern
import fahrten
import konfiguration
import modelle
from controller import Controller
from einstellungen import AUSSCHNITT_OBEN, KAMERA_NEIGEN_STANDARD, LENKUNG_MAX, PORT, TEMPO_STANDARD
from kamera import Kamera, overlay_zeichnen
from kern.netz import lenkwinkel_vorhersagen
from kern.version import code_version
from kern.vorverarbeitung import netz_ausschnitt

# Kommt so lange keine Anfrage der Weboberfläche, werden die Motoren ausgeschaltet
# (Seite geschlossen, Notebook zugeklappt, WLAN weg).
BROWSER_TIMEOUT = 1.5  # Sekunden
LIVEBILD_RATE = 15     # Bilder pro Sekunde für das Livebild im Browser

MODI = ("aufnahme", "training", "autonom", "kalibrierung")


# ----------------------------------------------------------------------
# Start: Läuft schon ein anderes Kamera-Programm?
# ----------------------------------------------------------------------

def andere_kamera_programme():
    """Sucht nach den Fernsteuer-Programmen aus dem anderen Projekt."""
    gefunden = subprocess.run(["pgrep", "-af", "server.py|controller_fahren.py|vilib"],
                              capture_output=True, text=True).stdout
    return [zeile for zeile in gefunden.splitlines() if "pgrep" not in zeile]


def kamera_starten():
    andere = andere_kamera_programme()
    try:
        return Kamera()
    except (RuntimeError, IndexError) as fehler:
        hinweis = "\nDie Kamera ist belegt oder nicht erreichbar.\n"
        if andere:
            hinweis += ("Es läuft noch ein anderes Programm, das die Kamera benutzt:\n    "
                        + "\n    ".join(andere)
                        + "\nBitte dieses Programm zuerst beenden (dort Strg+C drücken).\n")
        raise SystemExit(hinweis + f"(Fehlermeldung: {fehler})")


kamera = kamera_starten()

from fahrzeug import Fahrzeug  # noqa: E402 – erst nach der Kamera-Prüfung die Hardware übernehmen
from trainingssteuerung import Trainingssteuerung  # noqa: E402

fahrzeug = Fahrzeug()
controller = Controller()
aufnahme = fahrten.Aufnahme()
training = Trainingssteuerung()
app = Flask(__name__)

ROT = (40, 40, 230)      # Farben für das Overlay (OpenCV: Blau, Grün, Rot)
GRUEN = (0, 220, 0)
GELB = (0, 200, 240)

# Der gemeinsame Zustand, den Weboberfläche und Hauptschleife lesen und ändern
zustand = {
    "modus": "aufnahme",
    "tempo": TEMPO_STANDARD,     # eingestellte Geschwindigkeit in Prozent
    "ausschnitt_oben": AUSSCHNITT_OBEN,   # ab welcher Bildhöhe das Netz das Bild sieht (0 bis 1)
    "akku_volt": None,
    "temperatur": None,          # CPU-Temperatur in °C
    "drosselt": False,           # senkt der Pi gerade wegen Hitze seinen Takt?
    "anzeige_lenkwinkel": None,  # Lenkwinkel für das Overlay im Livebild
    "anzeige_text": "",
    "anzeige_farbe": (0, 220, 0),
}
letzte_browser_anfrage = time.monotonic()

# Zustand des autonomen Fahrens
autonom = {
    "modell_id": None,
    "netz": None,
    "meta": None,
    "faehrt": False,          # soll das Auto gerade autonom fahren?
    "lenkwinkel": None,       # letzte Vorhersage des Netzes (Grad)
    "rechenzeit_ms": None,    # so lange braucht das Netz für ein Bild
    "rate": None,             # Lenkentscheidungen pro Sekunde
}


# ----------------------------------------------------------------------
# Seiten und Livebild
# ----------------------------------------------------------------------

@app.route("/")
def startseite():
    return render_template("index.html")


@app.route("/kalibrierung")
def kalibrierseite():
    return render_template("kalibrierung.html")


@app.route("/video")
def video():
    def bilder():
        nummer = 0
        while True:
            nummer, bild = kamera.naechstes_bild(nummer)
            if bild is None:
                continue
            bild = overlay_zeichnen(bild, zustand["anzeige_lenkwinkel"], zustand["anzeige_text"],
                                    zustand["anzeige_farbe"], zustand["ausschnitt_oben"])
            ok, jpeg = cv2.imencode(".jpg", bild, [cv2.IMWRITE_JPEG_QUALITY, 80])
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
            time.sleep(1 / LIVEBILD_RATE)
    return Response(bilder(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/netzbild.jpg")
def netzbild():
    """Genau das Bild, das ins Netz geht (48×160) – zum Ansehen dreifach vergrößert."""
    _, bild = kamera.naechstes_bild(0)
    klein = netz_ausschnitt(bild, zustand["ausschnitt_oben"])
    gross = cv2.resize(klein, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)  # Pixel sichtbar lassen
    ok, jpeg = cv2.imencode(".jpg", gross, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return Response(jpeg.tobytes(), mimetype="image/jpeg", headers={"Cache-Control": "no-store"})


# ----------------------------------------------------------------------
# Allgemeine Befehle
# ----------------------------------------------------------------------

@app.get("/api/zustand")
def zustand_abfragen():
    """Die Weboberfläche fragt das zweimal pro Sekunde ab – das ist zugleich ihr Lebenszeichen."""
    global letzte_browser_anfrage
    letzte_browser_anfrage = time.monotonic()
    return jsonify({
        "modus": zustand["modus"],
        "tempo": zustand["tempo"],
        "ausschnitt_oben": zustand["ausschnitt_oben"],
        "akku_volt": zustand["akku_volt"],
        "temperatur": zustand["temperatur"],
        "drosselt": zustand["drosselt"],
        "motoren_frei": fahrzeug.motoren_frei,
        "motoren_gesperrt": fahrzeug.motoren_gesperrt,
        "faehrt": fahrzeug.faehrt(),
        "lenkwinkel": fahrzeug.lenkwinkel,
        "schwenken": fahrzeug.schwenken,
        "neigen": fahrzeug.neigen,
        "controller_verbunden": controller.verbunden(),
        "training_laeuft": training.laeuft,
        "autonom": {
            "modell_id": autonom["modell_id"],
            "modell_name": autonom["meta"]["anzeigename"] if autonom["meta"] else None,
            "faehrt": autonom["faehrt"],
            "lenkwinkel": autonom["lenkwinkel"],
            "rechenzeit_ms": autonom["rechenzeit_ms"],
            "rate": autonom["rate"],
        },
        "aufnahme": {
            "laeuft": aufnahme.laeuft,
            "pausiert": aufnahme.pausiert,
            "bilder": aufnahme.anzahl,
            "dauer_s": round(aufnahme.dauer(), 1),
        },
    })


@app.post("/api/motoren")
def motoren_schalten():
    fahrzeug.motoren_freigeben(bool(request.json["frei"]))
    return zustand_abfragen()


@app.post("/api/modus")
def modus_wechseln():
    neuer_modus = request.json["modus"]
    if neuer_modus not in MODI:
        return jsonify({"fehler": f"Unbekannter Modus: {neuer_modus}"}), 400
    if training.laeuft and neuer_modus != "training":
        return jsonify({"fehler": "Es läuft noch ein Training. Bitte warten oder abbrechen."}), 409
    fahrzeug.anhalten()   # Beim Moduswechsel hält das Auto immer an.
    # Während des Trainings sind die Motoren gesperrt.
    fahrzeug.motoren_sperren(neuer_modus == "training")
    aufnahme.stoppen()    # Eine laufende Aufnahme wird beendet
    autonom["faehrt"] = False   # und das autonome Fahren auch.
    controller.neu_gedrueckte_tasten()   # alte Tastendrücke verwerfen – sie gehören zum alten Modus
    if neuer_modus == "autonom" and autonom["meta"]:
        # Zurück im Autonom-Modus: wieder die Einstellungen des gewählten Modells verwenden
        fahrzeug.kamera_ausrichten(autonom["meta"]["kamera"]["schwenken"], autonom["meta"]["kamera"]["neigen"])
        zustand["ausschnitt_oben"] = autonom["meta"]["ausschnitt_oben"]
    if zustand["modus"] == "kalibrierung" and neuer_modus != "kalibrierung":
        # Die Kalibrier-Vorschau hat die Servos direkt bewegt. Jetzt wieder die
        # eingestellten Winkel anfahren – sonst stimmt der gespeicherte Kamerawinkel nicht.
        fahrzeug.lenken(0)
        fahrzeug.kamera_ausrichten(fahrzeug.schwenken, fahrzeug.neigen)
    zustand["modus"] = neuer_modus
    zustand["anzeige_lenkwinkel"] = None
    zustand["anzeige_text"] = ""
    return zustand_abfragen()


@app.post("/api/tempo")
def tempo_setzen():
    zustand["tempo"] = max(0, min(100, int(request.json["tempo"])))
    if fahrzeug.faehrt():
        fahrzeug.fahren(zustand["tempo"])   # wirkt sofort, auch während der Fahrt
    return zustand_abfragen()


@app.post("/api/kamera")
def kamera_ausrichten():
    if aufnahme.laeuft:
        # Der Kamerawinkel gehört zu den Daten einer Fahrt und muss gleich bleiben.
        return jsonify({"fehler": "Während einer Aufnahme kann die Kamera nicht bewegt werden."}), 409
    fahrzeug.kamera_ausrichten(float(request.json["schwenken"]), float(request.json["neigen"]))
    return zustand_abfragen()


@app.post("/api/ausschnitt")
def ausschnitt_setzen():
    if aufnahme.laeuft:
        return jsonify({"fehler": "Während einer Aufnahme kann der Bildausschnitt nicht geändert werden."}), 409
    zustand["ausschnitt_oben"] = max(0.0, min(0.75, float(request.json["ausschnitt_oben"])))
    return zustand_abfragen()


# ----------------------------------------------------------------------
# Modus 1: Daten aufnehmen
# ----------------------------------------------------------------------

def aufnahme_umschalten():
    if aufnahme.laeuft:
        aufnahme.stoppen()
        print(f"Aufnahme beendet: {aufnahme.anzahl} Bilder.")
    elif zustand["modus"] == "aufnahme":
        aufnahme.starten(zustand["tempo"], fahrzeug.schwenken, fahrzeug.neigen, zustand["ausschnitt_oben"])
        print(f"Aufnahme gestartet: {aufnahme.ordner.name}")


def pause_umschalten():
    aufnahme.pause_umschalten()
    if aufnahme.pausiert:
        fahrzeug.anhalten()


@app.post("/api/aufnahme")
def aufnahme_steuern():
    aktion = request.json["aktion"]
    if aktion == "umschalten":
        aufnahme_umschalten()
    elif aktion == "pause":
        pause_umschalten()
    return zustand_abfragen()


@app.get("/api/fahrten")
def fahrten_auflisten():
    return jsonify(fahrten.alle_fahrten())


@app.post("/api/fahrten/<fahrt_id>/umbenennen")
def fahrt_umbenennen(fahrt_id):
    fahrten.umbenennen(fahrt_id, request.json["name"])
    return jsonify(ok=True)


@app.post("/api/fahrten/<fahrt_id>/loeschen")
def fahrt_loeschen(fahrt_id):
    if aufnahme.laeuft and aufnahme.ordner.name == fahrt_id:
        return jsonify({"fehler": "Diese Fahrt wird gerade aufgenommen."}), 409
    fahrten.loeschen(fahrt_id)
    return jsonify(ok=True)


@app.get("/fahrten/<fahrt_id>/vorschau.jpg")
def fahrt_vorschau(fahrt_id):
    bild = fahrten.vorschaubild(fahrt_id)
    if bild is None:
        return "", 404
    return send_file(bild, mimetype="image/jpeg")


# ----------------------------------------------------------------------
# Modus 2: Trainieren
# ----------------------------------------------------------------------

@app.post("/api/training/start")
def training_starten():
    if zustand["modus"] != "training":
        return jsonify({"fehler": "Bitte zuerst in den Modus „Trainieren“ wechseln."}), 409
    if fahrzeug.faehrt():
        return jsonify({"fehler": "Trainieren geht nur, wenn das Fahrzeug steht."}), 409
    training.starten(request.json["fahrten"], bool(request.json["gruendlich"]), request.json.get("ort", "pi"))
    return jsonify(training.status())


# ----------------------------------------------------------------------
# Externe Trainingsressource (z. B. ein Mac mit dem Dienst aus mac_worker/)
# ----------------------------------------------------------------------

def extern_fuer_browser(einstellung):
    """Die Einstellung für die Weboberfläche – das Token selbst verraten wir nicht."""
    return {k: v for k, v in einstellung.items() if k != "token"} | {"token_gesetzt": bool(einstellung["token"])}


def extern_aus_anfrage(daten):
    """Einstellung aus der Anfrage; ein leeres Token-Feld heißt: das gespeicherte behalten."""
    gespeichert = konfiguration.laden()["extern"]
    return {
        "aktiv": bool(daten.get("aktiv", gespeichert["aktiv"])),
        "name": str(daten.get("name", gespeichert["name"])).strip(),
        "host": str(daten.get("host", gespeichert["host"])).strip(),
        "port": int(daten.get("port") or gespeichert["port"]),
        "token": str(daten.get("token") or "").strip() or gespeichert["token"],
    }


@app.get("/api/extern")
def extern_lesen():
    return jsonify(extern_fuer_browser(konfiguration.laden()["extern"]) | {"pi_version": code_version()})


@app.post("/api/extern")
def extern_speichern():
    konfig = konfiguration.laden()
    konfig["extern"] = extern_aus_anfrage(request.json)
    konfiguration.speichern(konfig)
    return jsonify(extern_fuer_browser(konfig["extern"]))


@app.post("/api/extern/suchen")
def extern_suchen():
    """Sucht 3 Sekunden lang per mDNS nach Trainings-Diensten im Netz."""
    return jsonify(extern.dienste_suchen(3))


@app.post("/api/extern/testen")
def extern_testen():
    """Verbindung testen: erreichbar? welches Gerät? passt die Code-Version?"""
    einstellung = extern_aus_anfrage(request.json)
    try:
        info = extern.info_abfragen(einstellung)
    except extern.Verbindungsfehler as fehler:
        return jsonify({"erreichbar": False, "meldung": str(fehler)})
    pi_version = code_version()
    warnung = None
    if info["version"] != pi_version:
        warnung = (f"Andere Code-Version: extern {info['version']}, Pi {pi_version}. "
                   "Bitte auf beiden Seiten denselben Stand verwenden (git pull).")
    return jsonify({"erreichbar": True, "info": info, "pi_version": pi_version, "warnung": warnung})


@app.post("/api/training/abbrechen")
def training_abbrechen():
    training.abbrechen()      # verwerfen
    return jsonify(training.status())


@app.post("/api/training/beenden")
def training_beenden():
    training.beenden()        # aufhören und das bisher beste Modell speichern
    return jsonify(training.status())


@app.get("/api/training/status")
def training_status():
    return jsonify(training.status())


@app.get("/api/modelle")
def modelle_auflisten():
    return jsonify(modelle.alle_modelle())


@app.get("/api/modelle/<modell_id>/lernkurve")
def modell_lernkurve(modell_id):
    return jsonify(modelle.lernkurve(modell_id))


@app.post("/api/modelle/<modell_id>/umbenennen")
def modell_umbenennen(modell_id):
    modelle.umbenennen(modell_id, request.json["name"])
    return jsonify(ok=True)


@app.post("/api/modelle/<modell_id>/loeschen")
def modell_loeschen(modell_id):
    modelle.loeschen(modell_id)
    return jsonify(ok=True)


# ----------------------------------------------------------------------
# Modus 3: Autonom fahren
# ----------------------------------------------------------------------

@app.post("/api/autonom/modell")
def autonom_modell_waehlen():
    """Lädt ein Modell und stellt Kamera, Bildausschnitt und Tempo wie in seinen Trainingsdaten ein."""
    if zustand["modus"] != "autonom":
        return jsonify({"fehler": "Bitte zuerst in den Modus „Autonom fahren“ wechseln."}), 409
    netz, meta = modelle.laden(request.json["modell"])
    autonom.update(faehrt=False, netz=netz, meta=meta, modell_id=request.json["modell"], lenkwinkel=None)
    fahrzeug.anhalten()
    fahrzeug.kamera_ausrichten(meta["kamera"]["schwenken"], meta["kamera"]["neigen"])
    zustand["ausschnitt_oben"] = meta["ausschnitt_oben"]
    zustand["tempo"] = meta["tempo"]
    torch.set_num_threads(2)   # für ein einzelnes Bild reichen 2 Rechenkerne
    return zustand_abfragen()


@app.post("/api/autonom/fahren")
def autonom_fahren():
    if request.json["an"]:
        if autonom["netz"] is None:
            return jsonify({"fehler": "Bitte zuerst ein Modell auswählen."}), 409
        if not fahrzeug.motoren_frei:
            return jsonify({"fehler": "Bitte zuerst die Motoren einschalten (Schalter oben rechts)."}), 409
        autonom["faehrt"] = True
    else:
        autonom["faehrt"] = False
        fahrzeug.anhalten()
    return zustand_abfragen()


def autonom_schritt(bild):
    """Ein Takt im Autonom-Modus: Das Netz schaut aufs Bild und lenkt."""
    # Controller (falls verbunden): A = Start/Stopp, B = Notstopp
    for taste in controller.neu_gedrueckte_tasten():
        if taste == "B":
            autonom["faehrt"] = False
        elif taste == "A" and autonom["netz"] is not None and fahrzeug.motoren_frei:
            autonom["faehrt"] = not autonom["faehrt"]

    if autonom["netz"] is None:
        zustand["anzeige_lenkwinkel"] = None
        zustand["anzeige_text"], zustand["anzeige_farbe"] = "Kein Modell gewaehlt", GELB
        return

    # Das Netz sagt den Lenkwinkel vorher – und wir messen, wie lange das dauert
    start = time.perf_counter()
    lenkwinkel = lenkwinkel_vorhersagen(autonom["netz"], netz_ausschnitt(bild, zustand["ausschnitt_oben"]))
    autonom["rechenzeit_ms"] = round((time.perf_counter() - start) * 1000, 1)
    jetzt = time.monotonic()
    if autonom.get("letzter_takt"):
        rate = 1 / (jetzt - autonom["letzter_takt"])
        autonom["rate"] = round(0.9 * (autonom["rate"] or rate) + 0.1 * rate, 1)   # geglättet
    autonom["letzter_takt"] = jetzt
    autonom["lenkwinkel"] = round(lenkwinkel, 1)

    # Lenken – auch im Stand, so kann man die Vorhersage gefahrlos ausprobieren
    fahrzeug.lenken(lenkwinkel)

    # Fahren: Sind die Motoren aus (Schalter, Weboberfläche weg), endet die autonome Fahrt.
    # Sie startet beim Wiedereinschalten NICHT von selbst.
    if not fahrzeug.motoren_frei:
        autonom["faehrt"] = False
    if autonom["faehrt"]:
        if fahrzeug.tempo != zustand["tempo"]:
            fahrzeug.fahren(zustand["tempo"])
    elif fahrzeug.faehrt():
        fahrzeug.anhalten()

    zustand["anzeige_lenkwinkel"] = lenkwinkel
    zustand["anzeige_text"] = "AUTONOM" if autonom["faehrt"] else "bereit"
    zustand["anzeige_farbe"] = (255, 160, 60) if autonom["faehrt"] else (200, 200, 200)


@app.errorhandler(ValueError)
def ungueltige_eingabe(fehler):
    return jsonify({"fehler": str(fehler)}), 400


def aufnahme_schritt(bild):
    """Ein Takt im Aufnahmemodus: Controller auswerten, lenken, ggf. Bild speichern."""
    if not controller.verbunden():
        if fahrzeug.faehrt():
            print("Controller getrennt – Auto hält an.")
            fahrzeug.anhalten()
        zustand["anzeige_text"] = "Controller nicht verbunden"
        zustand["anzeige_farbe"] = GELB
        return

    for taste in controller.neu_gedrueckte_tasten():
        if taste == "A" and not aufnahme.pausiert:
            fahrzeug.fahren(0 if fahrzeug.faehrt() else zustand["tempo"])
        elif taste == "B":
            fahrzeug.anhalten()
        elif taste == "PLUS":
            aufnahme_umschalten()
        elif taste == "MINUS":
            pause_umschalten()

    lenkwinkel = round(controller.lenkung * LENKUNG_MAX)
    if lenkwinkel != fahrzeug.lenkwinkel:
        fahrzeug.lenken(lenkwinkel)

    # Bilder nur speichern, während das Auto wirklich fährt
    if aufnahme.laeuft and fahrzeug.faehrt():
        aufnahme.bild_speichern(bild, fahrzeug.lenkwinkel, fahrzeug.tempo)

    # Overlay: echter Lenkwinkel, dazu der Aufnahme-Zustand
    zustand["anzeige_lenkwinkel"] = fahrzeug.lenkwinkel
    if aufnahme.pausiert:
        zustand["anzeige_text"], zustand["anzeige_farbe"] = "PAUSE", GELB
    elif aufnahme.laeuft:
        zustand["anzeige_text"], zustand["anzeige_farbe"] = f"REC  {aufnahme.anzahl} Bilder", ROT
    else:
        zustand["anzeige_text"], zustand["anzeige_farbe"] = "", GRUEN


def steuerschleife():
    """Das Herz des Programms: läuft im Takt der Kamera (30-mal pro Sekunde)."""
    nummer = 0
    while True:
        nummer, bild = kamera.naechstes_bild(nummer)
        if bild is None:
            continue
        try:
            if zustand["modus"] == "aufnahme":
                aufnahme_schritt(bild)
            elif zustand["modus"] == "autonom":
                autonom_schritt(bild)
            else:
                controller.neu_gedrueckte_tasten()   # hier hat der Controller nichts zu sagen
                if zustand["modus"] == "training":
                    zustand["anzeige_text"] = "TRAINING - Motoren gesperrt" if training.laeuft else "Motoren gesperrt"
                    zustand["anzeige_farbe"] = GELB
        except Exception as fehler:   # ein Fehler darf die Schleife nicht beenden
            print("Fehler in der Steuerschleife:", fehler)
            autonom["faehrt"] = False
            fahrzeug.anhalten()


# ----------------------------------------------------------------------
# Kalibrierung
# ----------------------------------------------------------------------

@app.get("/api/kalibrierung")
def kalibrierung_lesen():
    return jsonify(fahrzeug.kalibrierung_lesen())


@app.post("/api/kalibrierung/vorschau")
def kalibrierung_vorschau():
    werte = request.json
    fahrzeug.kalibrierung_vorschau(float(werte["lenkung"]), float(werte["schwenken"]), float(werte["neigen"]))
    return jsonify(ok=True)


@app.post("/api/kalibrierung/speichern")
def kalibrierung_speichern():
    werte = request.json
    fahrzeug.kalibrierung_speichern(float(werte["lenkung"]), float(werte["schwenken"]), float(werte["neigen"]))
    return jsonify(fahrzeug.kalibrierung_lesen())


# ----------------------------------------------------------------------
# Hintergrund-Aufgaben
# ----------------------------------------------------------------------

def browser_waechter():
    """Schaltet die Motoren aus, wenn sich die Weboberfläche nicht mehr meldet."""
    while True:
        time.sleep(0.1)
        if fahrzeug.motoren_frei and time.monotonic() - letzte_browser_anfrage > BROWSER_TIMEOUT:
            print("Weboberfläche meldet sich nicht mehr – Motoren werden ausgeschaltet.")
            fahrzeug.motoren_freigeben(False)


def sensoren_messen():
    """Misst jede Sekunde Akkuspannung und CPU-Temperatur."""
    messwerte = []
    while True:
        spannung = fahrzeug.akku_spannung()
        if 5.0 < spannung < 9.0:   # Ausreißer (Messfehler) ignorieren
            messwerte = (messwerte + [spannung])[-10:]   # gleitender Mittelwert über 10 Messungen
            zustand["akku_volt"] = round(sum(messwerte) / len(messwerte), 2)

        # Die CPU-Temperatur steht in tausendstel Grad in dieser Datei
        with open("/sys/class/thermal/thermal_zone0/temp") as datei:
            zustand["temperatur"] = round(int(datei.read()) / 1000, 1)
        # Drosselt der Pi gerade? (Bit 2: Takt gesenkt, Bit 3: Temperaturgrenze erreicht)
        antwort = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True).stdout
        if "=" in antwort:
            zustand["drosselt"] = bool(int(antwort.split("=")[1], 16) & 0b1100)
        time.sleep(1)


# ----------------------------------------------------------------------
# Start und Ende
# ----------------------------------------------------------------------

def main():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    fahrzeug.lenken(0)
    fahrzeug.kamera_ausrichten(0, KAMERA_NEIGEN_STANDARD)
    for aufgabe in (steuerschleife, browser_waechter, sensoren_messen):
        threading.Thread(target=aufgabe, daemon=True).start()

    ip_adressen = subprocess.run(["hostname", "-I"], capture_output=True, text=True).stdout.split()
    print("\nEnd-to-End-Projekt läuft. Im Browser öffnen:")
    for ip in ip_adressen:
        if "." in ip:
            print(f"    http://{ip}:{PORT}")
    print("Beenden mit Strg+C\n")

    try:
        app.run(host="0.0.0.0", port=PORT, threaded=True, debug=False, use_reloader=False)
    finally:
        print("Programm wird beendet: Motoren aus, Lenkung geradeaus.")
        training.abbrechen()
        aufnahme.stoppen()
        fahrzeug.herunterfahren()
        kamera.schliessen()


if __name__ == "__main__":
    main()
