"""
controller_fahren.py – Den PiCar-X mit dem Nintendo Switch Pro Controller fahren.

Nebenbei läuft ein kleiner Webserver, der das Kamerabild im Vollbild zeigt –
zusammen mit Akkustand, Tempo und Controller-Verbindung.

Start:   cd ~/prof-playground/controller_fernsteuerung && python3 controller_fahren.py
Kamerabild im Browser:   http://<IP-Adresse-des-Pi>:8001

Belegung:
    linker Stick     fahren und lenken: hoch/runter = stufenlos vorwärts/rückwärts,
                     links/rechts = lenken
    ZR halten        vorwärts fahren mit festem Tempo
    ZL halten        rückwärts fahren mit festem Tempo
    Steuerkreuz ▲ ▼  festes Tempo für ZR/ZL +10 % / -10 %
    B                Stopp (solange gedrückt)
    rechter Stick    Kamera bewegen
    A                Kamera zentrieren

Nicht gleichzeitig mit handy_fernsteuerung/server.py starten – beide brauchen Kamera und Motoren.
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
from auto import RUECKWAERTS, STOPP, VORWAERTS, Auto, begrenzen
from gamepad import Gamepad

PORT = 8001
TAKT = 0.02                 # Sekunden pro Durchlauf der Steuerschleife (50-mal pro Sekunde)
TEMPO_START = 30            # Prozent, festes Tempo für ZR/ZL
TEMPO_SCHRITT = 10          # Prozent pro Druck auf das Steuerkreuz
# Damit „Stick nach oben“ vorwärts fährt. Am Auto ausprobiert: Der Controller meldet
# „oben“ als negativen Wert, deshalb drehen wir das Vorzeichen um.
GAS_RICHTUNG = -1
KAMERA_GESCHWINDIGKEIT = 90 # Grad pro Sekunde, wenn der rechte Stick ganz ausgelenkt ist
AKKU_MESS_PAUSE = 1.0       # Sekunden

auto = Auto()
akku = AkkuAnzeige()
gamepad = Gamepad()
app = Flask(__name__)


# ----------------------------------------------------------------------
# Webserver: Vollbild-Kamerabild mit Akkustand
# ----------------------------------------------------------------------

@app.route("/")
def startseite():
    return render_template("vollbild.html")


@app.route("/video")
def video():
    return Response(kamera.mjpeg_stream(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.get("/api/status")
def status():
    return jsonify({
        **auto.status(),  # Richtung, Tempo, Lenkung und Kamera-Mitte vom Auto
        "akku": akku.als_dict(),
        "controller": gamepad.verbunden(),
    })


# Kalibrierung: verschiebt die Mitte von Kamera und Lenkung dauerhaft (gilt systemweit)
@app.post("/api/kamera_justieren")
def kamera_justieren():
    auto.kamera_justieren(float(request.json["schwenken"]), float(request.json["neigen"]))
    return status()


@app.post("/api/lenkung_justieren")
def lenkung_justieren():
    auto.lenkung_justieren(float(request.json["aenderung"]))
    return status()


@app.post("/api/kamera_zentrieren")
def kamera_zentrieren():
    auto.kamera_ausrichten(0, 0)
    return status()


def webserver_starten():
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.run(host="0.0.0.0", port=PORT, threaded=True, debug=False, use_reloader=False)


def akku_dauerhaft_messen():
    while True:
        akku.messwert_hinzufuegen(auto.akku_spannung_messen())
        time.sleep(AKKU_MESS_PAUSE)


# ----------------------------------------------------------------------
# Steuerung mit dem Controller
# ----------------------------------------------------------------------

def steuern():
    """Die Steuerschleife: liest 50-mal pro Sekunde den Controller und stellt das Auto ein."""
    festes_tempo = TEMPO_START  # für ZR/ZL, mit dem Steuerkreuz einstellbar
    war_verbunden = False

    while True:
        time.sleep(TAKT)

        # --- Ist der Controller da? ---
        if not gamepad.verbunden():
            if war_verbunden:
                print("Controller-Verbindung verloren – Auto hält an.")
                auto.fahren(STOPP)
                war_verbunden = False
            # Kein Lebenszeichen mehr an das Auto → die Totmannschaltung
            # in auto.py hält es sicher an, auch wenn hier etwas schiefgeht.
            continue
        if not war_verbunden:
            print("Controller verbunden – los geht's!")
            war_verbunden = True
        auto.lebenszeichen()

        # --- Einzelne Tastendrücke: Tempo und Kamera zentrieren ---
        for taste in gamepad.neu_gedrueckte_tasten():
            if taste == "HOCH":
                festes_tempo = begrenzen(festes_tempo + TEMPO_SCHRITT, 0, 100)
                print(f"Tempo für ZR/ZL: {festes_tempo} %")
            elif taste == "RUNTER":
                festes_tempo = begrenzen(festes_tempo - TEMPO_SCHRITT, 0, 100)
                print(f"Tempo für ZR/ZL: {festes_tempo} %")
            elif taste == "A":
                auto.kamera_ausrichten(0, 0)

        # --- Lenken mit dem linken Stick ---
        lenkwinkel = round(gamepad.achse("LX") * Auto.LENKUNG_MAX)
        if lenkwinkel != auto.lenkwinkel:
            auto.lenken(lenkwinkel)  # stellt auch das Differential neu ein

        # --- Fahren: B hat Vorrang, dann ZR/ZL, dann der linke Stick ---
        gas = gamepad.achse("LY") * GAS_RICHTUNG  # -1 (ganz runter) bis 1 (ganz hoch)
        tempo = auto.tempo
        if "B" in gamepad.gedrueckt:
            richtung = STOPP
        elif "ZR" in gamepad.gedrueckt and "ZL" not in gamepad.gedrueckt:
            richtung, tempo = VORWAERTS, festes_tempo
        elif "ZL" in gamepad.gedrueckt and "ZR" not in gamepad.gedrueckt:
            richtung, tempo = RUECKWAERTS, festes_tempo
        elif gas > 0:
            # Stufenlos: je weiter der Stick nach oben zeigt, desto schneller
            richtung, tempo = VORWAERTS, round(gas * 100)
        elif gas < 0:
            richtung, tempo = RUECKWAERTS, round(-gas * 100)
        else:
            richtung = STOPP

        # Erst das Tempo, dann die Richtung – so fährt das Auto gleich richtig schnell los.
        if tempo != auto.tempo:
            auto.tempo_setzen(tempo)
        if richtung != auto.richtung:
            auto.fahren(richtung)

        # --- Kamera mit dem rechten Stick: je weiter ausgelenkt, desto schneller ---
        rx, ry = gamepad.achse("RX"), gamepad.achse("RY")
        if rx != 0 or ry != 0:
            schritt = KAMERA_GESCHWINDIGKEIT * TAKT
            # Vorzeichen bei „neigen“ am Auto ausprobiert: so bewegt sich die Kamera wie gewünscht
            auto.kamera_ausrichten(auto.schwenken + rx * schritt, auto.neigen + ry * schritt)


# ----------------------------------------------------------------------
# Start und Ende
# ----------------------------------------------------------------------

def adressen_anzeigen():
    ip_adressen = subprocess.run(["hostname", "-I"], capture_output=True, text=True).stdout.split()
    print("\nKamerabild im Browser öffnen:")
    for ip in ip_adressen:
        if "." in ip:
            print(f"    http://{ip}:{PORT}")
    print("Controller einschalten (z. B. Home drücken). Beenden mit Strg+C\n")


def main():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    kamera.starten()
    threading.Thread(target=akku_dauerhaft_messen, daemon=True).start()
    threading.Thread(target=webserver_starten, daemon=True).start()
    adressen_anzeigen()

    try:
        steuern()
    except KeyboardInterrupt:
        pass
    finally:
        print("\nProgramm wird beendet: Motoren aus, Lenkung und Kamera geradeaus.")
        auto.herunterfahren()
        kamera.stoppen()


if __name__ == "__main__":
    main()
