# PiCar-X End-to-End: Einer Linie folgen mit einem neuronalen Netz

Der PiCar-X lernt, einer Klebeband-Linie auf dem Boden zu folgen. **End-to-End** heißt:
Ein neuronales Netz bekommt das Kamerabild und gibt direkt den Lenkwinkel aus –
niemand programmiert „suche die Linie“. Das Netz lernt es aus Beispielen: aus Fahrten,
bei denen ein Mensch mit dem Controller gelenkt hat.

Alles läuft auf dem Raspberry Pi – Aufnehmen, Trainieren und Fahren. Bedient wird es
über eine Weboberfläche im Browser (z. B. auf dem Notebook).

## Einrichten (einmalig)

```bash
cd ~/prof-playground/end2end
./einrichten.sh
```

Das legt die Python-Umgebung `.venv` an (PyTorch, evdev, NumPy, OpenCV, Flask – etwa 900 MB).
Außerdem nötig: SunFounder-Module (robot-hat, vilib, picar-x), ein gekoppelter
Nintendo Switch Pro Controller und einmalig:

```bash
sudo mkdir -p /opt/picar-x && sudo chown pi:pi /opt/picar-x
```

## Starten

```bash
cd ~/prof-playground/end2end
./start.sh
```

Dann im Browser öffnen: `http://<IP-Adresse-des-Pi>:8080` (die Adresse zeigt das Programm an).
Beenden mit **Strg+C** – die Motoren stoppen, die Lenkung stellt sich geradeaus.

Die Fernsteuerungen aus den anderen Ordnern dürfen nicht gleichzeitig laufen
(sie brauchen dieselbe Kamera). Das Programm prüft das beim Start und sagt Bescheid.

## So geht's

Oben rechts: **CPU-Temperatur** (grün < 70 °C, gelb 70–80 °C, rot ab 80 °C – dann drosselt
der Pi), **Akku** und der große **Motorschalter** (beim Start aus). Schließt man die Seite,
gehen die Motoren nach 1,5 s von selbst aus.

**0. Kalibrieren** (Seite „Kalibrierung“): Lenkung und Kamera so einstellen, dass sie
geradeaus zeigen. Gilt für alle Programme auf dem Pi.

**1. Daten aufnehmen:** Kamerawinkel und Bildausschnitt einstellen (die Vorschau zeigt, was das
Netz sieht), Motoren ein, mit dem Controller fahren:

| Controller | Funktion |
|---|---|
| linker Stick | lenken |
| A | anfahren / anhalten (mit der eingestellten Geschwindigkeit) |
| B | anhalten |
| + | Aufnahme starten / stoppen |
| − | Pause (zum Umsetzen des Autos) |

Gespeichert wird nur, während das Auto fährt: 10 Bilder pro Sekunde mit Lenkwinkel.
Fahrten lassen sich umbenennen und löschen.

**2. Trainieren:** Fahrten auswählen, „schnell“ oder „gründlich“, Training starten.
Es läuft, bis das Netz 5 Epochen lang nicht besser wird; „Beenden & speichern“ hört früher auf.
Die Lernkurve zeigt den Fehler beim Lernen und beim Prüfen. Mit etwa 4000 Bildern dauert
„schnell“ rund 6 Minuten, „gründlich“ rund 15. Unter „Wo trainieren?“ lässt sich statt des Pi
eine externe Trainingsressource wählen (siehe unten).

**3. Autonom fahren:** Modell wählen – alles wird so eingestellt wie bei der Aufnahme der
Trainingsdaten (siehe „Varianten“). Das Netz lenkt schon im Stand (zum Ausprobieren).
Motoren ein, „Autonom fahren“. Controller: A = Start/Stopp, B = Notstopp.

## Aktive Kamera

Statt geradeaus zu schauen, kann die Kamera der Klebeband-Linie folgen: Eine Linienerkennung
(klassische Bildverarbeitung, `linie.py`) findet die Linie in einem waagerechten Suchstreifen,
ein PD-Regler (`kamera_regler.py`) schwenkt die Kamera so, dass sie in der Bildmitte bleibt.
Der Schwenkwinkel zeigt dann, wohin die Linie vor dem Auto läuft – hilfreich in engen Kurven.

- **Linienerkennung einstellen** (Seite „Kalibrierung“): Verfahren „hell“ (Otsu, mit
  Mindesthelligkeit gegen helle Dielenfugen) oder „Farbe“ (Klick aufs Band im Livebild).
  „Bildwinkel ausmessen“ schwenkt die Kamera um ±8° und misst, wie weit die Linie wandert.
- **Aktive Kamera einschalten:** Reiter „1 · Daten aufnehmen“ → Kamera „aktiv“.
- **Regler einmessen:** Feld „Kameraregelung“ → „Regler einmessen“ probiert 16 Kombinationen
  aus Kp und Kd aus (Sprungantwort) und schlägt die beste vor (`regler_einmessen.py`).

## Varianten und sortenreine Daten

| Variante | Aufnahme mit | Netz bekommt | Beim Fahren |
|---|---|---|---|
| **B** | fester Kamera | Kamerabild | Kamera steht fest |
| **C** | aktiver Kamera | Kamerabild + Schwenkwinkel | Kamera folgt der Linie |

