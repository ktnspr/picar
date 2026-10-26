// training.js – Modus 2: Trainingsdaten auswählen, Training starten, Fortschritt und Modelle anzeigen.

"use strict";

const lernkurveZiel = document.getElementById("lernkurve");
const lernkurveLegende = document.getElementById("lernkurve-legende");
const lernkurveTitel = document.getElementById("lernkurve-titel");

// ---------------------------------------------------------------------
// Auswahl der Trainingsdaten
// ---------------------------------------------------------------------

let bekannteFahrten = [];

async function fahrtenAuswahlLaden() {
  const liste = await senden("/api/fahrten");
  if (!liste) return;
  const vorher = new Set(gewaehlteFahrten());
  const neu = bekannteFahrten.length === 0;   // beim ersten Laden alle auswählen
  bekannteFahrten = liste;
  const ziel = document.getElementById("fahrten-auswahl");
  if (liste.length === 0) {
    ziel.textContent = "Noch keine Fahrten.";
    summeAnzeigen();
    return;
  }
  ziel.innerHTML = "";
  for (const fahrt of liste) {
    const zeile = document.createElement("label");
    const aktiv = fahrt.kamera_modus === "aktiv";
    zeile.innerHTML = `<input type="checkbox" value="${fahrt.id}"> <b class="name"></b>
      <span class="marke ${aktiv ? "aktiv" : ""}">${aktiv ? "aktive Kamera → C" : "feste Kamera → B"}</span>
      <span>– ${fahrt.frames} Bilder, ${sekundenText(fahrt.dauer_s)}, Tempo ${fahrt.tempo} %,
      Kamera ${aktiv ? "" : fahrt.kamera.schwenken + "° / "}${fahrt.kamera.neigen}°, Ausschnitt ab ${Math.round(fahrt.bild.ausschnitt_oben * 100)} %,
      Kalibrierung ${fahrt.kalibrierung ? "gespeichert" : "unbekannt"}</span>`;
    zeile.querySelector(".name").textContent = fahrt.anzeigename;
    zeile.querySelector("input").checked = neu || vorher.has(fahrt.id);
    zeile.querySelector("input").addEventListener("change", summeAnzeigen);
    ziel.appendChild(zeile);
  }
  summeAnzeigen();
}

function gewaehlteFahrten() {
  return [...document.querySelectorAll("#fahrten-auswahl input:checked")].map((feld) => feld.value);
}

// Passen die ausgewählten Fahrten zusammen? Das prüft der Server (gemeinsamer Kern).
// Nur dann lässt sich das Training starten.
let auswahlPasst = true;

async function summeAnzeigen() {
  const gewaehlt = bekannteFahrten.filter((f) => gewaehlteFahrten().includes(f.id));
  const bilder = gewaehlt.reduce((summe, f) => summe + f.frames, 0);
  const warnung = document.getElementById("auswahl-warnung");
  let text = `${gewaehlt.length} Fahrten ausgewählt, ${bilder} Bilder.`;
  if (gewaehlt.length === 0) {
    auswahlPasst = false;
    warnung.classList.add("versteckt");
  } else {
    const pruefung = await senden("/api/training/pruefen", { fahrten: gewaehlt.map((f) => f.id) });
    if (!pruefung) return;
    auswahlPasst = pruefung.passt;
    if (pruefung.passt) {
      text += pruefung.variante === "C"
        ? " Es wird ein Modell der Variante C trainiert (Bild + Schwenkwinkel, aktive Kamera)."
        : " Es wird ein Modell der Variante B trainiert (nur Bild, feste Kamera).";
    }
    const meldungen = pruefung.passt ? pruefung.hinweise
      : ["Diese Fahrten passen nicht zusammen – so kann nicht trainiert werden:", ...pruefung.unterschiede];
    warnung.innerHTML = "";
    for (const meldung of meldungen) {
      const zeile = document.createElement("div");
      zeile.textContent = meldung;
      warnung.appendChild(zeile);
    }
    warnung.classList.toggle("versteckt", meldungen.length === 0);
  }
  document.getElementById("auswahl-summe").textContent = text;
  document.getElementById("training-start").disabled = !auswahlPasst || trainingLiefVorher;
}

document.getElementById("alle-fahrten").addEventListener("click", () => {
  document.querySelectorAll("#fahrten-auswahl input").forEach((feld) => { feld.checked = true; });
  summeAnzeigen();
});
document.getElementById("keine-fahrten").addEventListener("click", () => {
  document.querySelectorAll("#fahrten-auswahl input").forEach((feld) => { feld.checked = false; });
  summeAnzeigen();
});

