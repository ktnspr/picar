"""
server.py – Webserver für die Fernsteuerung des PiCar-X.

Start:   cd ~/prof-playground/handy_fernsteuerung && python3 server.py
Dann im Handy-Browser öffnen:   http://<IP-Adresse-des-Pi>:8000

Der Server liefert die Webseite aus und nimmt die Befehle entgegen, die die
Webseite schickt (fahren, lenken, Kamera bewegen, ...). Die eigentliche
Hardware-Steuerung steckt in auto.py, die Kamera in kamera.py und die
Akku-Berechnung in akku.py.
"""

import logging
import os
import signal
import subprocess
import sys
import threading
import time

from flask import Flask, Response, jsonify, render_template, request

# Die gemeinsamen Bausteine (auto.py, kamera.py, akku.py, ...) liegen einen Ordner
# höher. Damit Python sie findet, nehmen wir diesen Ordner in den Suchpfad auf.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import kamera
from akku import AkkuAnzeige
from auto import Auto

PORT = 8000
AKKU_MESS_PAUSE = 1.0  # Sekunden zwischen zwei Akku-Messungen

app = Flask(__name__)
auto = Auto()
akku = AkkuAnzeige()


# ----------------------------------------------------------------------
# Webseite und Video
# ----------------------------------------------------------------------

@app.route("/")
def startseite():
    # Die Grenzen der Servos geben wir an die Webseite weiter,
    # damit die Schieberegler den richtigen Bereich haben.
    return render_template("index.html", auto=Auto)


@app.route("/video")
def video():
    return Response(kamera.mjpeg_stream(), mimetype="multipart/x-mixed-replace; boundary=frame")


# ----------------------------------------------------------------------
# Befehle der Webseite (die Webseite schickt JSON, wir antworten mit JSON)
# ----------------------------------------------------------------------

@app.post("/api/herzschlag")
def herzschlag():
    auto.lebenszeichen()
    return jsonify(auto.status())


@app.post("/api/fahren")
def fahren():
    auto.fahren(request.json["richtung"])
    return jsonify(auto.status())


@app.post("/api/tempo")
def tempo():
    auto.tempo_setzen(request.json["prozent"])
    return jsonify(auto.status())


@app.post("/api/lenken")
def lenken():
    auto.lenken(float(request.json["winkel"]))
    return jsonify(auto.status())


@app.post("/api/lenkung_justieren")
def lenkung_justieren():
    auto.lenkung_justieren(float(request.json["aenderung"]))
    return jsonify(auto.status())


@app.post("/api/kamera_justieren")
def kamera_justieren():
    auto.kamera_justieren(float(request.json["schwenken"]), float(request.json["neigen"]))
    return jsonify(auto.status())


@app.post("/api/kamera")
def kamera_ausrichten():
    auto.kamera_ausrichten(float(request.json["schwenken"]), float(request.json["neigen"]))
    return jsonify(auto.status())


@app.get("/api/akku")
def akku_stand():
    return jsonify(akku.als_dict())


# ----------------------------------------------------------------------
# Start und Ende
# ----------------------------------------------------------------------

def akku_dauerhaft_messen():
    """Läuft im Hintergrund und misst jede Sekunde die Akkuspannung."""
    while True:
        akku.messwert_hinzufuegen(auto.akku_spannung_messen())
        time.sleep(AKKU_MESS_PAUSE)


def adressen_anzeigen():
    """Zeigt an, unter welcher Adresse die Seite im Browser erreichbar ist."""
    ip_adressen = subprocess.run(["hostname", "-I"], capture_output=True, text=True).stdout.split()
    print("\nFernsteuerung läuft! Im Handy-Browser öffnen:")
    for ip in ip_adressen:
        if "." in ip:  # nur IPv4-Adressen, die sind leichter abzutippen
            print(f"    http://{ip}:{PORT}")
    print("Beenden mit Strg+C\n")


def main():
    # Auch beim Beenden per „kill“ (Signal SIGTERM) sauber aufräumen.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    # Nicht jede einzelne Anfrage ausgeben – der Herzschlag kommt 5-mal pro Sekunde.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    kamera.starten()
    threading.Thread(target=akku_dauerhaft_messen, daemon=True).start()
    adressen_anzeigen()

    try:
        # debug=False und use_reloader=False: Das Programm darf nur EINMAL laufen,
        # sonst streiten sich zwei Kopien um Kamera und Motoren.
        app.run(host="0.0.0.0", port=PORT, threaded=True, debug=False, use_reloader=False)
    finally:
        # Wird immer ausgeführt – auch bei Strg+C oder einem Fehler.
        print("Server wird beendet: Motoren aus, Lenkung und Kamera geradeaus.")
        auto.herunterfahren()
        kamera.stoppen()


if __name__ == "__main__":
    main()