Die Variante ergibt sich aus den Trainingsdaten. Trainiert wird nur mit **sortenreinen** Fahrten:
gleicher Kameramodus, gleiche Kalibrierung, gleiche Kamerastellung, gleicher Bildausschnitt und –
bei aktiver Kamera – gleiche Regler- und Linienerkennungs-Einstellungen. Passt etwas nicht, zeigt
die Weboberfläche, was, und das Training bleibt gesperrt (auch auf dem Mac).

Das Modell speichert alle diese Aufnahme-Einstellungen. Beim autonomen Fahren werden sie
**vorübergehend** übernommen – auch die Kalibrierung –, danach gilt wieder das Gespeicherte.

## Messwerte auf dem Raspberry Pi 5

| Was | Messung | gewählt |
|---|---|---|
| Kamera | 60 Bilder/s bei 320 × 240 | 30 Bilder/s |
| Netz: Rechenzeit pro Bild | ca. 1 ms (3 ms mit Vorbereitung) | 30 Lenkentscheidungen/s |
| Netz: Training | ca. 600 Bilder/s (bei 48 × 160) | – |
| Aufnahme | – | 10 Bilder/s |

Beim Training wird der Pi über 80 °C heiß und drosselt etwas – ein Lüfter hilft.

## Externe Trainingsressource (z. B. ein Mac)

Ein schnellerer Rechner im selben Netz kann das Training übernehmen. Dort läuft der Dienst
aus [`mac_worker/`](mac_worker/README.md); er benutzt denselben Trainings-Code (Paket `kern`)
wie der Pi, die Modelle passen also garantiert zusammen.

Auf dem Pi: **2 · Trainieren → Externe Trainingsressource**

1. „Im Netz suchen“ (der Dienst kündigt sich per mDNS an) oder Hostname/IP und Port eintragen
2. Token aus `mac_worker/config.json` des Macs eintragen
3. „Verbindung testen“ – zeigt Erreichbarkeit, Rechengerät (MPS/CPU) und Code-Version;
   warnt, wenn die Version von der auf dem Pi abweicht
4. „Externe Trainingsressource verwenden“ ankreuzen, „Speichern“

Die Einstellung steht in `konfiguration.json` (mit Token, deshalb nicht im Git-Repository;
Vorlage: `konfiguration.example.json`). Beim Training dann „Wo trainieren? → extern“ wählen.
Ist der Rechner nicht erreichbar, trainiert der Pi selbst und sagt das deutlich. Der Steckbrief
jedes Modells hält fest, wo, auf welchem Gerät und wie lange trainiert wurde.

## Aufbau des Codes

**Gemeinsamer Kern** – Paket `kern/`, benutzt vom Pi UND vom Mac-Dienst (ohne Pi-spezifische Module):

| Datei | Aufgabe |
|---|---|
| `kern/netz.py` | Das neuronale Netz (PilotNet, verkleinert) |
| `kern/vorverarbeitung.py` | Ausschnitt aus dem Kamerabild → Bild fürs Netz |
| `kern/datensatz.py` | Fahrten von der Festplatte lesen, Blöcke bilden |
| `kern/training.py` | Training: Augmentierung, Ausgleich, Early Stopping, blockweise Validierung (Variante B und C) |
| `kern/konstanten.py`, `kern/version.py` | Netzgröße, Lenkbereich; Code-Version (Git-Commit) |

**Pi:**

| Datei | Aufgabe |
|---|---|
| `app.py` | Webserver und Steuerzentrale: Modi, Steuerschleife (30-mal pro Sekunde), Sicherheit |
| `einstellungen.py` | Alle wichtigen Zahlen an einer Stelle (Bildgrößen, Raten, Ordner) |
| `fahrzeug.py` | Motoren (mit elektronischem Differential), Lenkung, Kamera-Servos, Kalibrierung |
| `kamera.py` | Kamerabilder holen, Overlay im Livebild |
| `controller.py` | Nintendo-Controller mit evdev auslesen (zum Testen direkt startbar) |
| `fahrten.py` | Fahrten aufnehmen, speichern, umbenennen, löschen |
| `trainingssteuerung.py` | Training starten (Pi oder extern, mit Rückfall) und Modell speichern |
| `linie.py` | Linienerkennung im Kamerabild (Suchstreifen, Schwellwert, Tracking) |
| `kamera_regler.py` | PD-Regler für die aktive Kamera, Suche bei verlorener Linie |
| `regler_einmessen.py` | Bewertung von Sprungantworten zum Einmessen der Reglerwerte |
| `akku.py` | Ladestand aus der Akkuspannung |
| `extern.py` | Mit der externen Trainingsressource sprechen (Suche, Test, Training) |
| `konfiguration.py` | Gespeicherte Einstellungen (`konfiguration.json`) |
| `modelle.py` | Modelle speichern, laden, umbenennen, löschen |
| `templates/`, `static/` | Die Weboberfläche (HTML, CSS, JavaScript) |

**Mac:** `mac_worker/` – der Trainings-Dienst (eigene [README](mac_worker/README.md)).

Daten liegen in `daten/` (nicht im Git-Repository):

```
daten/fahrten/2026-10-26_14-29-58/   meta.json, frames.csv, bilder/000001.jpg ...
daten/modelle/2026-10-26_15-01-11/   meta.json, modell.pt
```
