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
import numpy as np
import torch
from flask import Flask, Response, jsonify, render_template, request, send_file

import extern
import fahrten
import kamera_regler
import linie
import regler_einmessen
from akku import spannung_zu_prozent
import konfiguration
import modelle
from controller import Controller
from einstellungen import (AUSSCHNITT_OBEN, KAMERA_BREITE, KAMERA_NEIGEN_STANDARD, LENKUNG_MAX, PORT,
                           TEMPO_STANDARD)
from kamera import Kamera, overlay_zeichnen
from kern.datensatz import aufnahme_einstellungen, einheitlichkeit_pruefen
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
linienerkennung = linie.Linienerkennung(konfiguration.laden()["linie"])
kameraregler = kamera_regler.Kameraregler(konfiguration.laden()["regler"])

# Zustand des Einmessens der Reglerwerte (siehe regler_einmessen.py)
einmessung = {"laeuft": False, "fortschritt": 0.0, "text": "", "ergebnisse": [], "beste": None,
              "fehler": None, "abbrechen": False, "regler": None, "aufzeichnung": [], "profil": "flott"}
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
    "akku_prozent": None,         # geschätzter Ladestand (aus der Spannung, siehe akku.py)
    "temperatur": None,          # CPU-Temperatur in °C
    "drosselt": False,           # senkt der Pi gerade wegen Hitze seinen Takt?
    "anzeige_lenkwinkel": None,  # Lenkwinkel für das Overlay im Livebild
    "anzeige_text": "",
    "anzeige_farbe": (0, 220, 0),
    "linie": None,               # letztes Ergebnis der Linienerkennung (linie.py)
    "kamera_modus": "fest",      # Aufnahme: "fest" oder "aktiv" (Kamera folgt der Linie)
    "schwenken_fest": 0.0,       # Schwenkwinkel für die feste Kamera (Regler „Kamera schwenken“)
    "regler_zustand": None,      # "folgt", "sucht", "verloren" – oder None, wenn die Regelung aus ist
    "messung_laeuft": False,     # Bildwinkel wird gerade ausgemessen (Regelung pausiert)
    "regeltest": False,          # Kalibrierseite: Kamera folgt testweise der Linie
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
    "variante": "B",          # A = klassisch, B = CNN mit fester Kamera, C = CNN mit aktiver Kamera
    "hinweise": [],           # Hinweise zum gewählten Modell (z. B. abweichende Kalibrierung)
    "tempo_modell": None,     # Geschwindigkeit, mit der die Trainingsdaten aufgenommen wurden
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
            if zustand["linie"] is not None:
                bild = linie.overlay_linie(bild, zustand["linie"], fahrzeug.schwenken, zustand["regler_zustand"])
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
        "akku_prozent": zustand["akku_prozent"],
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
        "kamera_modus": zustand["kamera_modus"],
        "schwenken_fest": zustand["schwenken_fest"],
        "regler_zustand": zustand["regler_zustand"],
        "regeltest": zustand["regeltest"],
        "linie": linie_fuer_browser(zustand["linie"]),
        "autonom": {
            "modell_id": autonom["modell_id"],
            "modell_name": autonom["meta"]["anzeigename"] if autonom["meta"] else None,
            "faehrt": autonom["faehrt"],
            "lenkwinkel": autonom["lenkwinkel"],
            "rechenzeit_ms": autonom["rechenzeit_ms"],
            "rate": autonom["rate"],
            "variante": autonom["variante"] if autonom["meta"] else None,
            "hinweise": autonom["hinweise"] if autonom["meta"] else [],
            "tempo_modell": autonom["tempo_modell"] if autonom["meta"] else None,
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
    zustand["regeltest"] = False   # der Regeltest gehört zur Kalibrierseite
    autonom["faehrt"] = False   # und das autonome Fahren auch.
    controller.neu_gedrueckte_tasten()   # alte Tastendrücke verwerfen – sie gehören zum alten Modus
    if zustand["modus"] == "autonom" and neuer_modus != "autonom":
        eigene_einstellungen_wiederherstellen()
    if zustand["modus"] == "kalibrierung" and neuer_modus != "kalibrierung":
        # Die Kalibrier-Vorschau hat die Servos direkt bewegt. Jetzt wieder die
        # eingestellten Winkel anfahren – sonst stimmt der gespeicherte Kamerawinkel nicht.
        fahrzeug.lenken(0)
        fahrzeug.kamera_ausrichten(fahrzeug.schwenken, fahrzeug.neigen)
    zustand["modus"] = neuer_modus
    if neuer_modus == "autonom" and autonom["meta"]:
        # Zurück im Autonom-Modus: wieder alle Einstellungen des gewählten Modells verwenden
        modell_einstellungen_anwenden(autonom["meta"])
    zustand["anzeige_lenkwinkel"] = None
    zustand["anzeige_text"] = ""
    return zustand_abfragen()


@app.post("/api/tempo")
def tempo_setzen():
    if aufnahme.laeuft:
        # Die Geschwindigkeit gehört zu den Aufnahme-Einstellungen einer Fahrt
        return jsonify({"fehler": "Während einer Aufnahme bleibt die Geschwindigkeit fest."}), 409
    zustand["tempo"] = max(0, min(100, int(request.json["tempo"])))
    if fahrzeug.faehrt():
        fahrzeug.fahren(zustand["tempo"])   # wirkt sofort, auch während der Fahrt
    return zustand_abfragen()


@app.post("/api/kamera")
def kamera_ausrichten():
    if aufnahme.laeuft:
        # Der Kamerawinkel gehört zu den Daten einer Fahrt und muss gleich bleiben.
        return jsonify({"fehler": "Während einer Aufnahme kann die Kamera nicht bewegt werden."}), 409
    zustand["schwenken_fest"] = float(request.json["schwenken"])
    # Bei aktiver Kamera bestimmt der Regler das Schwenken – einstellbar bleibt nur die Neigung
    schwenken = fahrzeug.schwenken if regelung_aktiv() else zustand["schwenken_fest"]
    fahrzeug.kamera_ausrichten(schwenken, float(request.json["neigen"]))
    return zustand_abfragen()


# ----------------------------------------------------------------------
# Aktive Kamera: Regelung und Einstellungen
# ----------------------------------------------------------------------

def regelung_aktiv():
    """Soll die Kamera gerade der Linie folgen?"""
    if zustand["messung_laeuft"]:
        return False
    if zustand["modus"] == "aufnahme":
        return zustand["kamera_modus"] == "aktiv"
    if zustand["modus"] == "autonom":
        return autonom["variante"] in ("A", "C")
    if zustand["modus"] == "kalibrierung":
        return zustand["regeltest"]
    return False


@app.post("/api/regeltest")
def regeltest_schalten():
    """Kalibrierseite: Kamera folgt testweise der Linie – mit der Neigung wie bei der Aufnahme."""
    zustand["regeltest"] = bool(request.json["an"]) and zustand["modus"] == "kalibrierung"
    if zustand["regeltest"]:
        fahrzeug.kamera_ausrichten(fahrzeug.schwenken, fahrzeug.neigen)
    return zustand_abfragen()


@app.post("/api/kamera_modus")
def kamera_modus_setzen():
    if aufnahme.laeuft:
        return jsonify({"fehler": "Während einer Aufnahme kann der Kameramodus nicht geändert werden."}), 409
    modus = request.json["modus"]
    if modus not in ("fest", "aktiv"):
        raise ValueError(f"Unbekannter Kameramodus: {modus}")
    zustand["kamera_modus"] = modus
    return zustand_abfragen()


@app.get("/api/regler")
def regler_lesen():
    return jsonify(kameraregler.einstellungen)


@app.post("/api/regler")
def regler_einstellen():
    if aufnahme.laeuft:
        return jsonify({"fehler": "Während einer Aufnahme bleiben die Reglerwerte fest."}), 409
    if zustand["modus"] == "autonom" and autonom["meta"]:
        return jsonify({"fehler": "Beim autonomen Fahren gelten die Reglerwerte des Modells."}), 409
    konfig = konfiguration.laden()
    for schluessel, wert in request.json.items():
        if schluessel in kamera_regler.STANDARD:
            konfig["regler"][schluessel] = type(kamera_regler.STANDARD[schluessel])(wert)
    konfiguration.speichern(konfig)
    kameraregler.einstellen(konfig["regler"])
    return jsonify(kameraregler.einstellungen)


@app.post("/api/regler/einmessen")
def regler_einmessen_starten():
    if einmessung["laeuft"]:
        return jsonify({"fehler": "Das Einmessen läuft bereits."}), 409
    if fahrzeug.faehrt() or aufnahme.laeuft or zustand["modus"] == "training":
        return jsonify({"fehler": "Einmessen geht nur, wenn das Auto steht, keine Aufnahme und kein Training läuft."}), 409
    if not (zustand["linie"] and zustand["linie"].sichtbar):
        return jsonify({"fehler": "Die Linie ist nicht im Bild."}), 409
    profil = request.json.get("profil", "flott")
    if profil not in regler_einmessen.PROFILE:
        raise ValueError(f"Unbekanntes Profil: {profil}")
    einmessung.update(laeuft=True, fortschritt=0.0, text="Starte ...", ergebnisse=[], beste=None,
                      fehler=None, abbrechen=False, profil=profil)
    threading.Thread(target=regler_einmessen_ablauf, daemon=True).start()
    return jsonify(einmessung_status())


@app.post("/api/regler/einmessen/abbrechen")
def regler_einmessen_abbrechen():
    einmessung["abbrechen"] = True
    return jsonify(einmessung_status())


@app.get("/api/regler/einmessen")
def einmessung_status():
    return {k: einmessung[k] for k in ("laeuft", "fortschritt", "text", "ergebnisse", "beste", "fehler", "profil")}


def regler_einmessen_ablauf():
    """Probiert alle Kombinationen aus Kp und Kd aus (Sprungantwort nach links und rechts)."""
    ausgang = fahrzeug.schwenken
    richtung = kameraregler.einstellungen["richtung"]
    toleranz = max(2.0, kameraregler.einstellungen["totzone"] + 0.5)
    profil = regler_einmessen.PROFILE[einmessung["profil"]]
    zustand["messung_laeuft"] = True   # die normale Regelung pausiert
    try:
        # 1. Linie in die Bildmitte holen (mit den jetzigen Reglerwerten), Richtung der Linie merken
        einmessung["text"] = "Suche die Linie ..."
        einmessung["regler"] = kamera_regler.Kameraregler(kameraregler.einstellungen)
        time.sleep(1.5)
        einmessung["regler"] = None
        if not (zustand["linie"] and zustand["linie"].sichtbar):
            raise ValueError("Linie nicht gefunden.")
        mitte = fahrzeug.schwenken + richtung * zustand["linie"].winkel   # Schwenkwinkel, bei dem die Linie mittig ist

        # 2. Alle Kombinationen ausprobieren
        kombinationen = [(kp, kd) for kp in profil["kp_werte"] for kd in profil["kd_werte"]]
        for nummer, (kp, kd) in enumerate(kombinationen):
            bewertungen = []
            for seite in (1, -1):
                if einmessung["abbrechen"]:
                    raise ValueError("Abgebrochen.")
                einmessung["text"] = f"Versuch {nummer + 1}/{len(kombinationen)}: Kp {kp}, Kd {kd}, " \
                                     f"{'rechts' if seite > 0 else 'links'} neben der Linie"
                fahrzeug.kamera_ausrichten(mitte + seite * regler_einmessen.AUSLENKUNG, fahrzeug.neigen)
                time.sleep(0.6)                                          # Servo zur Ruhe kommen lassen
                einmessung["aufzeichnung"] = []
                einmessung["regler"] = kamera_regler.Kameraregler(kameraregler.einstellungen | {"kp": kp, "kd": kd})
                time.sleep(profil["versuchsdauer"])                      # loslassen und zuschauen
                einmessung["regler"] = None
                bewertungen.append(regler_einmessen.bewerten(einmessung["aufzeichnung"], toleranz,
                                                             einmessung["profil"]))
                einmessung["fortschritt"] = (2 * nummer + (1 if seite > 0 else 2)) / (2 * len(kombinationen))
            einmessung["ergebnisse"].append(regler_einmessen.zusammenfassen(kp, kd, *bewertungen))

        einmessung["beste"] = min(einmessung["ergebnisse"], key=lambda e: e["note"])
        b = einmessung["beste"]
        einmessung["text"] = (f"Fertig ({einmessung['profil']}). Am besten: Kp {b['kp']}, Kd {b['kd']} – "
                              f"Einschwingzeit {b['einschwingzeit']} s, Überschwingen {b['ueberschwingen']}°, "
                              f"Unruhe {b['unruhe']}°, Ruckeln {b['ruckeln']}.")
    except ValueError as fehler:
        einmessung["fehler"] = str(fehler)
        einmessung["text"] = "Einmessen beendet: " + str(fehler)
    finally:
        einmessung["regler"] = None
        fahrzeug.kamera_ausrichten(ausgang, fahrzeug.neigen)
        zustand["messung_laeuft"] = False
        einmessung["laeuft"] = False


@app.post("/api/bildwinkel_messen")
def bildwinkel_messen():
    """Misst den Bildwinkel der Kamera: Kamera um ±8° schwenken und schauen, wie weit die Linie wandert.

    Die Linie erscheint bei x = Bildmitte + f · tan(Winkel der Linie − Schwenkwinkel).
    Zwischen −8° und +8° wandert sie also um etwa f · 2 · tan(8°) Pixel – daraus folgt
    die Brennweite f und daraus der Bildwinkel. Nebenbei sieht man, ob die Schwenkrichtung stimmt.
    """
    if fahrzeug.faehrt():
        return jsonify({"fehler": "Bitte erst anhalten."}), 409
    ausgang = fahrzeug.schwenken
    zustand["messung_laeuft"] = True
    try:
        positionen = []
        for winkel in (-8.0, 8.0):
            fahrzeug.kamera_ausrichten(ausgang + winkel, fahrzeug.neigen)
            time.sleep(0.8)                      # Servo und Kamerabild zur Ruhe kommen lassen
            werte = []
            for _ in range(10):
                time.sleep(0.05)
                if zustand["linie"] and zustand["linie"].sichtbar:
                    werte.append(zustand["linie"].x)
            if len(werte) < 5:
                return jsonify({"fehler": "Linie nicht (gut genug) sichtbar – bitte das Auto so hinstellen, "
                                          "dass die Linie in der Bildmitte liegt."}), 409
            positionen.append(float(np.median(werte)))
    finally:
        fahrzeug.kamera_ausrichten(ausgang, fahrzeug.neigen)
        zustand["messung_laeuft"] = False
    wanderung = positionen[0] - positionen[1]    # Pixel
    if abs(wanderung) < 10:
        return jsonify({"fehler": "Die Linie hat sich kaum bewegt – bewegt sich der Schwenk-Servo?"}), 409
    brennweite = abs(wanderung) / (2 * np.tan(np.radians(8.0)))
    bildwinkel = round(float(np.degrees(2 * np.arctan(KAMERA_BREITE / 2 / brennweite))), 1)
    # Wandert die Linie beim Schwenken nach +8° im Bild nach links (wanderung > 0), heißt
    # „positiver Winkel“ beim Servo „nach rechts“ – dann muss der Regler nichts umdrehen.
    return jsonify({"bildwinkel": bildwinkel, "brennweite_pixel": round(float(brennweite), 1),
                    "wanderung_pixel": round(wanderung, 1), "regler_richtung": 1 if wanderung > 0 else -1})


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
        aufnahme.starten(zustand["tempo"], fahrzeug.schwenken, fahrzeug.neigen, zustand["ausschnitt_oben"],
                         kamera_modus=zustand["kamera_modus"], regler=dict(kameraregler.einstellungen),
                         linienerkennung=dict(linienerkennung.einstellungen),
                         kalibrierung=fahrzeug.kalibrierung_lesen())
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


@app.post("/api/training/pruefen")
def training_pruefen():
    """Passen die ausgewählten Fahrten zusammen? Welche Variante würde trainiert?"""
    metas = [fahrten.meta_lesen(fahrten.fahrt_ordner(f)) for f in request.json["fahrten"]]
    if not metas:
        return jsonify({"passt": False, "unterschiede": [], "variante": None})
    unterschiede = einheitlichkeit_pruefen(metas)
    variante = "C" if aufnahme_einstellungen(metas[0])["kamera_modus"] == "aktiv" else "B"
    hinweise = []
    if any(m.get("kalibrierung") is None for m in metas):
        hinweise.append("Bei mindestens einer Fahrt ist die Kalibrierung unbekannt (ältere Aufnahme). "
                        "Beim Fahren wird dann die aktuelle Kalibrierung verwendet.")
    return jsonify({"passt": not unterschiede, "unterschiede": unterschiede, "variante": variante,
                    "hinweise": hinweise})


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
    modell_einstellungen_anwenden(meta)
    torch.set_num_threads(2)   # für ein einzelnes Bild reichen 2 Rechenkerne
    return zustand_abfragen()


def modell_einstellungen_anwenden(meta):
    """Stellt ALLES so ein wie bei der Aufnahme der Trainingsdaten: Kalibrierung, Kamerawinkel,
    Bildausschnitt, Kameramodus, Regler, Linienerkennung. Nur vorübergehend – gespeichert wird nichts."""
    hinweise = []
    aufnahme = meta.get("aufnahme")
    if aufnahme is None:
        # Ältere Modelle kennen nur Kamerawinkel und Bildausschnitt
        aufnahme = {"kamera_modus": "fest", "kamera": meta["kamera"], "ausschnitt_oben": meta["ausschnitt_oben"],
                    "kalibrierung": None, "regler": None, "linienerkennung": None}
        hinweise.append("Älteres Modell: Es kennt nur Kamerawinkel und Bildausschnitt, nicht Kalibrierung und "
                        "Kameramodus. Es fährt mit fester Kamera.")
        if any(fahrten.meta_lesen(fahrten.FAHRTEN / f["id"]).get("kamera_modus") == "aktiv"
               for f in meta["fahrten"] if (fahrten.FAHRTEN / f["id"] / "meta.json").exists()):
            hinweise.append("Achtung: Seine Trainingsdaten stammen (teilweise) von einer AKTIVEN Kamera – "
                            "dieses Modell passt nicht dazu. Bitte neu trainieren.")

    # Kalibrierung: die des Modells – oder, wenn unbekannt, die gespeicherte
    eigene_einstellungen_wiederherstellen()
    if aufnahme["kalibrierung"]:
        gespeichert = fahrzeug.gespeicherte_kalibrierung()
        if any(abs(float(aufnahme["kalibrierung"][k]) - gespeichert[k]) > 0.01 for k in gespeichert):
            hinweise.append("Die Kalibrierung des Modells weicht von der gespeicherten ab – für die Fahrt gilt die "
                            "des Modells: " + kalibrierung_text(aufnahme["kalibrierung"])
                            + " (gespeichert: " + kalibrierung_text(gespeichert) + ").")
        fahrzeug.kalibrierung_voruebergehend(aufnahme["kalibrierung"])
    else:
        hinweise.append("Kalibrierung der Trainingsdaten unbekannt – es gilt die gespeicherte.")

    # Aktive Kamera: Regler und Linienerkennung wie bei der Aufnahme
    if aufnahme["kamera_modus"] == "aktiv":
        if aufnahme["regler"]:
            kameraregler.einstellen(aufnahme["regler"])
        if aufnahme["linienerkennung"]:
            linienerkennung.einstellen(aufnahme["linienerkennung"])
    autonom["variante"] = meta.get("variante", "B")
    autonom["hinweise"] = hinweise

    zustand["schwenken_fest"] = float(aufnahme["kamera"]["schwenken"])
    fahrzeug.kamera_ausrichten(zustand["schwenken_fest"] if aufnahme["kamera_modus"] == "fest" else 0.0,
                               float(aufnahme["kamera"]["neigen"]))
    zustand["ausschnitt_oben"] = aufnahme["ausschnitt_oben"]
    # Geschwindigkeit wie bei der Aufnahme (ältere Modelle: Durchschnitt der Trainingsdaten)
    autonom["tempo_modell"] = int(aufnahme.get("tempo", meta["tempo"]))
    zustand["tempo"] = autonom["tempo_modell"]


def eigene_einstellungen_wiederherstellen():
    """Nach der autonomen Fahrt: wieder die gespeicherte Kalibrierung und die eigenen Einstellungen."""
    konfig = konfiguration.laden()
    fahrzeug.kalibrierung_aus_datei()
    kameraregler.einstellen(konfig["regler"])
    linienerkennung.einstellen(konfig["linie"])


def kalibrierung_text(k):
    return f"Lenkung {float(k['lenkung']):+g}°, Schwenken {float(k['schwenken']):+g}°, Neigen {float(k['neigen']):+g}°"


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
    lenkwinkel = lenkwinkel_vorhersagen(autonom["netz"], netz_ausschnitt(bild, zustand["ausschnitt_oben"]),
                                        fahrzeug.schwenken)   # den Schwenkwinkel nutzt nur Variante C
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


# ----------------------------------------------------------------------
# Linienerkennung (Einstellungen auf der Kalibrierseite)
# ----------------------------------------------------------------------

def linie_fuer_browser(ergebnis):
    if ergebnis is None:
        return None
    helligkeit = ergebnis.streifen[0].helligkeit if ergebnis.streifen else None
    return {"sichtbar": ergebnis.sichtbar, "x": ergebnis.x,
            "winkel": None if ergebnis.winkel is None else round(ergebnis.winkel, 1),
            "helligkeit": None if helligkeit is None else round(helligkeit),
            "rechenzeit_ms": round(ergebnis.rechenzeit_ms, 2)}


@app.get("/api/linie")
def linie_lesen():
    return jsonify(linienerkennung.einstellungen)


@app.post("/api/linie")
def linie_einstellen():
    konfig = konfiguration.laden()
    for schluessel, wert in request.json.items():
        if schluessel in linie.STANDARD and schluessel != "farbe_bgr":
            # Zahlen als Zahlen speichern, Schalter als Schalter
            standard = linie.STANDARD[schluessel]
            konfig["linie"][schluessel] = (bool(wert) if isinstance(standard, bool) else
                                           type(standard)(wert) if isinstance(standard, (int, float)) else wert)
    konfiguration.speichern(konfig)
    linienerkennung.einstellen(konfig["linie"])
    return jsonify(linienerkennung.einstellungen)


@app.post("/api/linie/farbe")
def linie_farbe_waehlen():
    """Bandfarbe per Klick ins Livebild: Farbe an dieser Stelle (Mittel über 7×7 Pixel) merken."""
    _, bild = kamera.naechstes_bild(0)
    x = int(max(3, min(bild.shape[1] - 4, request.json["x"])))
    y = int(max(3, min(bild.shape[0] - 4, request.json["y"])))
    farbe = [int(v) for v in np.median(bild[y - 3:y + 4, x - 3:x + 4].reshape(-1, 3), axis=0)]
    konfig = konfiguration.laden()
    konfig["linie"]["farbe_bgr"] = farbe
    konfig["linie"]["modus"] = "farbe"
    konfiguration.speichern(konfig)
    linienerkennung.einstellen(konfig["linie"])
    return jsonify(linienerkennung.einstellungen)


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
        aufnahme.bild_speichern(bild, fahrzeug.lenkwinkel, fahrzeug.tempo, fahrzeug.schwenken, zustand["linie"])

    # Overlay: echter Lenkwinkel, dazu der Aufnahme-Zustand
    zustand["anzeige_lenkwinkel"] = fahrzeug.lenkwinkel
    if aufnahme.pausiert:
        zustand["anzeige_text"], zustand["anzeige_farbe"] = "PAUSE", GELB
    elif aufnahme.laeuft:
        zustand["anzeige_text"], zustand["anzeige_farbe"] = f"REC  {aufnahme.anzahl} Bilder", ROT
    else:
        zustand["anzeige_text"], zustand["anzeige_farbe"] = "", GRUEN


def kamera_regeln(dt):
    """Aktive Kamera: den Schwenkwinkel nachführen, damit die Linie in der Bildmitte bleibt."""
    if einmessung["regler"] is not None:
        # Beim Einmessen regelt ein Versuchsregler – und jeder Takt wird mitgeschrieben
        regler = einmessung["regler"]
        neu = regler.schritt(zustand["linie"], fahrzeug.schwenken, dt)
        if abs(neu - fahrzeug.schwenken) >= 0.2:
            fahrzeug.kamera_ausrichten(neu, fahrzeug.neigen)
        linie_jetzt = zustand["linie"]
        einmessung["aufzeichnung"].append(
            (time.monotonic(), linie_jetzt.winkel if linie_jetzt and linie_jetzt.sichtbar else None, neu))
        zustand["regler_zustand"] = regler.zustand
        return
    if regelung_aktiv():
        neu = kameraregler.schritt(zustand["linie"], fahrzeug.schwenken, dt)
        if abs(neu - fahrzeug.schwenken) >= 0.2:   # winzige Änderungen nicht an den Servo schicken
            fahrzeug.kamera_ausrichten(neu, fahrzeug.neigen)
        zustand["regler_zustand"] = kameraregler.zustand
    elif zustand["regler_zustand"] is not None and not zustand["messung_laeuft"]:
        # Regelung wurde gerade ausgeschaltet: Kamera zurück auf den festen Winkel
        # (außer auf der Kalibrierseite – dort stellt die Kalibrierung die Servos)
        kameraregler.zuruecksetzen()
        zustand["regler_zustand"] = None
        if zustand["modus"] != "kalibrierung":
            fahrzeug.kamera_ausrichten(zustand["schwenken_fest"], fahrzeug.neigen)


def steuerschleife():
    """Das Herz des Programms: läuft im Takt der Kamera (30-mal pro Sekunde)."""
    nummer = 0
    letzter_takt = time.monotonic()
    while True:
        nummer, bild = kamera.naechstes_bild(nummer)
        if bild is None:
            continue
        jetzt = time.monotonic()
        dt = min(0.2, jetzt - letzter_takt)   # Zeit seit dem letzten Takt (für den Regler)
        letzter_takt = jetzt
        try:
            # Die Linienerkennung läuft in jedem Takt mit (sie braucht weniger als 1 ms)
            zustand["linie"] = linienerkennung.erkennen(bild)
            kamera_regeln(dt)
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
            zustand["akku_prozent"] = round(spannung_zu_prozent(zustand["akku_volt"]))

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
