"""
dienst.py – Trainings-Dienst für den Mac (oder einen anderen schnellen Rechner).

Der Raspberry Pi schickt die ausgewählten Fahrten als Archiv hierher. Der Dienst
trainiert mit dem GLEICHEN Code wie der Pi (Paket kern im Ordner darüber),
meldet Fortschritt und Lernkurve und gibt am Ende das Modell samt Steckbrief zurück.

Start:   ./start.sh      (richtet beim ersten Mal alles ein)

Absicherung: Jede Anfrage muss das gemeinsame Token mitschicken
(„Authorization: Bearer <token>“). Das Token steht in config.json.

Der Pi spricht NUR mit diesem Dienst – er bekommt keinen anderen Zugang zum Mac.
"""

import asyncio
import io
import json
import secrets
import shutil
import sys
import tarfile
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import torch
import torch.nn as nn
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import Response

# Der gemeinsame Kern liegt einen Ordner höher (end2end/kern)
ORDNER = Path(__file__).resolve().parent
sys.path.insert(0, str(ORDNER.parent))

from kern.netz import PilotNetKlein, bilder_zu_tensor  # noqa: E402
from kern.konstanten import NETZ_BREITE, NETZ_HOEHE  # noqa: E402
from kern.training import Training  # noqa: E402
from kern.version import code_version  # noqa: E402

import ankuendigung  # noqa: E402

PROTOKOLL = 1                       # wird erhöht, wenn sich die Schnittstelle ändert
VARIANTEN = ["B", "C"]              # B = nur Kamerabild, C = Kamerabild + Schwenkwinkel (aktive Kamera)
KONFIGURATION = ORDNER / "config.json"
ARBEITSORDNER = ORDNER / "auftraege"


# ----------------------------------------------------------------------
# Konfiguration und Rechengerät
# ----------------------------------------------------------------------

def konfiguration_laden():
    if not KONFIGURATION.exists():
        raise SystemExit(f"Keine {KONFIGURATION.name} gefunden. Bitte ./start.sh benutzen "
                         "(legt sie an) oder config.example.json kopieren.")
    with open(KONFIGURATION, encoding="utf-8") as datei:
        konfig = json.load(datei)
    if not konfig.get("token") or "ÄNDERN" in konfig["token"]:
        raise SystemExit("Bitte in config.json ein eigenes Token eintragen.")
    return konfig


def geraet_messen(sekunden=2.0):
    """Misst, wie viele Trainingsbilder pro Sekunde CPU und (falls vorhanden) MPS schaffen.

    MPS ist die Grafikeinheit der Apple-Chips. Bei so einem kleinen Netz ist sie nicht
    automatisch schneller als die CPU – deshalb messen wir lieber nach.
    """
    kandidaten = ["cpu"]
    if torch.backends.mps.is_available():
        kandidaten.append("mps")
    ergebnisse = {}
    for name in kandidaten:
        geraet = torch.device(name)
        netz = PilotNetKlein().to(geraet)
        optimierer = torch.optim.Adam(netz.parameters(), 1e-3)
        x = bilder_zu_tensor(torch.randint(0, 255, (64, NETZ_HOEHE, NETZ_BREITE, 3), dtype=torch.uint8).numpy())
        x, y = x.to(geraet), torch.rand(64, device=geraet)
        schritte, start = 0, None
        while start is None or time.perf_counter() - start < sekunden:
            if schritte == 3:
                start = time.perf_counter()   # die ersten Schritte zum Aufwärmen nicht mitzählen
            optimierer.zero_grad()
            nn.functional.mse_loss(netz(x).squeeze(1), y).backward()
            optimierer.step()
            if name == "mps":
                torch.mps.synchronize()   # warten, bis die Grafikeinheit wirklich fertig ist
            schritte += 1
        ergebnisse[name] = round((schritte - 3) * 64 / (time.perf_counter() - start))
    return max(ergebnisse, key=ergebnisse.get), ergebnisse


# ----------------------------------------------------------------------
# Zustand des Dienstes
# ----------------------------------------------------------------------

konfig = konfiguration_laden()
dienst = {
    "version": code_version(),
    "geraet": None,          # wird beim Start gemessen
    "messung": {},
    "auftrag": None,         # der aktuelle (oder zuletzt fertige) Auftrag
}


