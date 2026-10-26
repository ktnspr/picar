# PiCar-X Fernsteuerung

Zwei Wege, den SunFounder PiCar-X V2.0 fernzusteuern – jeweils mit Livebild der Frontkamera:

| Ordner | Steuerung | Browser-Adresse |
|---|---|---|
| `handy_fernsteuerung/` | Bedienfeld im Handy-Browser (Knöpfe und Schieberegler) | `http://<IP-des-Pi>:8000` |
| `controller_fernsteuerung/` | Nintendo Switch Pro Controller per Bluetooth; Browser zeigt das Kamerabild im Vollbild | `http://<IP-des-Pi>:8001` |
| `end2end/` | Eigenständiges Projekt: Ein neuronales Netz lernt, einer Linie zu folgen (eigene [README](end2end/README.md)) | `http://<IP-des-Pi>:8080` |

**Immer nur eines der Programme starten** – alle brauchen Kamera und Motoren.

## Voraussetzungen

- Die SunFounder-Module `robot-hat`, `vilib` und `picar-x` sind installiert
  ([Anleitung](https://docs.sunfounder.com/projects/picar-x-v20/en/latest/python/install_all_modules.html)).
- Flask ist dadurch schon vorhanden (siehe `requirements.txt`).
- **Einmalig** den Ordner für die Kalibrierwerte anlegen, damit die Programme ohne `sudo` laufen:

  ```bash
  sudo mkdir -p /opt/picar-x && sudo chown pi:pi /opt/picar-x
  ```

> **Erster Test:** Das Auto aufbocken, sodass die Räder frei in der Luft drehen!

Beenden jeweils mit **Strg+C** – dabei stoppen die Motoren, Lenkung und Kamera stellen sich geradeaus.

## Handy-Fernsteuerung

```bash
cd ~/prof-playground/handy_fernsteuerung
python3 server.py
```

Der Server zeigt die Adresse an, z. B. `http://192.168.178.42:8000`.
Diese im Handy-Browser öffnen (Handy im selben WLAN, quer halten).

| Element | Funktion |
|---|---|
| Lenkung (links) | Schieberegler, springt beim Loslassen in die Mitte zurück |
| Mitte ◀ ▶ (unter der Lenkung) | Feinjustierung, falls das Auto nicht geradeaus fährt: verschiebt die Mitte um je 1°, wird dauerhaft gespeichert |
| Tempo (links) | 0–100 %, wirkt sofort – auch während der Fahrt |
| Vorwärts / Rückwärts (rechts) | Einmal tippen: fährt dauerhaft, bis STOP oder die Gegenrichtung gedrückt wird |
| STOP (rechts) | Hält sofort an |
| Kamera schwenken / neigen | Bewegt die Kamera, „Zentrieren“ stellt sie geradeaus |
| Justieren (neben den Kamerareglern) | Feinjustierung der Kamera-Mitte mit Pfeiltasten, wird dauerhaft und systemweit gespeichert |
| Akku (oben rechts) | Geschätzter Ladestand, darunter die gemessene Spannung |

**Totmannschaltung:** Die Webseite schickt alle 200 ms ein Lebenszeichen an das Auto.
Kommt 500 ms lang keins an (WLAN weg, Seite geschlossen, Handy gesperrt), stoppen die
Motoren sofort. Die Seite zeigt dann eine rote Warnung. Nach dem Wiederverbinden bleibt
das Auto stehen, bis wieder „Vorwärts“ oder „Rückwärts“ gedrückt wird.

## Controller-Fernsteuerung

```bash
cd ~/prof-playground/controller_fernsteuerung
python3 controller_fahren.py
```

Das Kamerabild mit Akkustand gibt es im Browser unter `http://<IP-des-Pi>:8001`
(Tippen auf das Bild schaltet den Vollbildmodus ein).

**Kamera und Lenkung justieren:** Der Knopf „Justieren“ oben auf der Seite stellt die
Kamera auf ihre Mitte. Mit den Pfeiltasten verschiebt man die Mitte von Kamera und Lenkung
um je 1°, bis beide genau geradeaus zeigen. Die Werte speichert picarx in
`/opt/picar-x/picar-x.conf` – sie gelten also systemweit (auch für die Handy-Fernsteuerung
und die SunFounder-Beispiele).

| Controller | Funktion |
|---|---|
| linker Stick | fahren und lenken: hoch/runter = stufenlos vorwärts/rückwärts, links/rechts = lenken (mit Differential) |
| ZR halten / ZL halten | vorwärts / rückwärts mit festem Tempo (loslassen = anhalten) |
| Steuerkreuz ▲ / ▼ | festes Tempo für ZR/ZL +10 % / −10 % (wird im Terminal angezeigt) |
| B | Stopp (hat Vorrang vor allem anderen) |
| rechter Stick | Kamera bewegen |
| A | Kamera zentrieren |

Der Controller ist per Bluetooth gekoppelt und verbindet sich nach einem Tastendruck
(z. B. Home) von selbst. Kommen 0,3 s lang keine Daten vom Controller (außer Reichweite,
ausgeschaltet), hält das Auto an. Zum Testen der Tasten: `python3 gamepad.py`.

## Aufbau des Codes

**Gemeinsame Bausteine** (im Hauptordner, von beiden Programmen benutzt):

| Datei | Aufgabe |
|---|---|
| `auto.py` | Steuert Motoren, Lenkung und Kamera-Halterung; enthält die Totmannschaltung |
| `differential.py` | Elektronisches Differential: berechnet in Kurven die Geschwindigkeit jedes Hinterrads |
| `kamera.py` | Holt die Kamerabilder und schickt sie als Video-Stream an den Browser |
| `akku.py` | Schätzt den Ladestand aus der Akkuspannung (Entladekurve + Glättung) |
| `motortest.py` | Messprogramm (Auto aufgebockt!): welcher Motor links ist und ab welchem PWM-Wert ein Rad dreht |

**`handy_fernsteuerung/`**

| Datei | Aufgabe |
|---|---|
| `server.py` | Webserver (Flask): liefert die Seite aus und nimmt Befehle entgegen |
| `templates/index.html` | Aufbau der Webseite |
| `static/style.css` | Aussehen der Webseite |
| `static/steuerung.js` | Logik im Browser: Knöpfe, Regler, Herzschlag, Akku-Anzeige |

**`controller_fernsteuerung/`**

| Datei | Aufgabe |
|---|---|
| `controller_fahren.py` | Steuerschleife für den Controller + kleiner Webserver für das Kamerabild |
| `gamepad.py` | Liest den Controller aus (Tasten, Sticks, Verbindungsüberwachung) |
| `templates/vollbild.html` | Vollbild-Kamerabild mit Akku, Tempo und Controller-Status |
