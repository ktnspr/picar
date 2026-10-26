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
„schnell“ rund 6 Minuten, „gründlich“ rund 15.

**3. Autonom fahren:** Modell wählen – Kamerawinkel, Bildausschnitt und Geschwindigkeit
werden wie in den Trainingsdaten eingestellt. Das Netz lenkt schon im Stand (zum Ausprobieren).
Motoren ein, „Autonom fahren“. Controller: A = Start/Stopp, B = Notstopp.

## Messwerte auf dem Raspberry Pi 5

| Was | Messung | gewählt |
|---|---|---|
| Kamera | 60 Bilder/s bei 320 × 240 | 30 Bilder/s |
| Netz: Rechenzeit pro Bild | ca. 1 ms (3 ms mit Vorbereitung) | 30 Lenkentscheidungen/s |
| Netz: Training | ca. 600 Bilder/s (bei 48 × 160) | – |
| Aufnahme | – | 10 Bilder/s |

Beim Training wird der Pi über 80 °C heiß und drosselt etwas – ein Lüfter hilft.

## Aufbau des Codes

| Datei | Aufgabe |
|---|---|
| `app.py` | Webserver und Steuerzentrale: Modi, Steuerschleife (30-mal pro Sekunde), Sicherheit |
| `einstellungen.py` | Alle wichtigen Zahlen an einer Stelle (Bildgrößen, Raten, Ordner) |
| `fahrzeug.py` | Motoren (mit elektronischem Differential), Lenkung, Kamera-Servos, Kalibrierung |
| `kamera.py` | Kamerabilder holen, Ausschnitt fürs Netz, Overlay im Livebild |
| `controller.py` | Nintendo-Controller mit evdev auslesen (zum Testen direkt startbar) |
| `fahrten.py` | Fahrten aufnehmen, speichern, umbenennen, löschen |
| `netz.py` | Das neuronale Netz (PilotNet, verkleinert) |
| `training.py` | Training: Daten laden, Blöcke, Augmentierung, Early Stopping, Validierung |
| `modelle.py` | Modelle speichern, laden, umbenennen, löschen |
| `templates/`, `static/` | Die Weboberfläche (HTML, CSS, JavaScript) |

Daten liegen in `daten/` (nicht im Git-Repository):

```
daten/fahrten/2026-10-26_14-29-58/   meta.json, frames.csv, bilder/000001.jpg ...
daten/modelle/2026-10-26_15-01-11/   meta.json, modell.pt
```