// ---------------------------------------------------------------------
// Training starten, abbrechen, Fortschritt anzeigen
// ---------------------------------------------------------------------

document.getElementById("training-start").addEventListener("click", async () => {
  const gruendlich = document.querySelector("input[name=gruendlich]:checked").value === "ja";
  const ort = document.querySelector("input[name=ort]:checked").value;   // "pi" oder "extern"
  const status = await senden("/api/training/start", { fahrten: gewaehlteFahrten(), gruendlich: gruendlich, ort: ort });
  if (status) trainingAnzeigen(status);
});
document.getElementById("training-beenden").addEventListener("click", () => senden("/api/training/beenden", {}));
document.getElementById("training-abbrechen").addEventListener("click", () => {
  if (confirm("Training abbrechen? Es wird kein Modell gespeichert.")) senden("/api/training/abbrechen", {});
});

let trainingLiefVorher = false;

function trainingAnzeigen(status) {
  document.getElementById("fortschritt-balken").style.width = (status.fortschritt * 100) + "%";
  document.getElementById("training-text").textContent = status.fehler ? "Fehler: " + status.fehler : status.text;
  // Deutlicher Hinweis, wenn die externe Ressource nicht erreichbar war und der Pi übernommen hat
  const hinweis = document.getElementById("training-hinweis");
  hinweis.textContent = status.hinweis || "";
  hinweis.classList.toggle("versteckt", !status.hinweis);
  document.getElementById("training-start").disabled = status.laeuft || !auswahlPasst;
  document.getElementById("training-abbrechen").disabled = !status.laeuft;
  document.getElementById("training-beenden").disabled = !status.laeuft;
  if (status.laeuft || trainingLiefVorher) {
    lernkurveZeichnen(lernkurveZiel, lernkurveLegende, lernkurveTitel, status.kurven);
  }
  if (trainingLiefVorher && !status.laeuft) modelleLaden();   // fertig → neues Modell in der Liste
  trainingLiefVorher = status.laeuft;
}

// Jede Sekunde den Fortschritt abfragen, solange der Trainings-Reiter offen ist
setInterval(async () => {
  if (document.getElementById("modus-training").classList.contains("versteckt")) return;
  const status = await senden("/api/training/status");
  if (status) trainingAnzeigen(status);
}, 1000);

// ---------------------------------------------------------------------
// Liste der Modelle
// ---------------------------------------------------------------------

// Variante, Kamera und Kalibrierung aus dem Steckbrief (ältere Modelle kennen nicht alles)
function varianteText(modell) {
  if (!modell.variante) return "B (älteres Modell, ohne Angaben zur Aufnahme)";
  return modell.variante === "C" ? "C – Bild + Schwenkwinkel (aktive Kamera)" : "B – nur Bild (feste Kamera)";
}

function kameraText(modell) {
  const a = modell.aufnahme;
  if (!a) return `schwenken ${modell.kamera.schwenken}°, neigen ${modell.kamera.neigen}°` +
                 (modell.kamera_einheitlich === false ? " (Fahrten uneinheitlich!)" : "");
  if (a.kamera_modus === "aktiv") {
    const r = a.regler || {};
    return `aktiv, neigen ${a.kamera.neigen}° – Regler Kp ${r.kp}, Kd ${r.kd}, Totzone ${r.totzone}°, ` +
           `bis ${r.max_geschwindigkeit}°/s, ±${r.schwenk_max}°`;
  }
  return `fest, schwenken ${a.kamera.schwenken}°, neigen ${a.kamera.neigen}°`;
}

function kalibrierungText(modell) {
  const k = modell.aufnahme && modell.aufnahme.kalibrierung;
  return k ? `Lenkung ${k.lenkung}°, Kamera schwenken ${k.schwenken}°, neigen ${k.neigen}° (wird beim Fahren übernommen)`
           : "unbekannt (beim Fahren gilt die gespeicherte)";
}

// Wo, worauf und wie lange wurde trainiert? (Ältere Modelle haben diese Angabe noch nicht.)
function trainiertAufText(modell) {
  const t = modell.trainiert_auf;
  if (!t) return "Pi (CPU)";
  let text = `${t.ort === "extern" ? t.name : "Pi"} (${t.geraet.toUpperCase()}), ${Math.round(t.dauer_s)} s`;
  if (t.ort === "extern") text += ` – mit Übertragung ${Math.round(t.gesamtdauer_s)} s, Code-Version ${t.code_version}`;
  if (t.hinweis) text += ` – ${t.hinweis}`;
  return text;
}