@asynccontextmanager
async def lebensdauer(app):
    """Läuft beim Start und beim Beenden des Dienstes."""
    if konfig.get("geraet", "auto") == "auto":
        print("Messe, ob CPU oder MPS schneller ist ...")
        dienst["geraet"], dienst["messung"] = geraet_messen()
    else:
        dienst["geraet"] = konfig["geraet"]
    print(f"Rechengerät: {dienst['geraet']}  (Messung in Bildern/s: {dienst['messung'] or 'übersprungen'})")
    print(f"Code-Version: {dienst['version']}")
    # Die mDNS-Bibliothek darf nicht im Takt des Webservers laufen – deshalb in einem eigenen Thread
    ankuendigung_aktiv = await asyncio.to_thread(ankuendigung.starten, konfig["name"], konfig["port"],
                                                 dienst["version"], PROTOKOLL)
    print(f"Dienst „{konfig['name']}“ läuft auf Port {konfig['port']}"
          + (" und ist per mDNS im Netz angekündigt." if ankuendigung_aktiv else "."))
    yield
    await asyncio.to_thread(ankuendigung.beenden)


app = FastAPI(title="PiCar-X Trainings-Dienst", lifespan=lebensdauer)


def token_pruefen(authorization: str = Header(default="")):
    """Jede Anfrage muss das richtige Token mitschicken."""
    erwartet = "Bearer " + konfig["token"]
    if not secrets.compare_digest(authorization.encode(), erwartet.encode()):
        raise HTTPException(status_code=401, detail="Falsches oder fehlendes Token.")


def auftrag_holen(auftrag_id):
    auftrag = dienst["auftrag"]
    if auftrag is None or auftrag["id"] != auftrag_id:
        raise HTTPException(status_code=404, detail="Unbekannter Auftrag.")
    return auftrag


# ----------------------------------------------------------------------
# Schnittstelle (alle Anfragen brauchen das Token)
# ----------------------------------------------------------------------

@app.get("/info", dependencies=[Depends(token_pruefen)])
def info():
    """Wer bin ich, welches Gerät, welche Code-Version – für „Verbindung testen“ auf dem Pi."""
    auftrag = dienst["auftrag"]
    return {
        "dienst": "picar-training",
        "protokoll": PROTOKOLL,
        "name": konfig["name"],
        "version": dienst["version"],
        "geraet": dienst["geraet"],
        "messung": dienst["messung"],
        "torch": torch.__version__,
        "varianten": VARIANTEN,
        "beschaeftigt": bool(auftrag and auftrag["training"].laeuft),
    }


