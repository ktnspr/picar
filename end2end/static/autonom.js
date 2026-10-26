// autonom.js – Modus 3: Modell auswählen und autonom fahren lassen.

"use strict";

const modellAuswahl = document.getElementById("modell-auswahl");
const autonomKnopf = document.getElementById("autonom-knopf");
let modellListe = [];

async function modellAuswahlLaden() {
  const liste = await senden("/api/modelle");
  if (!liste) return;
  modellListe = liste;
  const gewaehlt = modellAuswahl.value;
  modellAuswahl.innerHTML = '<option value="">– bitte wählen –</option>';
  for (const modell of liste) {
    const option = document.createElement("option");
    option.value = modell.id;
    option.textContent = `${modell.anzeigename} – Fehler ${modell.validierung.fehler_grad.toFixed(1)}°`;
    modellAuswahl.appendChild(option);
  }
  modellAuswahl.value = gewaehlt;
}

function modellInfoAnzeigen(modellId) {
  const modell = modellListe.find((m) => m.id === modellId);
  document.getElementById("modell-info").textContent = modell
    ? `Eingestellt wie in den Trainingsdaten: Kamera schwenken ${modell.kamera.schwenken}°, ` +
      `neigen ${modell.kamera.neigen}°, Bildausschnitt ab ${Math.round(modell.ausschnitt_oben * 100)} %, ` +
      `Tempo ${modell.tempo} %. Trainiert mit: ${modell.fahrten.map((f) => f.anzeigename).join(", ")}.`
    : "";
}

// Ein Modell auswählen = laden und Kamera, Ausschnitt, Tempo einstellen
modellAuswahl.addEventListener("change", async () => {
  if (!modellAuswahl.value) return;
  const zustand = await senden("/api/autonom/modell", { modell: modellAuswahl.value });
  if (zustand) modellInfoAnzeigen(zustand.autonom.modell_id);
});

autonomKnopf.addEventListener("click", () => {
  const faehrt = letzterZustand && letzterZustand.autonom.faehrt;
  senden("/api/autonom/fahren", { an: !faehrt });
});

function autonomAnzeigen(zustand) {
  const a = zustand.autonom;
  if (a.modell_id && modellAuswahl.value !== a.modell_id && modellListe.length) {
    modellAuswahl.value = a.modell_id;   // z. B. nach dem Neuladen der Seite
    modellInfoAnzeigen(a.modell_id);
  }
  autonomKnopf.disabled = !a.modell_id;
  autonomKnopf.textContent = a.faehrt ? "■ Anhalten" : "▶ Autonom fahren";
  autonomKnopf.className = "gross " + (a.faehrt ? "gefahr" : "wichtig");

  document.getElementById("autonom-lenkwinkel").textContent =
    a.lenkwinkel === null ? "–" : `${a.lenkwinkel > 0 ? "+" : ""}${a.lenkwinkel.toFixed(1)}°`;
  document.getElementById("autonom-rechenzeit").textContent = a.rechenzeit_ms === null ? "–" : `${a.rechenzeit_ms} ms`;
  document.getElementById("autonom-rate").textContent = a.rate === null ? "–" : `${Math.round(a.rate)} pro Sekunde`;
}

// Beim Wechsel in den Autonom-Reiter die Modellliste auffrischen
document.querySelector(".reiter button[data-modus=autonom]").addEventListener("click", modellAuswahlLaden);
modellAuswahlLaden();
