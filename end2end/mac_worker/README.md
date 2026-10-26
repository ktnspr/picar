# Trainings-Dienst für den Mac

Mit diesem Dienst trainiert ein Mac (Apple Silicon) die Netze für den PiCar-X statt des
Raspberry Pi. Der Pi schickt die ausgewählten Fahrten hierher, der Mac trainiert mit
**demselben Code** wie der Pi (Paket `../kern`) und schickt das fertige Modell zurück.
Bedient wird alles weiter über die Weboberfläche des Pi.

Der Dienst

- misst beim Start, ob die Grafikeinheit (MPS) oder die CPU für das kleine Netz schneller ist,
- kündigt sich per mDNS im lokalen Netz an – der Pi findet ihn über „Suchen“,
- lässt nur Anfragen mit dem richtigen Token zu,
- meldet seine Code-Version (Git-Commit), damit der Pi Versionsunterschiede erkennt.

Der Pi bekommt keinen anderen Zugang zum Mac als diesen Dienst.

## Voraussetzungen

- Mac mit Apple Silicon (M1 oder neuer), macOS 13 oder neuer
- Python 3.10 oder neuer: `python3 --version` (falls zu alt: `brew install python`)
- git (bringen die Xcode Command Line Tools mit: `xcode-select --install`)

## Einrichten und starten

```bash
git clone https://github.com/ktnspr/picar.git
cd picar/end2end/mac_worker
./start.sh
```

Beim ersten Start richtet `start.sh` alles ein (das dauert ein paar Minuten):

1. eine Python-Umgebung `.venv` mit PyTorch, FastAPI usw.
2. die Datei `config.json` mit einem **zufälligen Token** – das Token wird angezeigt.

In `config.json` kannst du den Namen ändern, unter dem der Mac im Netz erscheint:

```json
{
  "name": "Alexanders Mac",
  "port": 8765,
  "token": "…",
  "geraet": "auto"
}
```

`geraet`: `"auto"` (messen), `"mps"` oder `"cpu"`. Nach einer Änderung den Dienst neu starten.

Danach startet der Dienst immer mit demselben Befehl: `./start.sh`. Beenden mit **Strg+C**.

Beim ersten Start fragt macOS eventuell, ob Python eingehende Verbindungen annehmen darf –
mit **Erlauben** bestätigen, sonst erreicht der Pi den Dienst nicht.

## Auf dem Pi eintragen

Weboberfläche des Pi → **2 · Trainieren** → **Externe Trainingsressource**:
„Suchen“ drücken und den Mac auswählen (oder Hostname/IP und Port von Hand eintragen),
das Token aus `config.json` eintragen, „Verbindung testen“, „Speichern“.

## Aktualisieren

```bash
cd picar/end2end/mac_worker
git pull
./start.sh
```

`start.sh` installiert geänderte Pakete automatisch nach. Mac und Pi sollten denselben
Stand haben – sonst zeigt der Pi beim Verbindungstest eine Warnung.

## Dateien

| Datei | Aufgabe |
|---|---|
| `dienst.py` | der HTTP-Dienst (FastAPI): Aufträge annehmen, trainieren, Modell zurückgeben |
| `ankuendigung.py` | Anmeldung im lokalen Netz per mDNS (Zeroconf) |
| `start.sh` | einrichten (beim ersten Mal) und starten |
| `config.example.json` | Vorlage für `config.json` (die echte Datei mit Token kommt nicht ins Repository) |
| `requirements.txt` | Python-Pakete |

## Schnittstelle (für Neugierige)

Alle Anfragen brauchen den Kopf `Authorization: Bearer <token>`.

| Anfrage | Bedeutung |
|---|---|
| `GET /info` | Name, Rechengerät, Code-Version, beschäftigt? |
| `POST /auftraege?einstellungen=…` | Trainingsauftrag; Inhalt: tar-Archiv mit den Fahrten |
| `GET /auftraege/<id>` | Fortschritt, Text, Lernkurve; am Ende der Steckbrief |
| `POST /auftraege/<id>/beenden` | aufhören, bisher bestes Modell liefern |
| `POST /auftraege/<id>/abbrechen` | aufhören, nichts liefern |
| `GET /auftraege/<id>/modell` | die gelernten Gewichte (PyTorch) |
| `DELETE /auftraege/<id>` | Auftrag aufräumen |