async function modelleLaden() {
  const liste = await senden("/api/modelle");
  if (!liste) return;
  const ziel = document.getElementById("modelle-liste");
  if (liste.length === 0) {
    ziel.textContent = "Noch keine Modelle.";
    return;
  }
  ziel.innerHTML = "";
  for (const modell of liste) {
    const v = modell.validierung;
    const eintrag = document.createElement("div");
    eintrag.className = "eintrag";
    eintrag.style.gridTemplateColumns = "1fr auto";
    eintrag.innerHTML = `
      <div>
        <div class="name"></div>
        <dl class="modell-werte">
          <dt>Fehler (Prüfen)</dt><dd><b>${v.fehler_grad.toFixed(1)}°</b> – zum Vergleich „immer geradeaus“: ${v.vergleich_grad.toFixed(1)}°</dd>
          <dt>Prüfmethode</dt><dd>${v.methode}${v.je_durchgang.length > 1 ? " (" + v.je_durchgang.map((f) => f.toFixed(1) + "°").join(", ") + ")" : ""}</dd>
          <dt>Fahrten</dt><dd class="fahrten-namen"></dd>
          <dt>Bilder</dt><dd>${modell.bilder_gesamt} (davon ${v.lern_bilder} Lernen / ${v.pruef_bilder} Prüfen im Probetraining)</dd>
          <dt>Training</dt><dd>${Math.round(modell.trainingsdauer_s)} s, ${modell.epochen} Epochen, Modus ${modell.modus === "gruendlich" ? "gründlich" : "schnell"}</dd>
          <dt>Trainiert auf</dt><dd>${trainiertAufText(modell)}</dd>
          ${modell.hinweis ? `<dt>Hinweis</dt><dd class="schlecht">${modell.hinweis}</dd>` : ""}
          <dt>Variante</dt><dd>${varianteText(modell)}</dd>
          <dt>Bild fürs Netz</dt><dd>${modell.bildgroesse[0]} × ${modell.bildgroesse[1]} Pixel, Ausschnitt ab ${Math.round(modell.ausschnitt_oben * 100)} %${modell.ausschnitt_einheitlich === false ? " (Fahrten uneinheitlich!)" : ""}</dd>
          <dt>Kamera</dt><dd>${kameraText(modell)}</dd>
          <dt>Kalibrierung</dt><dd>${kalibrierungText(modell)}</dd>
          <dt>Geschwindigkeit</dt><dd>${modell.aufnahme && modell.aufnahme.tempo !== undefined ? modell.aufnahme.tempo : modell.tempo} % – wird beim Fahren übernommen</dd>
          <dt>Netz</dt><dd>${modell.architektur}, ${modell.parameter.toLocaleString("de-DE")} Parameter</dd>
        </dl>
      </div>
      <div class="aktionen">
        <button class="kurve">Lernkurve</button>
        <button class="umbenennen">Umbenennen</button>
        <button class="loeschen gefahr">Löschen</button>
      </div>`;
    eintrag.querySelector(".name").textContent =
      modell.anzeigename === modell.id ? modell.id : `${modell.anzeigename} (${modell.id})`;
    eintrag.querySelector(".fahrten-namen").textContent =
      modell.fahrten.map((f) => `${f.anzeigename} (${f.frames})`).join(", ");
    eintrag.querySelector(".kurve").addEventListener("click", async () => {
      const kurven = await senden(`/api/modelle/${modell.id}/lernkurve`);
      lernkurveZeichnen(lernkurveZiel, lernkurveLegende, lernkurveTitel, kurven);
      lernkurveTitel.textContent += ` – ${modell.anzeigename}`;
    });
    eintrag.querySelector(".umbenennen").addEventListener("click", async () => {
      const name = prompt("Neuer Name für das Modell:", modell.anzeigename);
      if (name !== null) {
        await senden(`/api/modelle/${modell.id}/umbenennen`, { name: name });
        modelleLaden();
      }
    });
    eintrag.querySelector(".loeschen").addEventListener("click", async () => {
      if (confirm(`Modell „${modell.anzeigename}“ wirklich löschen?`)) {
        await senden(`/api/modelle/${modell.id}/loeschen`, {});
        modelleLaden();
      }
    });
    ziel.appendChild(eintrag);
  }
}

// Beim Wechsel in den Trainings-Reiter die Listen auffrischen
for (const knopf of document.querySelectorAll(".reiter button[data-modus=training]")) {
  knopf.addEventListener("click", () => { fahrtenAuswahlLaden(); modelleLaden(); });
}
fahrtenAuswahlLaden();
modelleLaden();