@app.post("/auftraege", dependencies=[Depends(token_pruefen)])
async def auftrag_annehmen(anfrage: Request, einstellungen: str):
    """Nimmt einen Trainingsauftrag an.

    Inhalt der Anfrage: ein tar-Archiv mit den Fahrten (je ein Ordner).
    einstellungen (URL-Parameter, JSON): {"fahrten": [...], "gruendlich": true/false, "pi_version": "..."}
    """
    if dienst["auftrag"] and dienst["auftrag"]["training"].laeuft:
        raise HTTPException(status_code=409, detail="Es läuft bereits ein Training.")
    einstellungen = json.loads(einstellungen)
    alter_auftrag = dienst["auftrag"]
    if alter_auftrag:
        shutil.rmtree(alter_auftrag["ordner"], ignore_errors=True)

    # Archiv empfangen und zwischenspeichern
    ARBEITSORDNER.mkdir(exist_ok=True)
    ordner = Path(tempfile.mkdtemp(prefix="auftrag-", dir=ARBEITSORDNER))
    archiv = ordner / "fahrten.tar"
    with open(archiv, "wb") as datei:
        async for stueck in anfrage.stream():
            datei.write(stueck)

    # Archiv auspacken – nur normale Dateien, nichts außerhalb des Auftragsordners
    with tarfile.open(archiv) as tar:
        if hasattr(tarfile, "data_filter"):
            tar.extractall(ordner, filter="data")
        else:   # ältere Python-Versionen: selbst prüfen
            for eintrag in tar:
                ziel = (ordner / eintrag.name).resolve()
                if not str(ziel).startswith(str(ordner)) or not (eintrag.isfile() or eintrag.isdir()):
                    raise HTTPException(status_code=400, detail=f"Ungültiger Eintrag im Archiv: {eintrag.name}")
                tar.extract(eintrag, ordner)
    archiv.unlink()

    # Die Fahrten in derselben Reihenfolge wie auf dem Pi (wichtig für die Blöcke)
    fahrt_ordner = [ordner / fahrt_id for fahrt_id in einstellungen["fahrten"]]
    for fahrt in fahrt_ordner:
        if fahrt.parent != ordner or not (fahrt / "meta.json").exists() or not (fahrt / "frames.csv").exists():
            raise HTTPException(status_code=400, detail=f"Fahrt fehlt oder ist unvollständig: {fahrt.name}")

    training = Training(geraet=dienst["geraet"])
    auftrag = {"id": uuid.uuid4().hex[:12], "ordner": ordner, "training": training, "modell": None,
               "pi_version": einstellungen.get("pi_version")}

    def fertig(training):
        """Nach dem Training: Gewichte für den Pi bereitlegen, Bilder wieder löschen."""
        puffer = io.BytesIO()
        torch.save(training.ergebnis_netz.state_dict(), puffer)
        auftrag["modell"] = puffer.getvalue()

    try:
        # prüft auch, ob die Fahrten zusammenpassen (gleiche Kalibrierung, gleiche Kameraeinstellungen)
        training.starten(fahrt_ordner, bool(einstellungen.get("gruendlich")), bei_ende=fertig)
    except ValueError as fehler:
        shutil.rmtree(ordner, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(fehler))
    dienst["auftrag"] = auftrag
    print(f"Auftrag {auftrag['id']}: Variante {training.variante}, {len(fahrt_ordner)} Fahrten, "
          f"{'gründlich' if einstellungen.get('gruendlich') else 'schnell'}, Gerät {dienst['geraet']}")
    return {"auftrag": auftrag["id"]}


@app.get("/auftraege/{auftrag_id}", dependencies=[Depends(token_pruefen)])
def auftrag_status(auftrag_id: str):
    """Fortschritt, Text und Lernkurve – genau wie beim Training auf dem Pi."""
    auftrag = auftrag_holen(auftrag_id)
    training = auftrag["training"]
    status = training.status() | {"geraet": dienst["geraet"], "name": konfig["name"]}
    status["fertig"] = auftrag["modell"] is not None and not training.laeuft
    if status["fertig"]:
        status["meta"] = training.ergebnis_meta
        shutil.rmtree(auftrag["ordner"], ignore_errors=True)   # Bilder werden nicht mehr gebraucht
    return status


@app.post("/auftraege/{auftrag_id}/beenden", dependencies=[Depends(token_pruefen)])
def auftrag_beenden(auftrag_id: str):
    auftrag_holen(auftrag_id)["training"].beenden()
    return {"ok": True}


@app.post("/auftraege/{auftrag_id}/abbrechen", dependencies=[Depends(token_pruefen)])
def auftrag_abbrechen(auftrag_id: str):
    auftrag_holen(auftrag_id)["training"].abbrechen()
    return {"ok": True}


@app.get("/auftraege/{auftrag_id}/modell", dependencies=[Depends(token_pruefen)])
def modell_holen(auftrag_id: str):
    """Die gelernten Gewichte (PyTorch state_dict, auf der CPU)."""
    auftrag = auftrag_holen(auftrag_id)
    if auftrag["modell"] is None:
        raise HTTPException(status_code=409, detail="Das Training ist noch nicht fertig.")
    return Response(auftrag["modell"], media_type="application/octet-stream")


@app.delete("/auftraege/{auftrag_id}", dependencies=[Depends(token_pruefen)])
def auftrag_loeschen(auftrag_id: str):
    """Der Pi hat alles abgeholt – Auftrag vergessen."""
    auftrag = auftrag_holen(auftrag_id)
    if auftrag["training"].laeuft:
        raise HTTPException(status_code=409, detail="Das Training läuft noch.")
    shutil.rmtree(auftrag["ordner"], ignore_errors=True)
    dienst["auftrag"] = None
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=konfig["port"], log_level="warning")
