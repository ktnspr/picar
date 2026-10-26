"""
modelle.py – Speichert die trainierten Modelle und verwaltet sie.

Jedes Training legt einen Ordner an, benannt nach dem Zeitpunkt:

    daten/modelle/2026-10-26_15-10-44/
        modell.pt      die gelernten Gewichte des Netzes
        meta.json      alles Wissenswerte: verwendete Fahrten, Validierungsergebnis,
                       Trainingsdauer, Bildgröße, Kamerawinkel, Geschwindigkeit, Lernkurve

Der Ordnername ändert sich nie. Umbenennen ändert nur den Anzeigenamen in meta.json.
"""

import json
import shutil
from datetime import datetime

import torch

from einstellungen import MODELLE
from kern.netz import PilotNetKlein


def _meta_lesen(ordner):
    with open(ordner / "meta.json", encoding="utf-8") as datei:
        return json.load(datei)


def _meta_schreiben(ordner, meta):
    with open(ordner / "meta.json", "w", encoding="utf-8") as datei:
        json.dump(meta, datei, indent=2, ensure_ascii=False)


def modell_ordner(modell_id):
    """Der Ordner zu einem Modell – nur, wenn es dieses Modell wirklich gibt."""
    ordner = MODELLE / modell_id
    if ordner.parent != MODELLE or not (ordner / "meta.json").exists():
        raise ValueError(f"Unbekanntes Modell: {modell_id}")
    return ordner


def speichern(gewichte, meta):
    """Speichert die Gewichte (state_dict) eines frisch trainierten Netzes samt Steckbrief.

    Egal ob auf dem Pi oder dem Mac trainiert: Vor dem Speichern laden wir die Gewichte
    einmal in ein Netz – so fällt sofort auf, wenn sie nicht zum Netz passen.
    Ergebnis: die Modell-ID.
    """
    PilotNetKlein().load_state_dict(gewichte)
    modell_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    ordner = MODELLE / modell_id
    ordner.mkdir(parents=True)
    torch.save(gewichte, ordner / "modell.pt")
    meta = {"anzeigename": modell_id, "erstellt": datetime.now().isoformat(timespec="seconds"), **meta}
    _meta_schreiben(ordner, meta)
    return modell_id


def laden(modell_id):
    """Lädt ein Modell. Ergebnis: (netz, meta)."""
    ordner = modell_ordner(modell_id)
    netz = PilotNetKlein()
    netz.load_state_dict(torch.load(ordner / "modell.pt", weights_only=True))
    netz.eval()   # Vorhersage-Modus (z. B. kein Dropout)
    return netz, _meta_lesen(ordner)


def alle_modelle():
    """Liste aller Modelle, neueste zuerst (ohne die lange Lernkurve)."""
    if not MODELLE.exists():
        return []
    modelle = []
    for ordner in sorted(MODELLE.iterdir(), reverse=True):
        if (ordner / "meta.json").exists():
            meta = _meta_lesen(ordner)
            meta.pop("lernkurve", None)
            meta["id"] = ordner.name
            modelle.append(meta)
    return modelle


def lernkurve(modell_id):
    return _meta_lesen(modell_ordner(modell_id)).get("lernkurve")


def umbenennen(modell_id, neuer_name):
    ordner = modell_ordner(modell_id)
    meta = _meta_lesen(ordner)
    meta["anzeigename"] = neuer_name.strip() or modell_id
    _meta_schreiben(ordner, meta)


def loeschen(modell_id):
    shutil.rmtree(modell_ordner(modell_id))
