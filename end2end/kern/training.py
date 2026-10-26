"""
training.py – Trainiert das Netz im Hintergrund (gemeinsam für Pi und Mac).

Ablauf im Modus „schnell“:
  1. Daten laden: aus jedem Bild den Ausschnitt fürs Netz ausschneiden und verkleinern.
  2. Blöcke bilden: Die Fahrten werden in zusammenhängende Abschnitte von 3 Sekunden geteilt.
  3. Probetraining: Auf 80 % der Blöcke lernen, an den übrigen 20 % prüfen (Validierung).
     Dabei stellt sich heraus, nach wie vielen Durchgängen (Epochen) das Netz am besten ist.
     Das Training hört von selbst auf, wenn es 5 Epochen lang nicht besser wird (Early Stopping).
  4. Finales Modell: noch einmal auf ALLEN Daten trainieren, mit genau so vielen Epochen.

Mit „Beenden“ kann man jederzeit aufhören – dann wird das bisher beste Modell gespeichert.

Im Modus „gründlich“ wird Schritt 3 viermal gemacht (4-fache Kreuzvalidierung):
Jedes Mal dient ein anderes Viertel der Blöcke zum Prüfen. Das dauert länger,
liefert aber ein verlässlicheres Ergebnis.

Warum Blöcke statt zufälliger Aufteilung? Bei 10 Bildern pro Sekunde sind benachbarte
Bilder fast gleich. Würden wir zufällig aufteilen, hätte das Netz zu fast jedem
Prüfbild einen „Zwilling“ beim Lernen gesehen – das Ergebnis wäre geschönt.

Gespeichert wird hier nichts: Das fertige Netz und sein Steckbrief stehen am Ende in
ergebnis_netz und ergebnis_meta. Was damit passiert, entscheidet der Aufrufer
(der Pi speichert es als Modell, der Mac schickt es an den Pi zurück).
"""

import threading
import time

import numpy as np
import torch
import torch.nn as nn

from .datensatz import aufnahme_einstellungen, daten_laden, einheitlichkeit_pruefen, meta_lesen
from .konstanten import LENKUNG_MAX, NETZ_BREITE, NETZ_HOEHE
from .netz import ARCHITEKTUR, PilotNetKlein, anzahl_parameter, bilder_zu_tensor
from .version import code_version

# ---------- Aufteilung in Blöcke ----------
PUFFER_BILDER = 5         # so viele Bilder (0,5 s) Abstand zwischen Lern- und Prüfdaten
HOLDOUT_JEDER = 5         # jeder 5. Block wird Prüfblock → 20 %
FALTEN = 4                # Kreuzvalidierung im Modus „gründlich“

# ---------- Lernen ----------
BATCH = 64                # so viele Bilder auf einmal
LERNRATE = 1e-3
GEDULD_LERNRATE = 2       # so viele Epochen ohne Verbesserung → Lernrate halbieren
GEDULD_STOPP = 5          # so viele Epochen ohne Verbesserung → aufhören (Early Stopping)
MAX_EPOCHEN = 60          # Sicherheitsgrenze, falls Early Stopping nie greift
HELLIGKEIT = 0.2          # Helligkeit zufällig um ±20 % ändern
KLASSEN_BREITE = 5        # Grad – für den Ausgleich häufiger und seltener Lenkwinkel
MAX_GEWICHT = 5           # seltene Lenkwinkel höchstens 5-mal so oft zeigen wie häufige


class Abgebrochen(Exception):
    """„Abbrechen“ gedrückt: Training verwerfen, nichts speichern."""


# ----------------------------------------------------------------------
# 2.: Lern- und Prüfdaten trennen (die Blöcke bildet datensatz.py)
# ----------------------------------------------------------------------

def aufteilen(bloecke, fahrt_nummern, pruef_bloecke):
    """Teilt in Lern- und Prüfdaten. Lernbilder direkt neben Prüfblöcken werden weggelassen (Puffer)."""
    pruefen = np.isin(bloecke, pruef_bloecke)
    nahe_an_pruefung = pruefen.copy()
    for verschiebung in range(1, PUFFER_BILDER + 1):
        # Ist ein Nachbar (bis zu 5 Bilder entfernt, gleiche Fahrt) ein Prüfbild?
        for richtung in (verschiebung, -verschiebung):
            nachbar_prueft = np.roll(pruefen, richtung)
            gleiche_fahrt = np.roll(fahrt_nummern, richtung) == fahrt_nummern
            nahe_an_pruefung |= nachbar_prueft & gleiche_fahrt
    return np.where(~nahe_an_pruefung)[0], np.where(pruefen)[0]


# ----------------------------------------------------------------------
# 3. und 4.: Lernen
# ----------------------------------------------------------------------

def stichproben_gewichte(winkel):
    """Gleicht aus, dass manche Lenkwinkel viel häufiger vorkommen als andere.

    Die Lenkwinkel werden in Klassen zu je 5° eingeteilt. Bilder aus seltenen Klassen
    werden beim Lernen öfter gezeigt, Bilder aus häufigen seltener.
    (Nach Betrag, weil das Spiegeln links und rechts ohnehin gleich häufig macht.)
    """
    klasse = (np.abs(winkel) * LENKUNG_MAX // KLASSEN_BREITE).astype(int)
    haeufigkeit = np.bincount(klasse)
    gewicht = 1.0 / haeufigkeit[klasse]
    gewicht = np.minimum(gewicht, gewicht.min() * MAX_GEWICHT)
    return torch.from_numpy(gewicht)


def verbessern(x, y, schwenken):
    """Augmentierung: zufällig spiegeln (Lenkwinkel umdrehen) und Helligkeit verändern.
    Beim Spiegeln dreht sich auch der Schwenkwinkel der Kamera um (Variante C)."""
    spiegeln = torch.rand(len(x)) < 0.5
    x, y, schwenken = x.clone(), y.clone(), schwenken.clone()
    x[spiegeln] = x[spiegeln].flip(-1)       # links ↔ rechts
    y[spiegeln] = -y[spiegeln]
    schwenken[spiegeln] = -schwenken[spiegeln]
    faktor = 1 + (torch.rand(len(x), 1, 1, 1) * 2 - 1) * HELLIGKEIT
    x = ((x + 0.5) * faktor).clamp(0, 1) - 0.5
    return x, y, schwenken


def fehler_in_grad(netz, bilder, winkel, schwenkwinkel, indizes, geraet):
    """Mittlerer Fehler der Vorhersage in Grad (ohne Augmentierung)."""
    netz.eval()
    summe = 0.0
    with torch.no_grad():
        for start in range(0, len(indizes), 256):
            teil = indizes[start:start + 256]
            x = bilder_zu_tensor(bilder[teil]).to(geraet)
            s = torch.from_numpy(schwenkwinkel[teil]).to(geraet)
            vorhersage = netz(x, s).squeeze(1).clamp(-1, 1).cpu()
            summe += (vorhersage - torch.from_numpy(winkel[teil])).abs().sum().item()
    return summe / len(indizes) * LENKUNG_MAX


class Training:
    """Führt ein Training im Hintergrund aus und berichtet über den Fortschritt.

    geraet:  "cpu" oder "mps" (Grafikeinheit der Apple-Chips)
    threads: so viele Rechenkerne benutzen (None = alle, die PyTorch möchte)
    """

    def __init__(self, geraet="cpu", threads=None):
        self.geraet = torch.device(geraet)
        self.threads = threads
        self.ergebnis_netz = None   # nach dem Training: das fertige Netz (auf der CPU)
        self.ergebnis_meta = None   # ... und sein Steckbrief
        self.laeuft = False
        self.text = ""
        self.fortschritt = 0.0
        self.kurven = {}        # Name → Liste der Fehler pro Epoche (für die Lernkurve)
        self.fehler = None
        self._abbrechen = False   # alles verwerfen
        self._beenden = False     # aufhören und das bisher beste Modell speichern

    def status(self):
        return {"laeuft": self.laeuft, "text": self.text, "fortschritt": round(self.fortschritt, 3),
                "kurven": self.kurven, "fehler": self.fehler, "fertig": self.ergebnis_netz is not None}

    def starten(self, fahrt_ordner, gruendlich, bei_ende=None):
        """Startet das Training im Hintergrund.

        fahrt_ordner: Liste der Ordner der Fahrten (pathlib.Path)
        bei_ende:     wird nach erfolgreichem Training aufgerufen (mit diesem Training-Objekt),
                      solange laeuft noch True ist – z. B. um das Modell zu speichern.
        """
        if self.laeuft:
            raise ValueError("Es läuft bereits ein Training.")
        if not fahrt_ordner:
            raise ValueError("Bitte mindestens eine Fahrt auswählen.")
        # Nur Fahrten mit denselben Aufnahme-Einstellungen passen zusammen
        unterschiede = einheitlichkeit_pruefen([meta_lesen(ordner) for ordner in fahrt_ordner])
        if unterschiede:
            raise ValueError("Die Fahrten passen nicht zusammen: " + " | ".join(unterschiede))
        # Variante: feste Kamera → B (nur Bild), aktive Kamera → C (Bild + Schwenkwinkel)
        self.variante = "C" if aufnahme_einstellungen(meta_lesen(fahrt_ordner[0]))["kamera_modus"] == "aktiv" else "B"
        self.laeuft, self._abbrechen, self._beenden = True, False, False
        self.text, self.fortschritt, self.kurven = "Starte ...", 0.0, {}
        self.ergebnis_netz, self.ergebnis_meta, self.fehler = None, None, None
        threading.Thread(target=self._ausfuehren, args=(fahrt_ordner, gruendlich, bei_ende), daemon=True).start()

    def abbrechen(self):
        """Sofort aufhören und nichts speichern."""
        self._abbrechen = True

    def beenden(self):
        """Sofort aufhören, aber das bisher beste Modell speichern."""
        self._beenden = True

    # ------------------------------------------------------------------

    def _ausfuehren(self, fahrt_ordner, gruendlich, bei_ende):
        try:
            self._trainieren(fahrt_ordner, gruendlich)
            if bei_ende:
                bei_ende(self)
        except Abgebrochen:
            self.text = "Training abgebrochen."
        except Exception as fehler:
            self.fehler = str(fehler)
            self.text = "Fehler beim Training."
            print("Fehler beim Training:", repr(fehler))
        finally:
            self.laeuft = False

    def _melden(self, text, fortschritt=None):
        if self._abbrechen:
            raise Abgebrochen()
        self.text = text
        if fortschritt is not None:
            self.fortschritt = fortschritt

    def _trainieren(self, fahrt_ordner, gruendlich):
        if self.threads:
            torch.set_num_threads(self.threads)
        startzeit = time.time()
        modus = "gruendlich" if gruendlich else "schnell"

        # 1. und 2.: Daten laden, Blöcke bilden
        bilder, winkel, schwenkwinkel, bloecke, fahrt_nummern = daten_laden(fahrt_ordner, lambda t: self._melden(t, 0.02))
        self._schwenkwinkel = schwenkwinkel
        alle_bloecke = np.unique(bloecke)
        if len(alle_bloecke) < 2 * HOLDOUT_JEDER:
            raise ValueError("Zu wenige Daten – bitte mindestens etwa 30 Sekunden Fahrt auswählen.")

        # 3.: Probetraining(s) mit Validierung
        if gruendlich:
            durchgaenge = [alle_bloecke[i::FALTEN] for i in range(FALTEN)]   # jedes 4. Block-Paket
            methode = f"{FALTEN}-fache blockweise Kreuzvalidierung"
        else:
            durchgaenge = [alle_bloecke[HOLDOUT_JEDER // 2::HOLDOUT_JEDER]]  # jeder 5. Block
            methode = f"Blockweiser Holdout ({100 // HOLDOUT_JEDER} % der Blöcke)"
        anteil_probe = 0.7 if gruendlich else 0.6   # so viel vom Fortschrittsbalken

        ergebnisse = []
        for nummer, pruef_bloecke in enumerate(durchgaenge):
            lern_idx, pruef_idx = aufteilen(bloecke, fahrt_nummern, pruef_bloecke)
            name = f"Probetraining {nummer + 1}/{len(durchgaenge)}" if gruendlich else "Probetraining"
            basis = 0.05 + anteil_probe * nummer / len(durchgaenge)
            ergebnis = self._lernen(bilder, winkel, lern_idx, pruef_idx, name,
                                    fortschritt=(basis, anteil_probe / len(durchgaenge)))
            # Zum Vergleich: Wie groß wäre der Fehler, wenn man immer den mittleren Lenkwinkel nähme?
            ergebnis["vergleich"] = float(np.abs(winkel[pruef_idx] - winkel[lern_idx].mean()).mean() * LENKUNG_MAX)
            ergebnis["lern_bilder"], ergebnis["pruef_bilder"] = len(lern_idx), len(pruef_idx)
            ergebnisse.append(ergebnis)
            if self._beenden:
                break   # „Beenden“ gedrückt: keine weiteren Probetrainings

        epochen = max(1, round(np.mean([e["beste_epoche"] for e in ergebnisse])))
        if self._beenden:
            # Vorzeitig beendet: Wir nehmen das beste Netz aus dem (letzten) Probetraining.
            # Es hat nur einen Teil der Daten gesehen – das steht dann auch in der Beschreibung.
            netz = ergebnisse[-1]["netz"]
            hinweis = ("Vorzeitig beendet: Modell aus dem Probetraining (ohne finales Training "
                       "auf allen Daten).")
            if gruendlich and len(ergebnisse) < FALTEN:
                hinweis += f" Kreuzvalidierung nur mit {len(ergebnisse)} von {FALTEN} Durchgängen."
        else:
            # 4.: Finales Modell auf allen Daten, mit der gefundenen Epochenzahl und Lernrate
            lernraten = ergebnisse[0]["lernraten"][:epochen]
            lernraten += [lernraten[-1]] * (epochen - len(lernraten))
            final = self._lernen(bilder, winkel, np.arange(len(bilder)), None, "Finales Modell",
                                 fortschritt=(0.05 + anteil_probe, 0.95 - 0.05 - anteil_probe),
                                 lernraten=lernraten)
            netz = final["netz"]
            hinweis = None
            if self._beenden:
                epochen = final["epochen"]
                hinweis = f"Vorzeitig beendet: finales Training nach {epochen} Epochen gestoppt."

        # Ergebnis bereitstellen – mit allem, was man über das Modell wissen sollte
        self._melden("Stelle das Ergebnis zusammen ...", 0.97)
        meta = self._beschreibung(fahrt_ordner, modus, methode, ergebnisse, epochen, bilder, startzeit)
        meta["hinweis"] = hinweis
        self.ergebnis_netz, self.ergebnis_meta = netz.to("cpu"), meta
        mae = meta["validierung"]["fehler_grad"]
        self._melden(f"Fertig in {meta['trainingsdauer_s']:.0f} s – mittlerer Fehler {mae:.1f}° "
                     f"(zum Vergleich: immer geradeaus {meta['validierung']['vergleich_grad']:.1f}°)."
                     + (f" {hinweis}" if hinweis else ""), 1.0)

    def _lernen(self, bilder, winkel, lern_idx, pruef_idx, name, fortschritt, lernraten=None):
        """Trainiert ein frisches Netz. Mit Prüfdaten: bis zum Early Stopping. Ohne: feste Lernraten-Liste."""
        torch.manual_seed(0)
        netz = PilotNetKlein(mit_schwenkwinkel=self.variante == "C").to(self.geraet)
        s_alle = torch.from_numpy(self._schwenkwinkel)
        optimierer = torch.optim.Adam(netz.parameters(), lr=LERNRATE)
        planer = torch.optim.lr_scheduler.ReduceLROnPlateau(optimierer, factor=0.5, patience=GEDULD_LERNRATE)
        gewichte = stichproben_gewichte(winkel[lern_idx])
        y_alle = torch.from_numpy(winkel)
        anzahl_epochen = len(lernraten) if lernraten else MAX_EPOCHEN

        lern_kurve, pruef_kurve = [], []
        self.kurven[f"{name}: Lernen"] = lern_kurve
        if pruef_idx is not None:
            self.kurven[f"{name}: Prüfen"] = pruef_kurve
        bester_fehler, beste_epoche, bester_zustand, verwendete_lernraten = float("inf"), 0, None, []
        fertige_epochen = 0

        for epoche in range(1, anzahl_epochen + 1):
            if lernraten:
                for gruppe in optimierer.param_groups:
                    gruppe["lr"] = lernraten[epoche - 1]
            verwendete_lernraten.append(optimierer.param_groups[0]["lr"])

            # Eine Epoche: so viele Bilder ziehen, wie es Lernbilder gibt – seltene Lenkwinkel öfter
            netz.train()
            auswahl = lern_idx[torch.multinomial(gewichte, len(lern_idx), replacement=True).numpy()]
            fehler_summe = 0.0
            for b in range(0, len(auswahl), BATCH):
                if self._beenden:
                    break   # „Beenden“ gedrückt – diese Epoche nicht mehr zu Ende rechnen
                teil = auswahl[b:b + BATCH]
                # Augmentierung auf der CPU, dann aufs Rechengerät (CPU oder Apple-Grafikeinheit)
                x, y, s = verbessern(bilder_zu_tensor(bilder[teil]), y_alle[teil], s_alle[teil])
                x, y, s = x.to(self.geraet), y.to(self.geraet), s.to(self.geraet)
                vorhersage = netz(x, s).squeeze(1)
                verlust = nn.functional.mse_loss(vorhersage, y)
                optimierer.zero_grad()
                verlust.backward()
                optimierer.step()
                fehler_summe += (vorhersage.detach() - y).abs().sum().item()
                if b % (BATCH * 10) == 0:
                    self._fortschritt_melden(name, epoche, b / len(auswahl), anzahl_epochen,
                                             beste_epoche, bester_fehler, pruef_idx is not None, fortschritt)
            if self._beenden and fertige_epochen > 0:
                break
            fertige_epochen = epoche
            lern_kurve.append(round(fehler_summe / len(auswahl) * LENKUNG_MAX, 2))

            if pruef_idx is not None:
                pruef_fehler = fehler_in_grad(netz, bilder, winkel, self._schwenkwinkel, pruef_idx, self.geraet)
                pruef_kurve.append(round(pruef_fehler, 2))
                planer.step(pruef_fehler)   # wird es nicht besser → Lernrate verringern
                if pruef_fehler < bester_fehler:
                    bester_fehler, beste_epoche = pruef_fehler, epoche
                    bester_zustand = {k: v.clone() for k, v in netz.state_dict().items()}
                if epoche - beste_epoche >= GEDULD_STOPP:
                    break   # Early Stopping: seit 5 Epochen keine Verbesserung mehr
            if self._beenden:
                break

        if bester_zustand is not None:
            netz.load_state_dict(bester_zustand)   # das beste Netz behalten, nicht das letzte
        return {"netz": netz, "beste_epoche": beste_epoche or fertige_epochen, "epochen": fertige_epochen,
                "fehler": bester_fehler, "lernraten": verwendete_lernraten}

    def _fortschritt_melden(self, name, epoche, anteil_epoche, anzahl_epochen, beste_epoche, bester_fehler,
                            mit_pruefung, fortschritt):
        """Fortschrittsbalken und Text. Beim Probetraining weiß niemand vorher, wann Early Stopping
        greift – wir schätzen das Ende als „beste Epoche bisher + 5“."""
        if mit_pruefung:
            erwartet = min(MAX_EPOCHEN, max(beste_epoche + GEDULD_STOPP, epoche + 1))
            text = f"{name}: Epoche {epoche}"
            if beste_epoche:
                text += (f" – bisher beste: Epoche {beste_epoche} ({bester_fehler:.1f}°). "
                         f"Stoppt nach {GEDULD_STOPP} Epochen ohne Verbesserung.")
        else:
            erwartet = anzahl_epochen
            text = f"{name}: Epoche {epoche} von {anzahl_epochen}"
        wert = fortschritt[0] + fortschritt[1] * min((epoche - 1 + anteil_epoche) / erwartet, 1)
        self._melden(text, max(self.fortschritt, wert))   # der Balken soll nicht zurückspringen

    def _beschreibung(self, fahrt_ordner, modus, methode, ergebnisse, epochen, bilder, startzeit):
        """Stellt alle Angaben zum Modell zusammen (der Steckbrief, als meta.json gespeichert)."""
        infos = [meta_lesen(ordner) | {"id": ordner.name} for ordner in fahrt_ordner]
        gesamt = sum(i["frames"] for i in infos)
        erste = infos[0]   # alle Fahrten haben dieselben Aufnahme-Einstellungen (geprüft beim Start)
        return {
            "variante": self.variante,
            "eingaben": ["bild", "schwenkwinkel"] if self.variante == "C" else ["bild"],
            # Alles, was beim Fahren genauso eingestellt werden muss wie bei der Aufnahme:
            "aufnahme": {
                "kamera_modus": erste.get("kamera_modus", "fest"),
                "tempo": int(round(erste["tempo"])),           # mit dieser Geschwindigkeit wurde gefahren
                "kamera": erste["kamera"],
                "ausschnitt_oben": erste["bild"]["ausschnitt_oben"],
                "kalibrierung": erste.get("kalibrierung"),         # None = unbekannt (ältere Fahrten)
                "regler": erste.get("regler"),                     # nur bei aktiver Kamera
                "linienerkennung": erste.get("linienerkennung"),
            },
            "fahrten": [{"id": i["id"], "anzeigename": i["anzeigename"], "frames": i["frames"]} for i in infos],
            "bilder_gesamt": int(len(bilder)),
            "modus": modus,
            "validierung": {
                "methode": methode,
                "fehler_grad": round(float(np.mean([e["fehler"] for e in ergebnisse])), 2),
                "vergleich_grad": round(float(np.mean([e["vergleich"] for e in ergebnisse])), 2),
                "je_durchgang": [round(e["fehler"], 2) for e in ergebnisse],
                "lern_bilder": ergebnisse[0]["lern_bilder"],
                "pruef_bilder": ergebnisse[0]["pruef_bilder"],
            },
            "epochen": epochen,
            "trainingsdauer_s": round(time.time() - startzeit, 1),
            "geraet": self.geraet.type,          # "cpu" oder "mps"
            "code_version": code_version(),
            "bildgroesse": [NETZ_HOEHE, NETZ_BREITE],
            "ausschnitt_oben": erste["bild"]["ausschnitt_oben"],
            "kamera": erste["kamera"],
            "tempo": round(sum(i["tempo"] * i["frames"] for i in infos) / gesamt),
            "architektur": ARCHITEKTUR,
            "parameter": anzahl_parameter(PilotNetKlein(mit_schwenkwinkel=self.variante == "C")),
            "lernkurve": self.kurven,
        }
